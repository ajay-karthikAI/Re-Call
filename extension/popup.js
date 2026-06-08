const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const input = document.getElementById("apiBaseUrl");
const saveButton = document.getElementById("saveButton");
const testButton = document.getElementById("testButton");
const statusText = document.getElementById("status");

function normalizeUrl(value) {
  return String(value || DEFAULT_API_BASE_URL).trim().replace(/\/+$/, "") || DEFAULT_API_BASE_URL;
}

function setStatus(message, mode = "") {
  statusText.textContent = message;
  statusText.className = `status ${mode}`.trim();
}

async function load() {
  const stored = await chrome.storage.local.get({ apiBaseUrl: DEFAULT_API_BASE_URL });
  input.value = normalizeUrl(stored.apiBaseUrl);
}

async function save() {
  const apiBaseUrl = normalizeUrl(input.value);
  await chrome.storage.local.set({ apiBaseUrl });
  input.value = apiBaseUrl;
  setStatus("Saved.", "ok");
}

async function test() {
  const apiBaseUrl = normalizeUrl(input.value);
  setStatus("Checking backend...");
  try {
    const response = await fetch(`${apiBaseUrl}/health`);
    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}.`);
    }
    setStatus("Backend is reachable.", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

saveButton.addEventListener("click", save);
testButton.addEventListener("click", test);
load();
