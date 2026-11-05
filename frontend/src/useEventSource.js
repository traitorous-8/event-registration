import { useEffect, useState, useRef } from 'react';

/**
 * Reusable hook for Server-Sent Events.
 * Automatically handles reconnects (built into EventSource),
 * tracks connection status ('connected' | 'connecting' | 'error'),
 * dispatches custom events to handlers, and cleans up on unmount.
 *
 * @param {string|null} url SSE URL to connect to. If null, connection is paused.
 * @param {Record<string, (data: any) => void>} handlers Map of event name to callback function.
 */
export function useEventSource(url, handlers = {}) {
  const [status, setStatus] = useState('connecting');
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!url) {
      setStatus('error');
      return;
    }

    let isUnmounted = false;
    let es = null;

    try {
      es = new EventSource(url);
    } catch (err) {
      setStatus('error');
      return;
    }

    es.onopen = () => {
      if (!isUnmounted) {
        setStatus('connected');
      }
    };

    es.onerror = () => {
      if (!isUnmounted) {
        setStatus('error');
      }
    };

    // Attach listeners for registered event types
    const eventTypes = Object.keys(handlersRef.current);
    const listeners = [];

    eventTypes.forEach((type) => {
      const listener = (event) => {
        if (isUnmounted) return;
        try {
          const parsed = JSON.parse(event.data);
          if (handlersRef.current[type]) {
            handlersRef.current[type](parsed);
          }
        } catch (e) {
          if (handlersRef.current[type]) {
            handlersRef.current[type](event.data);
          }
        }
      };
      es.addEventListener(type, listener);
      listeners.push({ type, listener });
    });

    return () => {
      isUnmounted = true;
      listeners.forEach(({ type, listener }) => {
        es.removeEventListener(type, listener);
      });
      es.close();
    };
  }, [url]);

  return { status };
}
