
"use client";

import { useEffect, useRef } from "react";

type Sendable = Record<string, any>;

export default function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const url =
    (process.env.NEXT_PUBLIC_WS_URL as string) ?? "ws://localhost:8080";

  useEffect(() => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WS open -> registering touchscreen");
      ws.send(JSON.stringify({ type: "register", role: "touchscreen" }));
    };

    ws.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        console.log("WS message:", d);
      } catch (err) {
        console.warn("WS non-json:", ev.data);
      }
    };

    ws.onclose = () => {
      console.warn("WS closed - you may want to reconnect");
      // TODO: Simple no-reconnect logic here; can be extended to auto-reconnect
    };

    ws.onerror = (e) => {
      console.warn("WS error", e);
    };

    return () => {
      try {
        ws.close();
      } catch (_) {}
    };
  }, [url]);

  function send(obj: Sendable) {
    const ws = wsRef.current;
    if (!ws) {
      console.warn("WS not available");
      return;
    }
    if (ws.readyState !== WebSocket.OPEN) {
      console.warn("WS not open; readyState=", ws.readyState);
      return;
    }
    ws.send(JSON.stringify(obj));
  }

  return { send };
}
