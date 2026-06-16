const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("recall", {
  getApiBaseUrl: () => ipcRenderer.invoke("recall:api-base"),
  systemAudioStatus: () => ipcRenderer.invoke("recall:system-audio-status"),
  startSystemAudio: (payload) => ipcRenderer.invoke("recall:start-system-audio", payload),
  stopSystemAudio: () => ipcRenderer.invoke("recall:stop-system-audio"),
  showMainWindow: () => ipcRenderer.invoke("recall:show-main-window"),
  showOverlayWindow: () => ipcRenderer.invoke("recall:show-overlay-window"),
  minimizeOverlayWindow: () => ipcRenderer.invoke("recall:minimize-overlay-window"),
  hideOverlayWindow: () => ipcRenderer.invoke("recall:hide-overlay-window"),
  resizeOverlayWindow: (payload) => ipcRenderer.invoke("recall:resize-overlay-window", payload),
});
