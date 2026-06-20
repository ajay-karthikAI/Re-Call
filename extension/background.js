const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function normalizedApiBaseUrl(value) {
  const trimmed = String(value || DEFAULT_API_BASE_URL).trim().replace(/\/+$/, "");
  return trimmed || DEFAULT_API_BASE_URL;
}

function normalizedApiToken(value) {
  return String(value || "").trim();
}

async function getSettings() {
  const stored = await chrome.storage.local.get({ apiBaseUrl: DEFAULT_API_BASE_URL, apiToken: "" });
  return {
    apiBaseUrl: normalizedApiBaseUrl(stored.apiBaseUrl),
    apiToken: normalizedApiToken(stored.apiToken),
  };
}

function withApiAuth(options = {}, apiToken = "") {
  const token = normalizedApiToken(apiToken);
  if (!token) {
    return options;
  }

  return {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  };
}

async function fetchJson(url, options = {}, apiToken = "") {
  const response = await fetch(url, withApiAuth(options, apiToken));
  if (!response.ok) {
    let message = `${options.method || "GET"} ${url} failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep the status-based message.
    }
    throw new Error(message);
  }
  return response.json();
}

async function blobToDataUrl(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const chunkSize = 0x8000;
  let binary = "";
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return `data:${blob.type || "application/octet-stream"};base64,${btoa(binary)}`;
}

function shouldUseAuthenticatedDownload(downloadUrl, apiBaseUrl, apiToken) {
  if (!normalizedApiToken(apiToken)) {
    return false;
  }
  try {
    const targetUrl = new URL(downloadUrl);
    return targetUrl.pathname.startsWith("/api/files/");
  } catch {
    return false;
  }
}

async function downloadFile(downloadUrl, filename, apiBaseUrl, apiToken) {
  let url = downloadUrl;
  if (shouldUseAuthenticatedDownload(downloadUrl, apiBaseUrl, apiToken)) {
    const response = await fetch(downloadUrl, withApiAuth({}, apiToken));
    if (!response.ok) {
      throw new Error(`Download failed (${response.status})`);
    }
    url = await blobToDataUrl(await response.blob());
  }

  await chrome.downloads.download({
    url,
    filename: filename || undefined,
    saveAs: true,
  });
}

function extensionForMimeType(mimeType) {
  const normalized = String(mimeType || "").toLowerCase();
  if (normalized.includes("mp4")) {
    return "mp4";
  }
  if (normalized.includes("mpeg") || normalized.includes("mp3")) {
    return "mp3";
  }
  if (normalized.includes("ogg") || normalized.includes("oga")) {
    return "ogg";
  }
  if (normalized.includes("wav")) {
    return "wav";
  }
  return "webm";
}

function blobFromPayload(payload) {
  const mimeType = payload.mimeType || "audio/webm";
  if (payload.audioDataUrl) {
    const [header, encoded] = String(payload.audioDataUrl).split(",", 2);
    const contentType = header?.match(/^data:([^;]+);base64$/)?.[1] || mimeType;
    const binary = atob(encoded || "");
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Blob([bytes], { type: contentType });
  }
  return new Blob([payload.audioBuffer], { type: mimeType });
}

async function startRecording(payload) {
  const apiBaseUrl = normalizedApiBaseUrl(payload.apiBaseUrl);
  const apiToken = normalizedApiToken(payload.apiToken);
  return fetchJson(`${apiBaseUrl}/api/recording/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title || "",
      platform: payload.platform || "",
    }),
  }, apiToken);
}

async function uploadChunk(payload) {
  const apiBaseUrl = normalizedApiBaseUrl(payload.apiBaseUrl);
  const apiToken = normalizedApiToken(payload.apiToken);
  const formData = new FormData();
  const mimeType = payload.mimeType || "audio/webm";
  const audioBlob = blobFromPayload(payload);
  const extension = extensionForMimeType(audioBlob.type || mimeType);

  formData.append("session_id", payload.sessionId);
  formData.append("audio", audioBlob, `chunk-${Date.now()}.${extension}`);

  await fetchJson(`${apiBaseUrl}/api/recording/chunk`, {
    method: "POST",
    body: formData,
  }, apiToken);

  return { status: "accepted" };
}

async function stopRecording(payload) {
  const apiBaseUrl = normalizedApiBaseUrl(payload.apiBaseUrl);
  const apiToken = normalizedApiToken(payload.apiToken);
  return fetchJson(`${apiBaseUrl}/api/recording/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: payload.sessionId,
      duration_seconds: payload.durationSeconds || 0,
    }),
  }, apiToken);
}

async function getMeeting(payload) {
  const apiBaseUrl = normalizedApiBaseUrl(payload.apiBaseUrl);
  const apiToken = normalizedApiToken(payload.apiToken);
  return fetchJson(`${apiBaseUrl}/api/meetings/${payload.sessionId}`, {}, apiToken);
}

async function exportMeeting(payload) {
  const apiBaseUrl = normalizedApiBaseUrl(payload.apiBaseUrl);
  const apiToken = normalizedApiToken(payload.apiToken);
  const format = encodeURIComponent(payload.format || "pptx");
  const data = await fetchJson(`${apiBaseUrl}/api/export/${payload.sessionId}?format=${format}`, {
    method: "POST",
  }, apiToken);
  const downloadUrl = data.download_url || data.pptx_url;

  if (!downloadUrl) {
    throw new Error("Export finished, but no download URL was returned.");
  }

  await downloadFile(downloadUrl, data.filename, apiBaseUrl, apiToken);

  return data;
}

const handlers = {
  "recall:getSettings": getSettings,
  "recall:startRecording": startRecording,
  "recall:uploadChunk": uploadChunk,
  "recall:stopRecording": stopRecording,
  "recall:getMeeting": getMeeting,
  "recall:exportMeeting": exportMeeting,
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handler = handlers[message?.type];

  if (!handler) {
    sendResponse({ ok: false, error: "Unknown Re: Call extension action." });
    return false;
  }

  handler(message.payload || {})
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});
