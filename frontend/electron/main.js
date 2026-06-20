const { app, BrowserWindow, ipcMain, Menu, screen, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const APP_ENV = (process.env.APP_ENV || "development").trim().toLowerCase();
const LOCAL_API_BASE_URL = "http://127.0.0.1:8000";
const LOCAL_API_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
const API_BASE_URL = process.env.RECALL_API_BASE_URL || LOCAL_API_BASE_URL;
const API_TOKEN = (process.env.RECALL_API_TOKEN || "").trim();
let backendProcess = null;
let workerProcess = null;
let mainWindow = null;
let overlayWindow = null;
let systemAudioProcess = null;
let systemAudioDiagnostics = null;
let isQuitting = false;
const gotSingleInstanceLock = app.requestSingleInstanceLock();

function localBackendUrl() {
  try {
    const url = new URL(API_BASE_URL);
    if (!LOCAL_API_HOSTS.has(url.hostname.toLowerCase())) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

function validateRuntimeConfig() {
  const errors = [];
  if (!["development", "production"].includes(APP_ENV)) {
    errors.push("APP_ENV must be either development or production.");
  }

  let apiUrl = null;
  try {
    apiUrl = new URL(API_BASE_URL);
  } catch {
    errors.push("RECALL_API_BASE_URL must be a valid URL.");
  }

  if (APP_ENV === "production") {
    if (!process.env.RECALL_API_BASE_URL) {
      errors.push("RECALL_API_BASE_URL is required when APP_ENV=production.");
    }
    if (!API_TOKEN) {
      errors.push("RECALL_API_TOKEN is required when APP_ENV=production.");
    }
    if (apiUrl && LOCAL_API_HOSTS.has(apiUrl.hostname.toLowerCase())) {
      errors.push("RECALL_API_BASE_URL must not point to localhost when APP_ENV=production.");
    }
  }

  if (errors.length) {
    throw new Error(`[Re: Call] Invalid runtime configuration:\n - ${errors.join("\n - ")}`);
  }
}

function backendPythonPath(backendDir) {
  if (process.env.PYTHON) {
    return process.env.PYTHON;
  }
  const venvPython = process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }
  return "python3";
}

function backendDirPath() {
  return path.resolve(__dirname, "../../backend");
}

function backendHealthCheck(url) {
  return new Promise((resolve) => {
    const request = http.get(`${url.origin}/health`, { timeout: 1200 }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 500);
    });
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

async function startBackend() {
  if (process.env.RECALL_START_BACKEND === "false") {
    return;
  }
  if (backendProcess) {
    return;
  }

  const backendUrl = localBackendUrl();
  if (!backendUrl) {
    return;
  }
  if (await backendHealthCheck(backendUrl)) {
    return;
  }

  const backendDir = backendDirPath();
  const python = backendPythonPath(backendDir);
  backendProcess = spawn(
    python,
    ["-m", "uvicorn", "main:app", "--host", backendUrl.hostname, "--port", backendUrl.port || "8000"],
    {
      cwd: backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: "inherit",
    }
  );

  backendProcess.on("error", (error) => {
    console.error("[Re: Call] Failed to start backend:", error);
    backendProcess = null;
  });

  backendProcess.on("exit", (code, signal) => {
    console.error(`[Re: Call] Backend exited with code=${code} signal=${signal}`);
    backendProcess = null;
    if (!isQuitting && code !== 0) {
      setTimeout(() => {
        startBackend().catch((error) => console.error("[Re: Call] Backend restart failed:", error));
      }, 1500);
    }
  });
}

function startCeleryWorker() {
  if (process.env.RECALL_START_WORKER === "false") {
    return;
  }
  if (workerProcess) {
    return;
  }
  if (!localBackendUrl()) {
    return;
  }

  const backendDir = backendDirPath();
  const python = backendPythonPath(backendDir);
  workerProcess = spawn(
    python,
    [
      "-m",
      "celery",
      "-A",
      "tasks.celery_app:celery_app",
      "worker",
      "--loglevel=info",
      "-Q",
      "transcription,analysis,live_insights",
      "--concurrency=2",
      "-n",
      "recall-electron@%h",
    ],
    {
      cwd: backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" },
      stdio: "inherit",
    }
  );

  workerProcess.on("error", (error) => {
    console.error("[Re: Call] Failed to start Celery worker:", error);
    workerProcess = null;
  });

  workerProcess.on("exit", (code, signal) => {
    console.error(`[Re: Call] Celery worker exited with code=${code} signal=${signal}`);
    workerProcess = null;
    if (!isQuitting && code !== 0) {
      setTimeout(() => {
        startCeleryWorker();
      }, 2500);
    }
  });
}

function loadAppWindow(win, view) {
  if (app.isPackaged) {
    const options = view ? { query: { view } } : undefined;
    win.loadFile(path.join(__dirname, "../dist/index.html"), options);
    return;
  }

  const devUrl = new URL(process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173");
  if (view) {
    devUrl.searchParams.set("view", view);
  }
  win.loadURL(devUrl.toString());
}

function createMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    mainWindow.focus();
    return mainWindow;
  }

  const workArea = screen.getPrimaryDisplay().workArea;
  const windowWidth = Math.min(1440, workArea.width);
  const windowHeight = Math.min(920, workArea.height);

  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    minWidth: Math.min(1080, workArea.width),
    minHeight: Math.min(720, workArea.height),
    x: workArea.x + Math.max(0, Math.round((workArea.width - windowWidth) / 2)),
    y: workArea.y + Math.max(0, Math.round((workArea.height - windowHeight) / 2)),
    title: "Re: Call",
    backgroundColor: "#08090a",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    mainWindow.hide();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  loadAppWindow(mainWindow);
  return mainWindow;
}

function getOverlayWindowBounds({ expanded = false, mode = "standard" } = {}) {
  const workArea = screen.getPrimaryDisplay().workArea;
  const isRecording = expanded && mode === "recording";
  const width = isRecording
    ? Math.max(900, Math.min(1180, workArea.width - 48))
    : Math.max(560, Math.min(900, workArea.width - 48));
  const height = isRecording
    ? Math.max(620, Math.min(760, workArea.height - 72))
    : expanded
      ? Math.max(360, Math.min(560, workArea.height - 96))
      : 118;
  const x = workArea.x + Math.max(0, Math.round((workArea.width - width) / 2));
  const desiredY = workArea.y + 72;
  const y = Math.min(desiredY, workArea.y + Math.max(0, workArea.height - height - 24));
  return { x, y, width, height };
}

function resizeOverlayWindow({ expanded = false, mode = "standard" } = {}) {
  if (!overlayWindow || overlayWindow.isDestroyed()) {
    return;
  }
  overlayWindow.setBounds(getOverlayWindowBounds({ expanded, mode }), true);
}

function createOverlayWindow() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.show();
    overlayWindow.focus();
    return overlayWindow;
  }

  const workArea = screen.getPrimaryDisplay().workArea;
  const overlayBounds = getOverlayWindowBounds();
  overlayWindow = new BrowserWindow({
    width: overlayBounds.width,
    height: overlayBounds.height,
    minWidth: Math.min(560, overlayBounds.width),
    minHeight: 96,
    maxWidth: Math.max(560, Math.min(1040, workArea.width)),
    maxHeight: Math.max(360, Math.min(620, workArea.height)),
    x: overlayBounds.x,
    y: overlayBounds.y,
    title: "Re: Call Overlay",
    frame: false,
    resizable: true,
    transparent: true,
    hasShadow: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  overlayWindow.setAlwaysOnTop(true, "floating");
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  overlayWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  overlayWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    overlayWindow.hide();
  });

  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });

  loadAppWindow(overlayWindow, "overlay");
  return overlayWindow;
}

function showMainWindow() {
  const win = createMainWindow();
  win.show();
  win.focus();
}

function showOverlayWindow() {
  const win = createOverlayWindow();
  win.show();
  win.focus();
}

function showAllWindows() {
  showMainWindow();
  showOverlayWindow();
}

function configureRecoveryMenus() {
  const recoveryItems = [
    { label: "Show Dashboard", accelerator: "CommandOrControl+Shift+D", click: showMainWindow },
    { label: "Show Overlay", accelerator: "CommandOrControl+Shift+O", click: showOverlayWindow },
    { label: "Show Both", accelerator: "CommandOrControl+Shift+R", click: showAllWindows },
  ];
  const template = [
    ...(process.platform === "darwin"
      ? [{
          label: app.name,
          submenu: [
            { role: "about" },
            { type: "separator" },
            ...recoveryItems,
            { type: "separator" },
            { role: "hide" },
            { role: "hideOthers" },
            { role: "unhide" },
            { type: "separator" },
            { role: "quit" },
          ],
        }]
      : []),
    {
      label: "Window",
      submenu: [
        ...recoveryItems,
        { type: "separator" },
        { role: "minimize" },
        { role: "close" },
      ],
    },
    { role: "viewMenu" },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));

  if (process.platform === "darwin" && app.dock) {
    app.dock.setMenu(Menu.buildFromTemplate(recoveryItems));
  }
}

function configurePermissions() {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(["media", "microphone"].includes(permission));
  });

  session.defaultSession.setPermissionCheckHandler((_webContents, permission) => {
    return ["media", "microphone"].includes(permission);
  });
}

function systemAudioFlagEnabled() {
  const rawValue = String(process.env.RECALL_ENABLE_SYSTEM_AUDIO || "").trim().toLowerCase();
  if (["false", "0", "off", "no"].includes(rawValue)) {
    return false;
  }
  if (["true", "1", "on", "yes"].includes(rawValue)) {
    return true;
  }
  return process.platform === "darwin";
}

function systemAudioHelperPath() {
  if (process.platform !== "darwin") {
    return null;
  }

  const candidates = [
    process.env.RECALL_SYSTEM_AUDIO_HELPER_BIN,
    app.isPackaged ? path.join(process.resourcesPath, "native", "recall-macos-capture") : null,
    path.resolve(__dirname, "../../native/macos-screen-capture/.build/debug/recall-macos-capture"),
    path.resolve(__dirname, "../../native/macos-screen-capture/.build/release/recall-macos-capture"),
  ].filter(Boolean);

  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function systemAudioStatus() {
  const enabled = systemAudioFlagEnabled();
  const helperPath = systemAudioHelperPath();
  return {
    enabled,
    available: enabled && Boolean(helperPath),
    platform: process.platform,
    detail: enabled
      ? helperPath
        ? "System audio helper is available."
        : "System audio flag is on, but the helper binary was not found."
      : "System audio capture is disabled. Mic-only mode is active.",
  };
}

function startSystemAudioCapture(payload = {}) {
  const status = systemAudioStatus();
  if (!status.enabled) {
    return { ...status, started: false };
  }
  if (process.platform !== "darwin") {
    return { ...status, available: false, started: false, detail: "System audio helper is only available on macOS." };
  }
  if (!status.available) {
    return { ...status, started: false };
  }
  if (systemAudioProcess && !systemAudioProcess.killed) {
    return { ...status, started: true, detail: "System audio helper is already running.", diagnostics: systemAudioDiagnostics };
  }

  const sessionId = payload.sessionId;
  if (!sessionId) {
    return { ...status, started: false, detail: "A Re: Call session ID is required for system audio capture." };
  }

  return new Promise((resolve) => {
    let resolved = false;
    let stdoutBuffer = "";
    const helperPath = systemAudioHelperPath();
    systemAudioDiagnostics = {
      system_audio_enabled: true,
      system_audio_started: false,
      system_audio_buffers: 0,
      system_audio_uploaded_chunks: 0,
      system_audio_uploaded_bytes: 0,
      system_audio_skipped_chunks: 0,
      system_audio_errors: [],
    };

    const resolveOnce = (result) => {
      if (resolved) {
        return;
      }
      resolved = true;
      resolve(result);
    };

    const helperArgs = [
      "--api-base",
      payload.apiBaseUrl || API_BASE_URL,
      "--session-id",
      String(sessionId),
      "--chunk-seconds",
      String(payload.chunkSeconds || 6),
    ];
    const apiToken = String(payload.apiToken || API_TOKEN || "").trim();
    if (apiToken) {
      helperArgs.push("--api-token", apiToken);
    }
    if (payload.recordingStartedAtMs) {
      helperArgs.push("--recording-started-at-ms", String(payload.recordingStartedAtMs));
    }

    systemAudioProcess = spawn(
      helperPath,
      helperArgs,
      { stdio: ["pipe", "pipe", "pipe"] }
    );

    const startupTimer = setTimeout(() => {
      systemAudioDiagnostics.system_audio_started = true;
      resolveOnce({
        ...status,
        started: true,
        detail: "System audio helper is starting.",
        diagnostics: systemAudioDiagnostics,
      });
    }, 5000);

    systemAudioProcess.stdout.on("data", (data) => {
      stdoutBuffer += String(data);
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }
        console.log(`[recall-system-audio] ${line.trim()}`);
        try {
          const event = JSON.parse(line);
          if (event.type === "started") {
            clearTimeout(startupTimer);
            systemAudioDiagnostics.system_audio_started = true;
            resolveOnce({
              ...status,
              started: true,
              detail: "System audio helper started.",
              diagnostics: systemAudioDiagnostics,
            });
          } else if (event.type === "audio_buffer") {
            systemAudioDiagnostics.system_audio_buffers = Number(event.buffers || systemAudioDiagnostics.system_audio_buffers);
          } else if (event.type === "chunk_uploaded") {
            systemAudioDiagnostics.system_audio_uploaded_chunks += 1;
            systemAudioDiagnostics.system_audio_uploaded_bytes += Number(event.bytes || 0);
            systemAudioDiagnostics.system_audio_last_chunk = {
              chunk_index: event.chunk_index,
              start_offset_ms: event.start_offset_ms,
              end_offset_ms: event.end_offset_ms,
              rms: event.rms,
              peak: event.peak,
            };
          } else if (event.type === "chunk_skipped") {
            systemAudioDiagnostics.system_audio_skipped_chunks += 1;
            systemAudioDiagnostics.system_audio_last_skipped_chunk = {
              chunk_index: event.chunk_index,
              reason: event.reason,
              start_offset_ms: event.start_offset_ms,
              end_offset_ms: event.end_offset_ms,
              rms: event.rms,
              peak: event.peak,
            };
          } else if (event.type === "error" || event.type === "capture_error" || event.type === "upload_error" || event.type === "writer_error") {
            const message = event.message || "System audio helper error.";
            systemAudioDiagnostics.system_audio_errors.push(message);
            clearTimeout(startupTimer);
            resolveOnce({
              ...status,
              started: false,
              detail: message,
              diagnostics: systemAudioDiagnostics,
            });
          }
        } catch {
          // Keep logging non-JSON helper output.
        }
      }
    });

    systemAudioProcess.stderr.on("data", (data) => {
      console.error(`[recall-system-audio] ${String(data).trim()}`);
    });

    systemAudioProcess.on("exit", (code) => {
      clearTimeout(startupTimer);
      systemAudioProcess = null;
      if (!resolved) {
        resolveOnce({
          ...status,
          started: false,
          detail: `System audio helper exited${typeof code === "number" ? ` with code ${code}` : ""}.`,
          diagnostics: systemAudioDiagnostics,
        });
      }
    });
  });
}

function stopSystemAudioCapture() {
  return new Promise((resolve) => {
    const captureProcess = systemAudioProcess;
    if (!captureProcess || captureProcess.killed) {
      systemAudioProcess = null;
      resolve({ stopped: true, diagnostics: systemAudioDiagnostics });
      return;
    }

    const timeout = setTimeout(() => {
      if (!captureProcess.killed) {
        captureProcess.kill("SIGTERM");
      }
      systemAudioProcess = null;
      resolve({ stopped: true, forced: true, diagnostics: systemAudioDiagnostics });
    }, 5000);

    captureProcess.once("exit", () => {
      clearTimeout(timeout);
      systemAudioProcess = null;
      resolve({ stopped: true, diagnostics: systemAudioDiagnostics });
    });

    try {
      captureProcess.stdin.write("stop\n");
      captureProcess.stdin.end();
    } catch {
      captureProcess.kill("SIGTERM");
    }
  });
}

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (app.isReady()) {
      showAllWindows();
    }
  });

  app.whenReady().then(() => {
    validateRuntimeConfig();
    configureRecoveryMenus();
    configurePermissions();
    ipcMain.handle("recall:api-base", () => API_BASE_URL);
    ipcMain.handle("recall:api-token", () => API_TOKEN);
    ipcMain.handle("recall:system-audio-status", () => systemAudioStatus());
    ipcMain.handle("recall:start-system-audio", (_event, payload) => startSystemAudioCapture(payload));
    ipcMain.handle("recall:stop-system-audio", () => stopSystemAudioCapture());
    ipcMain.handle("recall:show-main-window", () => showMainWindow());
    ipcMain.handle("recall:show-overlay-window", () => showOverlayWindow());
    ipcMain.handle("recall:minimize-overlay-window", () => {
      if (overlayWindow && !overlayWindow.isDestroyed()) {
        overlayWindow.minimize();
      }
    });
    ipcMain.handle("recall:hide-overlay-window", () => {
      if (overlayWindow && !overlayWindow.isDestroyed()) {
        overlayWindow.hide();
      }
    });
    ipcMain.handle("recall:resize-overlay-window", (_event, payload = {}) => {
      resizeOverlayWindow({ expanded: Boolean(payload.expanded), mode: payload.mode || "standard" });
    });
    startBackend();
    startCeleryWorker();
    createMainWindow();
    createOverlayWindow();

    app.on("activate", () => {
      showAllWindows();
    });
  }).catch((error) => {
    console.error(error);
    app.quit();
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  if (systemAudioProcess && !systemAudioProcess.killed) {
    systemAudioProcess.kill("SIGTERM");
    systemAudioProcess = null;
  }
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  if (workerProcess) {
    workerProcess.kill();
    workerProcess = null;
  }
});
