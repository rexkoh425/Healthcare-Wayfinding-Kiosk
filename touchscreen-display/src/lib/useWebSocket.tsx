"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Sendable = Record<string, unknown>;

interface UseWebSocketOpts {
  url?: string;
  autoConnect?: boolean; // start connecting on mount
  reconnect?: boolean; // attempt reconnect on close
  maxReconnectAttempts?: number;
  reconnectBaseMs?: number; // base ms for exponential backoff
}

function defaultUrl(): string {
  if (typeof window === "undefined") return ""; // safe SSR no-op
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return explicit;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  // hostname (no port) matches your original behavior; change if needed
  return `${proto}://${window.location.hostname}:8080`;
}

export default function useWebSocket(opts?: UseWebSocketOpts) {
  const {
    url: explicitUrl,
    autoConnect = true,
    reconnect = true,
    maxReconnectAttempts = 6,
    reconnectBaseMs = 500,
  } = opts ?? {};

  const url = explicitUrl ?? defaultUrl();
  const wsRef = useRef<WebSocket | null>(null);
  const queueRef = useRef<Sendable[]>([]);
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);

  const [connected, setConnected] = useState(false);

  const flushQueue = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    while (queueRef.current.length > 0) {
      try {
        ws.send(JSON.stringify(queueRef.current.shift()));
      } catch (err) {
        console.warn("WS send while flushing queue failed, re-queueing", err);
        // put it back and stop trying
        // (this is defensive — very unlikely)
        // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
        queueRef.current.unshift(queueRef.current.shift()!);
        break;
      }
    }
  }, []);

  const cleanupSocket = useCallback(() => {
    try {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.onopen = null;
          wsRef.current.onmessage = null;
          wsRef.current.onclose = null;
          wsRef.current.onerror = null;
          wsRef.current.close();
        } catch (e) {
          /* ignore */
        }
        wsRef.current = null;
      }
    } finally {
      setConnected(false);
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!reconnect) return;
    if (reconnectCountRef.current >= maxReconnectAttempts) return;

    const attempt = reconnectCountRef.current + 1;
    const delay = Math.min(
      reconnectBaseMs * 2 ** (attempt - 1),
      30_000 // cap to 30s
    );

    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectCountRef.current = attempt;
      connect();
    }, delay);
  }, [reconnect, maxReconnectAttempts, reconnectBaseMs]);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    if (!url) return;
    if (wsRef.current) {
      // already created or opening
      const state = wsRef.current.readyState;
      if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;
    }

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectCountRef.current = 0;
        setConnected(true);
        flushQueue();
        // optionally register role like your original version
        try {
          ws.send(JSON.stringify({ type: "register", role: "touchscreen" }));
        } catch (e) {
          // ignore
        }
      };

      ws.onmessage = (event) => {
        // keep it simple: try parse JSON and log (or extend to accept callbacks)
        try {
          const data = JSON.parse(event.data);
          // You can extend this hook to accept onMessage handlers
          console.debug("WS message:", data);
        } catch {
          console.debug("WS non-json:", event.data);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // schedule reconnect (if allowed)
        scheduleReconnect();
      };

      ws.onerror = (ev) => {
        // errors will eventually trigger onclose — log for debugging
        console.warn("WS error", ev);
      };
    } catch (err) {
      console.warn("Failed to create WebSocket", err);
      scheduleReconnect();
    }
  }, [url, flushQueue, scheduleReconnect]);

  // Optionally auto-connect on mount (but still safe for SSR because of the typeof window guard)
  useEffect(() => {
    if (!autoConnect) return;
    // ensure window is available
    if (typeof window === "undefined") return;
    connect();
    return () => {
      cleanupSocket();
    };
    // connect and cleanup are stable (wrapped in useCallback)
  }, [autoConnect, connect, cleanupSocket]);

  const send = useCallback(
    (obj: Sendable) => {
      if (typeof window === "undefined") return;
      try {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(obj));
          return;
        }
        // if not open: queue and ensure a connection attempt
        queueRef.current.push(obj);
        connect();
      } catch (err) {
        console.warn("WebSocket send failed, queuing", err);
        queueRef.current.push(obj);
        connect();
      }
    },
    [connect]
  );

  const close = useCallback(() => {
    // prevents further reconnects
    cleanupSocket();
    reconnectCountRef.current = Number.MAX_SAFE_INTEGER;
  }, [cleanupSocket]);

  return {
    send,
    connect,
    close,
    connected,
  };
}
