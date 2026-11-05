import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useEventSource } from '../useEventSource';

class MockEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.onopen = null;
    this.onerror = null;
    this.close = vi.fn();
    MockEventSource.instances.push(this);
  }

  addEventListener(type, callback) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(callback);
  }

  removeEventListener(type, callback) {
    if (this.listeners[type]) {
      this.listeners[type] = this.listeners[type].filter((cb) => cb !== callback);
    }
  }

  emit(type, data) {
    if (this.listeners[type]) {
      this.listeners[type].forEach((cb) => cb({ data: JSON.stringify(data) }));
    }
  }
}

MockEventSource.instances = [];

describe('useEventSource hook', () => {
  const originalEventSource = global.EventSource;

  beforeEach(() => {
    MockEventSource.instances = [];
    global.EventSource = MockEventSource;
  });

  afterEach(() => {
    global.EventSource = originalEventSource;
  });

  it('connects, updates status to connected onopen, and receives snapshots', () => {
    const countsHandler = vi.fn();
    const { result } = renderHook(() =>
      useEventSource('/api/events/1/stream', { counts: countsHandler })
    );

    expect(result.current.status).toBe('connecting');
    const es = MockEventSource.instances[0];
    expect(es).toBeDefined();

    act(() => {
      es.onopen();
    });
    expect(result.current.status).toBe('connected');

    act(() => {
      es.emit('counts', { confirmed: 2, waitlist: 1 });
    });
    expect(countsHandler).toHaveBeenCalledWith({ confirmed: 2, waitlist: 1 });
  });

  it('updates status to error on error event', () => {
    const { result } = renderHook(() =>
      useEventSource('/api/events/1/stream', {})
    );

    const es = MockEventSource.instances[0];
    act(() => {
      es.onerror();
    });
    expect(result.current.status).toBe('error');
  });

  it('cleans up and closes EventSource on unmount', () => {
    const { unmount } = renderHook(() =>
      useEventSource('/api/events/1/stream', {})
    );

    const es = MockEventSource.instances[0];
    unmount();
    expect(es.close).toHaveBeenCalledTimes(1);
  });
});
