import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import EventPage from '../pages/EventPage';
import * as apiModule from '../api';

class MockEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    MockEventSource.instance = this;
  }
  addEventListener(type, cb) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(cb);
  }
  removeEventListener() {}
  close() {}
  emit(type, data) {
    if (this.listeners[type]) {
      this.listeners[type].forEach((cb) => cb({ data: JSON.stringify(data) }));
    }
  }
}

describe('EventPage', () => {
  const originalES = global.EventSource;

  beforeEach(() => {
    global.EventSource = MockEventSource;
    localStorage.clear();

    vi.spyOn(apiModule, 'apiFetch').mockImplementation(async (url, opts) => {
      if (url === '/api/events/1' && !opts?.method) {
        return {
          ok: true,
          status: 200,
          data: {
            id: 1,
            title: 'Frontend Conf',
            description: 'Про фронтенд',
            starts_at: '2026-12-10T18:00:00Z',
            capacity: 2,
            confirmed_count: 1,
            waitlist_count: 0,
          },
        };
      }
      if (url === '/api/events/1/registrations' && opts?.method === 'POST') {
        return {
          ok: true,
          status: 200,
          data: {
            status: 'confirmed',
            ticket_code: 'TICK123',
          },
        };
      }
      return { ok: true, status: 200, data: {} };
    });
  });

  afterEach(() => {
    global.EventSource = originalES;
    vi.restoreAllMocks();
  });

  it('registers user, shows confirmed status & ticket link, and updates live counters', async () => {
    render(
      <MemoryRouter initialEntries={['/events/1']}>
        <Routes>
          <Route path="/events/:id" element={<EventPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Frontend Conf')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();

    // Register email
    fireEvent.change(screen.getByPlaceholderText('name@example.com'), {
      target: { value: 'user@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Зарегистрироваться/i }));

    // Registration result appears
    expect(await screen.findByText(/Регистрация подтверждена!/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Перейти к билету \(TICK123\)/i })).toBeInTheDocument();

    // SSE emits new counts
    act(() => {
      MockEventSource.instance.emit('counts', { confirmed: 2, waitlist: 1 });
    });

    expect(screen.getByText('2 / 2')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });
});
