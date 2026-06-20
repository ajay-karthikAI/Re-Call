import { useEffect } from "react";
import { normalizeApiToken } from "../apiAuth.js";

function websocketUrl(apiBaseUrl, meetingId, apiToken) {
  const url = new URL(`/ws/meetings/${meetingId}`, apiBaseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const token = normalizeApiToken(apiToken);
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}

export function useWebSocket(apiBaseUrl, meetingId, onMessage, apiToken = "") {
  useEffect(() => {
    if (!apiBaseUrl || !meetingId) {
      return undefined;
    }

    const wsUrl = websocketUrl(apiBaseUrl, meetingId, apiToken);
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        onMessage({ type: "message", data: event.data });
      }
    };

    return () => socket.close();
  }, [apiBaseUrl, apiToken, meetingId, onMessage]);
}
