import { useEffect } from "react";

export function useWebSocket(apiBaseUrl, meetingId, onMessage) {
  useEffect(() => {
    if (!apiBaseUrl || !meetingId) {
      return undefined;
    }

    const wsUrl = apiBaseUrl.replace(/^http/, "ws") + `/ws/meetings/${meetingId}`;
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        onMessage({ type: "message", data: event.data });
      }
    };

    return () => socket.close();
  }, [apiBaseUrl, meetingId, onMessage]);
}
