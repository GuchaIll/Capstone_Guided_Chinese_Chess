import { useEffect, useRef, useState, useCallback } from 'react';

interface UseWebSocketOptions {
  url: string;
  onMessage?: (message: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

export function useWebSocket({
  url,
  onMessage,
  onOpen,
  onClose,
  onError,
  reconnectInterval = 3000,
  maxReconnectAttempts = 10,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const intentionalCloseRef = useRef(false);
  const [isConnected, setIsConnected] = useState(false);

  // Store callbacks in refs to avoid triggering reconnection on callback changes
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);

  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
  useEffect(() => { onOpenRef.current = onOpen; }, [onOpen]);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current !== null) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    // Guard: don't connect if unmounted or intentionally closed
    if (!mountedRef.current || intentionalCloseRef.current) {
      return;
    }

    // Close any existing connection cleanly before creating a new one
    if (wsRef.current) {
      const existing = wsRef.current;
      wsRef.current = null;
      // Only close if not already closed
      if (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING) {
        // Detach handlers to prevent the close from triggering reconnect
        existing.onopen = null;
        existing.onmessage = null;
        existing.onclose = null;
        existing.onerror = null;
        existing.close();
      }
    }

    console.log('[WS Hook] Connecting to', url);

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        if (!mountedRef.current) {
          ws.close();
          return;
        }
        console.log('[WS Hook] Connected');
        wsRef.current = ws;
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        onOpenRef.current?.();
      };

      ws.onmessage = (event) => {
        if (mountedRef.current) {
          onMessageRef.current?.(event.data);
        }
      };

      ws.onclose = (event) => {
        console.log('[WS Hook] Disconnected (code:', event.code, 'reason:', event.reason || 'none', ')');

        // Only update state if this is still our active connection
        if (wsRef.current === ws) {
          wsRef.current = null;
        }

        if (!mountedRef.current) return;

        setIsConnected(false);
        onCloseRef.current?.();

        // Only reconnect if not intentionally closed and still mounted
        if (!intentionalCloseRef.current && mountedRef.current) {
          if (reconnectAttemptsRef.current < maxReconnectAttempts) {
            reconnectAttemptsRef.current++;
            const delay = Math.min(reconnectInterval * reconnectAttemptsRef.current, 10000);
            console.log(`[WS Hook] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);
            clearReconnectTimer();
            reconnectTimeoutRef.current = window.setTimeout(() => {
              if (mountedRef.current && !intentionalCloseRef.current) {
                connect();
              }
            }, delay);
          } else {
            console.log('[WS Hook] Max reconnect attempts reached');
          }
        }
      };

      ws.onerror = (error) => {
        console.error('[WS Hook] Error:', error);
        if (mountedRef.current) {
          onErrorRef.current?.(error);
        }
        // Don't set isConnected here — onclose will fire after onerror
      };

      // Store ref immediately so we can track it, but isConnected is only set on onopen
      wsRef.current = ws;
    } catch (error) {
      console.error('[WS Hook] Failed to create WebSocket:', error);
    }
  }, [url, reconnectInterval, maxReconnectAttempts, clearReconnectTimer]);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearReconnectTimer();
    reconnectAttemptsRef.current = 0;

    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null;
      // Detach handlers before closing to prevent reconnect
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000, 'Client disconnect');
      }
    }
    setIsConnected(false);
  }, [clearReconnectTimer]);

  const sendMessage = useCallback((message: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(message);
    } else {
      console.warn('[WS Hook] Not connected (readyState:', wsRef.current?.readyState ?? 'null', '). Message not sent:', message);
    }
  }, []);

  const reconnect = useCallback(() => {
    intentionalCloseRef.current = false;
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);

  // Main connection lifecycle
  useEffect(() => {
    mountedRef.current = true;
    intentionalCloseRef.current = false;
    connect();

    return () => {
      mountedRef.current = false;
      clearReconnectTimer();
      // Close without triggering reconnect
      if (wsRef.current) {
        const ws = wsRef.current;
        wsRef.current = null;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close(1000, 'Component unmount');
        }
      }
    };
  }, [url, connect, clearReconnectTimer]);

  return {
    sendMessage,
    isConnected,
    reconnect,
    disconnect,
  };
}
