"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

type Sendable = Record<string, unknown>;

export default function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const url = useMemo(() => {
    const explicit = process.env.NEXT_PUBLIC_WS_URL as string | undefined;
    if (explicit) {
      return explicit;
    }
    if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      return `${proto}://${window.location.hostname}:8080`;
    }
    return "ws://localhost:8080";
  }, []);

  useEffect(() => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WS open -> registering touchscreen");
      ws.send(JSON.stringify({ type: "register", role: "touchscreen" }));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log("WS message:", data);
      } catch (err) {
        console.warn("WS non-json:", event.data);
      }
    };

    ws.onclose = () => {
      console.warn("WS closed - you may want to reconnect");
    };

    ws.onerror = (error) => {
      console.warn("WS error", error);
    };

    return () => {
      try {
        ws.close();
      } catch (error) {
        console.warn("WS close error", error);
      }
    };
  }, [url]);

  const send = useCallback((obj: Sendable) => {
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
  }, []);

  return { send };
}
