const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const input = document.getElementById("apiBaseUrl");
const tokenInput = document.getElementById("apiToken");
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
  const stored = await chrome.storage.local.get({ apiBaseUrl: DEFAULT_API_BASE_URL, apiToken: "" });
  input.value = normalizeUrl(stored.apiBaseUrl);
  tokenInput.value = String(stored.apiToken || "");
}

async function save() {
  const apiBaseUrl = normalizeUrl(input.value);
  const apiToken = String(tokenInput.value || "").trim();
  await chrome.storage.local.set({ apiBaseUrl, apiToken });
  input.value = apiBaseUrl;
  tokenInput.value = apiToken;
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
