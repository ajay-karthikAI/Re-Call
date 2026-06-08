const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("recall", {
  getApiBaseUrl: () => ipcRenderer.invoke("recall:api-base"),
  showMainWindow: () => ipcRenderer.invoke("recall:show-main-window"),
  showOverlayWindow: () => ipcRenderer.invoke("recall:show-overlay-window"),
  minimizeOverlayWindow: () => ipcRenderer.invoke("recall:minimize-overlay-window"),
  hideOverlayWindow: () => ipcRenderer.invoke("recall:hide-overlay-window"),
});
