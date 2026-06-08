const { app, BrowserWindow, ipcMain, screen, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

const API_BASE_URL = process.env.RECALL_API_BASE_URL || "http://127.0.0.1:8000";
let backendProcess = null;
let mainWindow = null;
let overlayWindow = null;

function startBackend() {
  if (process.env.RECALL_START_BACKEND === "false") {
    return;
  }

  const backendDir = path.resolve(__dirname, "../../backend");
  const python = process.env.PYTHON || "python3";
  backendProcess = spawn(
    python,
    ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: "inherit",
    }
  );
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

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
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

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  loadAppWindow(mainWindow);
  return mainWindow;
}

function createOverlayWindow() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.show();
    overlayWindow.focus();
    return overlayWindow;
  }

  const workArea = screen.getPrimaryDisplay().workArea;
  overlayWindow = new BrowserWindow({
    width: 360,
    height: 320,
    minWidth: 320,
    minHeight: 220,
    maxWidth: 420,
    maxHeight: 520,
    x: workArea.x + workArea.width - 388,
    y: workArea.y + 72,
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

function configurePermissions() {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(["media", "microphone"].includes(permission));
  });

  session.defaultSession.setPermissionCheckHandler((_webContents, permission) => {
    return ["media", "microphone"].includes(permission);
  });
}

app.whenReady().then(() => {
  configurePermissions();
  ipcMain.handle("recall:api-base", () => API_BASE_URL);
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
  startBackend();
  createMainWindow();
  createOverlayWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
      createOverlayWindow();
    } else {
      showMainWindow();
      showOverlayWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
