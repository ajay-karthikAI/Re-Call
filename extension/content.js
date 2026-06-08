const CHUNK_INTERVAL_MS = 6000;
const POLL_INTERVAL_MS = 4500;
const END_WATCH_INTERVAL_MS = 3500;

const END_PHRASES = [
  "you left the meeting",
  "you've left the meeting",
  "you have left the meeting",
  "you left the call",
  "you've left the call",
  "you have left the call",
  "return to home screen",
  "meeting has ended",
  "this meeting has ended",
  "the host has ended this meeting",
  "call has ended",
];

const EXPORT_OPTIONS = [
  { format: "pptx", label: "PowerPoint", extension: ".pptx" },
  { format: "pdf", label: "PDF", extension: ".pdf" },
  { format: "markdown", label: "Markdown", extension: ".md" },
];

const state = {
  apiBaseUrl: "http://127.0.0.1:8000",
  platform: detectPlatform(),
  status: "prompt",
  sessionId: null,
  startedAt: 0,
  elapsedSeconds: 0,
  recorder: null,
  audioContext: null,
  captureStreams: [],
  uploadPromises: [],
  error: "",
  warning: "",
  detectedStopReason: "",
  pollTimer: null,
  clockTimer: null,
  endWatchTimer: null,
};

let shadowRoot = null;

function detectPlatform() {
  const host = window.location.hostname;
  if (host.includes("meet.google.com")) {
    return "Google Meet";
  }
  if (host.includes("teams")) {
    return "Microsoft Teams";
  }
  if (host.includes("zoom")) {
    return "Zoom";
  }
  return "Meeting";
}

function sendExtensionMessage(type, payload = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, payload }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Re: Call extension request failed."));
        return;
      }
      resolve(response.data);
    });
  });
}

function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function getMeetingTitle() {
  const platformPattern = /(google meet|microsoft teams|zoom meeting|zoom)$/i;
  const cleaned = document.title
    .replace(/\s+[-|]\s+(Google Meet|Microsoft Teams|Zoom).*$/i, "")
    .replace(platformPattern, "")
    .trim();

  if (cleaned && cleaned.length > 2) {
    return cleaned.slice(0, 220);
  }

  const pathToken = window.location.pathname.replace(/^\/+|\/+$/g, "").split("/")[0];
  if (pathToken && pathToken.length > 2 && !["wc", "meet"].includes(pathToken)) {
    return `${state.platform} ${pathToken}`.slice(0, 220);
  }

  return `${state.platform} call`;
}

function getRecorderOptions() {
  if (!window.MediaRecorder) {
    throw new Error("This browser does not support MediaRecorder.");
  }

  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  return mimeType ? { mimeType } : undefined;
}

function stopTracks(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read recorded audio."));
    reader.readAsDataURL(blob);
  });
}

function clearTimers() {
  if (state.clockTimer) {
    window.clearInterval(state.clockTimer);
    state.clockTimer = null;
  }
  if (state.endWatchTimer) {
    window.clearInterval(state.endWatchTimer);
    state.endWatchTimer = null;
  }
}

function cleanupCapture() {
  if (state.recorder && state.recorder.state !== "inactive") {
    try {
      state.recorder.stop();
    } catch {
      // The normal stop path may have already stopped it.
    }
  }

  state.captureStreams.forEach(stopTracks);
  state.captureStreams = [];
  state.recorder = null;

  if (state.audioContext) {
    state.audioContext.close().catch(() => {});
    state.audioContext = null;
  }

  clearTimers();
}

async function buildMixedAudioStream() {
  if (!navigator.mediaDevices?.getDisplayMedia || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("Meeting recording requires a browser with screen and microphone capture support.");
  }

  const displayStream = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
    preferCurrentTab: true,
  });

  let micStream = null;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch {
    state.warning = "Microphone permission was skipped, so only shared meeting audio will be recorded.";
  }

  const displayAudioTracks = displayStream.getAudioTracks();
  const micAudioTracks = micStream?.getAudioTracks() || [];

  if (!displayAudioTracks.length && !micAudioTracks.length) {
    stopTracks(displayStream);
    stopTracks(micStream);
    throw new Error("No audio source was shared. Start again and enable tab audio or microphone access.");
  }

  if (!displayAudioTracks.length) {
    state.warning = "Tab audio was not shared, so Re: Call is recording microphone audio only.";
  }

  const audioContext = new AudioContext();
  const destination = audioContext.createMediaStreamDestination();

  for (const sourceStream of [displayStream, micStream]) {
    const audioTracks = sourceStream?.getAudioTracks() || [];
    if (audioTracks.length) {
      audioContext.createMediaStreamSource(new MediaStream(audioTracks)).connect(destination);
    }
  }

  displayStream.getVideoTracks().forEach((track) => track.stop());
  state.audioContext = audioContext;
  state.captureStreams = [displayStream, micStream].filter(Boolean);

  return destination.stream;
}

function startClock() {
  state.clockTimer = window.setInterval(() => {
    if (state.status === "recording") {
      state.elapsedSeconds = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
      render();
    }
  }, 1000);
}

function textSuggestsMeetingEnded() {
  const bodyText = document.body?.innerText?.toLowerCase() || "";
  if (!bodyText) {
    return false;
  }
  return END_PHRASES.some((phrase) => bodyText.includes(phrase));
}

function startEndWatcher() {
  state.endWatchTimer = window.setInterval(() => {
    if (state.status !== "recording") {
      return;
    }
    if (textSuggestsMeetingEnded()) {
      state.detectedStopReason = "Meeting ended";
      stopRecording().catch((error) => {
        state.status = "error";
        state.error = error.message;
        render();
      });
    }
  }, END_WATCH_INTERVAL_MS);
}

async function startRecording() {
  if (state.status === "starting" || state.status === "recording") {
    return;
  }

  state.status = "starting";
  state.error = "";
  state.warning = "";
  state.detectedStopReason = "";
  render();

  try {
    const mixedAudioStream = await buildMixedAudioStream();
    const startResponse = await sendExtensionMessage("recall:startRecording", {
      apiBaseUrl: state.apiBaseUrl,
      platform: state.platform,
      title: getMeetingTitle(),
    });

    const recorder = new MediaRecorder(mixedAudioStream, getRecorderOptions());
    state.sessionId = startResponse.session_id;
    state.startedAt = Date.now();
    state.elapsedSeconds = 0;
    state.uploadPromises = [];

    recorder.ondataavailable = (event) => {
      if (!event.data?.size || !state.sessionId) {
        return;
      }
      const upload = blobToDataUrl(event.data).then((audioDataUrl) =>
        sendExtensionMessage("recall:uploadChunk", {
          apiBaseUrl: state.apiBaseUrl,
          sessionId: state.sessionId,
          audioDataUrl,
          mimeType: event.data.type || recorder.mimeType || "audio/webm",
        })
      );
      state.uploadPromises.push(upload);
      upload.catch((error) => {
        state.warning = error.message;
        render();
      });
    };

    recorder.onerror = (event) => {
      state.warning = event.error?.message || "The browser recorder reported an error.";
      render();
    };

    state.recorder = recorder;
    recorder.start(CHUNK_INTERVAL_MS);
    state.status = "recording";
    startClock();
    startEndWatcher();
    render();
  } catch (error) {
    cleanupCapture();
    state.status = "error";
    state.error = error.message;
    render();
  }
}

function waitForRecorderStop() {
  return new Promise((resolve) => {
    const recorder = state.recorder;
    if (!recorder || recorder.state === "inactive") {
      resolve();
      return;
    }
    recorder.addEventListener("stop", resolve, { once: true });
    try {
      recorder.requestData();
      recorder.stop();
    } catch {
      resolve();
    }
  });
}

async function stopRecording() {
  if (!state.sessionId || !state.recorder || state.status === "stopping" || state.status === "processing") {
    return;
  }

  state.status = "stopping";
  state.error = "";
  render();

  const durationSeconds = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
  clearTimers();
  await waitForRecorderStop();

  state.captureStreams.forEach(stopTracks);
  state.captureStreams = [];
  if (state.audioContext) {
    await state.audioContext.close().catch(() => {});
    state.audioContext = null;
  }

  await Promise.allSettled(state.uploadPromises);
  await sendExtensionMessage("recall:stopRecording", {
    apiBaseUrl: state.apiBaseUrl,
    sessionId: state.sessionId,
    durationSeconds,
  });

  state.status = "processing";
  render();
  startMeetingPolling();
}

function startMeetingPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
  }

  const poll = async () => {
    if (!state.sessionId) {
      return;
    }

    try {
      const meeting = await sendExtensionMessage("recall:getMeeting", {
        apiBaseUrl: state.apiBaseUrl,
        sessionId: state.sessionId,
      });
      if (meeting.status === "complete") {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.status = "export";
        render();
      } else if (meeting.status === "error") {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.status = "error";
        state.error = meeting.notes_json?.error || "Re: Call could not process this meeting.";
        render();
      }
    } catch (error) {
      state.warning = error.message;
      render();
    }
  };

  poll();
  state.pollTimer = window.setInterval(poll, POLL_INTERVAL_MS);
}

async function exportMeeting(format) {
  if (!state.sessionId) {
    return;
  }

  state.status = "exporting";
  state.error = "";
  render();

  try {
    await sendExtensionMessage("recall:exportMeeting", {
      apiBaseUrl: state.apiBaseUrl,
      sessionId: state.sessionId,
      format,
    });
    state.status = "done";
    render();
  } catch (error) {
    state.status = "export";
    state.error = error.message;
    render();
  }
}

function dismissOverlay() {
  state.status = "collapsed";
  state.error = "";
  render();
}

function resetOverlay() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  cleanupCapture();
  state.status = "prompt";
  state.sessionId = null;
  state.elapsedSeconds = 0;
  state.error = "";
  state.warning = "";
  state.detectedStopReason = "";
  state.uploadPromises = [];
  render();
}

function button(label, className, action, extra = "") {
  return `<button type="button" class="${className}" data-action="${action}" ${extra}>${label}</button>`;
}

function renderBody() {
  if (state.status === "collapsed") {
    return `
      <button type="button" class="recall-badge" data-action="expand" aria-label="Open Re: Call overlay">
        <span>R:</span>
      </button>
    `;
  }

  if (state.status === "prompt") {
    return `
      <section class="recall-panel">
        <header>
          <span class="recall-mark">R:</span>
          <div>
            <strong>Re: Call</strong>
            <small>${state.platform} overlay</small>
          </div>
        </header>
        <p>Record this meeting?</p>
        <div class="recall-actions">
          ${button("Record", "primary", "start")}
          ${button("Not now", "ghost", "dismiss")}
        </div>
        <small class="recall-disclosure">Visible overlay. Browser and meeting participants may notice recording prompts.</small>
      </section>
    `;
  }

  if (state.status === "starting") {
    return `
      <section class="recall-panel">
        <header>
          <span class="recall-mark pulse">R:</span>
          <div>
            <strong>Starting</strong>
            <small>Choose this tab and enable audio when prompted.</small>
          </div>
        </header>
        <div class="recall-status-line"><span class="spinner"></span><span>Waiting for browser permissions</span></div>
      </section>
    `;
  }

  if (state.status === "recording") {
    return `
      <section class="recall-panel recording">
        <header>
          <span class="recall-dot"></span>
          <div>
            <strong>Recording</strong>
            <small>${formatDuration(state.elapsedSeconds)}</small>
          </div>
        </header>
        ${state.warning ? `<p class="warning">${state.warning}</p>` : ""}
        <div class="recall-actions">
          ${button("Stop", "danger", "stop")}
        </div>
      </section>
    `;
  }

  if (state.status === "stopping") {
    return `
      <section class="recall-panel">
        <header>
          <span class="recall-mark pulse">R:</span>
          <div>
            <strong>Saving audio</strong>
            <small>${state.detectedStopReason || "Recording stopped"}</small>
          </div>
        </header>
        <div class="recall-status-line"><span class="spinner"></span><span>Uploading final chunks</span></div>
      </section>
    `;
  }

  if (state.status === "processing") {
    return `
      <section class="recall-panel">
        <header>
          <span class="recall-mark pulse">R:</span>
          <div>
            <strong>Transcribing</strong>
            <small>Re: Call is creating notes.</small>
          </div>
        </header>
        ${state.warning ? `<p class="warning">${state.warning}</p>` : ""}
        <div class="recall-status-line"><span class="spinner"></span><span>Waiting for transcript</span></div>
      </section>
    `;
  }

  if (state.status === "export" || state.status === "exporting") {
    const disabled = state.status === "exporting" ? "disabled" : "";
    return `
      <section class="recall-panel">
        <header>
          <span class="recall-mark">R:</span>
          <div>
            <strong>${state.status === "exporting" ? "Exporting" : "Meeting ready"}</strong>
            <small>Choose a download format.</small>
          </div>
        </header>
        ${state.error ? `<p class="error">${state.error}</p>` : ""}
        <div class="export-grid">
          ${EXPORT_OPTIONS.map((option) =>
            button(`${option.label}<small>${option.extension}</small>`, "export-option", `export:${option.format}`, disabled)
          ).join("")}
        </div>
      </section>
    `;
  }

  if (state.status === "done") {
    return `
      <section class="recall-panel">
        <header>
          <span class="recall-mark">R:</span>
          <div>
            <strong>Downloaded</strong>
            <small>Your export is ready.</small>
          </div>
        </header>
        <div class="recall-actions">
          ${button("Export another", "secondary", "show-export")}
          ${button("Close", "ghost", "dismiss")}
        </div>
      </section>
    `;
  }

  return `
    <section class="recall-panel">
      <header>
        <span class="recall-mark">R:</span>
        <div>
          <strong>Re: Call error</strong>
          <small>${state.platform}</small>
        </div>
      </header>
      <p class="error">${state.error || "Something went wrong."}</p>
      <div class="recall-actions">
        ${button("Try again", "primary", "reset")}
        ${button("Close", "ghost", "dismiss")}
      </div>
    </section>
  `;
}

function renderStyles() {
  return `
    <style>
      :host {
        all: initial;
        color-scheme: dark;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      * {
        box-sizing: border-box;
      }

      .recall-root {
        position: fixed;
        right: 20px;
        bottom: 20px;
        z-index: 2147483647;
      }

      .recall-panel {
        width: min(328px, calc(100vw - 32px));
        overflow: hidden;
        background:
          radial-gradient(circle at 80% 0%, rgba(168, 255, 96, 0.12), transparent 34%),
          linear-gradient(180deg, rgba(255, 255, 255, 0.075), rgba(255, 255, 255, 0.025)),
          #101214;
        color: #f7f8f6;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 8px;
        box-shadow:
          0 22px 70px rgba(0, 0, 0, 0.42),
          inset 0 1px 0 rgba(255, 255, 255, 0.06);
        padding: 14px;
      }

      .recall-panel header {
        display: flex;
        align-items: center;
        gap: 11px;
        margin-bottom: 12px;
      }

      .recall-panel strong {
        display: block;
        font-size: 15px;
        line-height: 1.25;
        letter-spacing: 0;
        font-weight: 850;
      }

      .recall-panel small {
        display: block;
        color: #a3aaa0;
        font-size: 12px;
        line-height: 1.35;
        letter-spacing: 0;
      }

      .recall-panel p {
        margin: 0 0 12px;
        color: #dce3d8;
        font-size: 14px;
        line-height: 1.45;
        letter-spacing: 0;
      }

      .recall-mark,
      .recall-badge span {
        position: relative;
        display: inline-flex;
        width: 36px;
        height: 36px;
        overflow: hidden;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(168, 255, 96, 0.35);
        border-radius: 7px;
        background:
          radial-gradient(circle at 66% 28%, rgba(168, 255, 96, 0.36), transparent 22%),
          linear-gradient(145deg, #1a1d1b, #090a0b 72%);
        box-shadow:
          inset 0 1px 0 rgba(255, 255, 255, 0.08),
          0 0 28px rgba(168, 255, 96, 0.2);
        color: #a8ff60;
        font-weight: 900;
        font-size: 14px;
      }

      .recall-badge {
        border: 0;
        background: transparent;
        padding: 0;
        cursor: pointer;
        filter: drop-shadow(0 10px 26px rgba(0, 0, 0, 0.45));
      }

      .recall-actions {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      button {
        font: inherit;
        border: 1px solid transparent;
        border-radius: 7px;
        min-height: 36px;
        padding: 0 12px;
        cursor: pointer;
        font-weight: 820;
        letter-spacing: 0;
        transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease;
      }

      button:hover {
        transform: translateY(-1px);
      }

      button:focus-visible {
        outline: 2px solid rgba(168, 255, 96, 0.72);
        outline-offset: 2px;
      }

      button:disabled {
        cursor: wait;
        opacity: 0.62;
      }

      button.primary {
        border-color: rgba(168, 255, 96, 0.42);
        background: linear-gradient(180deg, #a8ff60, #61e887);
        color: #071008;
        box-shadow: 0 0 22px rgba(168, 255, 96, 0.18);
      }

      button.secondary {
        border-color: rgba(255, 255, 255, 0.11);
        background: rgba(255, 255, 255, 0.07);
        color: #f7f8f6;
      }

      button.ghost {
        background: transparent;
        color: #dce3d8;
        border-color: rgba(255, 255, 255, 0.13);
      }

      button.danger {
        border-color: rgba(255, 93, 93, 0.36);
        background: rgba(255, 93, 93, 0.14);
        color: #ffd7d7;
      }

      .recall-disclosure {
        margin-top: 10px;
      }

      .recall-dot {
        width: 16px;
        height: 16px;
        margin: 8px;
        border-radius: 999px;
        background: #ff5d5d;
        box-shadow: 0 0 0 7px rgba(255, 93, 93, 0.16), 0 0 24px rgba(255, 93, 93, 0.3);
      }

      .pulse {
        animation: recall-pulse 1.3s ease-in-out infinite;
      }

      .spinner {
        width: 16px;
        height: 16px;
        border-radius: 999px;
        border: 2px solid rgba(255, 255, 255, 0.25);
        border-top-color: #a8ff60;
        animation: recall-spin 0.8s linear infinite;
      }

      .recall-status-line {
        display: flex;
        align-items: center;
        gap: 10px;
        color: #dce3d8;
        font-size: 13px;
      }

      .warning,
      .error {
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 9px 10px;
        font-size: 13px !important;
      }

      .warning {
        border-color: rgba(255, 209, 102, 0.26);
        background: rgba(255, 209, 102, 0.12);
        color: #fde68a !important;
      }

      .error {
        border-color: rgba(255, 93, 93, 0.28);
        background: rgba(255, 93, 93, 0.12);
        color: #ffb3b3 !important;
      }

      .export-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
      }

      .export-option {
        display: flex;
        min-width: 0;
        min-height: 58px;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 2px;
        background: rgba(255, 255, 255, 0.055);
        color: #f7f8f6;
        border: 1px solid rgba(255, 255, 255, 0.11);
        padding: 8px 6px;
      }

      .export-option:hover {
        border-color: rgba(168, 255, 96, 0.34);
        background: rgba(168, 255, 96, 0.1);
      }

      .export-option small {
        color: #a3aaa0;
      }

      @keyframes recall-spin {
        to { transform: rotate(360deg); }
      }

      @keyframes recall-pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(0.94); }
      }
    </style>
  `;
}

function render() {
  if (!shadowRoot) {
    const host = document.createElement("div");
    host.id = "recall-extension-host";
    document.documentElement.appendChild(host);
    shadowRoot = host.attachShadow({ mode: "open" });
  }

  shadowRoot.innerHTML = `${renderStyles()}<div class="recall-root">${renderBody()}</div>`;

  shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
    element.addEventListener("click", (event) => {
      const action = event.currentTarget.getAttribute("data-action");
      if (action === "start") {
        startRecording();
      } else if (action === "stop") {
        stopRecording().catch((error) => {
          state.status = "error";
          state.error = error.message;
          render();
        });
      } else if (action === "dismiss") {
        dismissOverlay();
      } else if (action === "expand" || action === "reset") {
        resetOverlay();
      } else if (action === "show-export") {
        state.status = "export";
        render();
      } else if (action?.startsWith("export:")) {
        exportMeeting(action.split(":")[1]);
      }
    });
  });
}

async function init() {
  try {
    const settings = await sendExtensionMessage("recall:getSettings");
    state.apiBaseUrl = settings.apiBaseUrl || state.apiBaseUrl;
  } catch {
    // Keep the default API base URL.
  }
  render();
}

init();
