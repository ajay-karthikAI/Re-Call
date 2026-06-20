const VITE_API_TOKEN = (import.meta.env.VITE_RECALL_API_TOKEN || "").trim();

export function getInitialApiToken() {
  return VITE_API_TOKEN;
}

export function normalizeApiToken(value) {
  return String(value || "").trim();
}

export function withApiAuth(options = {}, apiToken = "") {
  const token = normalizeApiToken(apiToken);
  if (!token) {
    return options;
  }

  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  return { ...options, headers };
}

export function apiFetch(url, options = {}, apiToken = "") {
  return fetch(url, withApiAuth(options, apiToken));
}

function anchorDownload(url, filename) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "";
  link.rel = "noopener noreferrer";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function shouldUseAuthenticatedDownload(url, apiBaseUrl, apiToken) {
  if (!normalizeApiToken(apiToken)) {
    return false;
  }

  try {
    const targetUrl = new URL(url, window.location.href);
    return targetUrl.pathname.startsWith("/api/files/");
  } catch {
    return false;
  }
}

export async function downloadFile(url, filename, apiToken = "", apiBaseUrl = "") {
  if (!shouldUseAuthenticatedDownload(url, apiBaseUrl, apiToken)) {
    anchorDownload(url, filename);
    return;
  }

  const response = await apiFetch(url, {}, apiToken);
  if (!response.ok) {
    throw new Error(`Download failed (${response.status})`);
  }

  const objectUrl = URL.createObjectURL(await response.blob());
  anchorDownload(objectUrl, filename);
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
}
