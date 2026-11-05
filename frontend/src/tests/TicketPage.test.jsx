import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import TicketPage from '../pages/TicketPage';
import * as apiModule from '../api';

class MockEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
  }
  addEventListener(type, cb) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(cb);
  }
  removeEventListener() {}
  close() {}
}

describe('TicketPage', () => {
  const originalES = global.EventSource;

  beforeEach(() => {
    global.EventSource = MockEventSource;
    window.confirm = vi.fn().mockReturnValue(true);
  });

  afterEach(() => {
    global.EventSource = originalES;
    vi.restoreAllMocks();
  });

  it('handles cancellation and displays 409 error when ticket is already checked in', async () => {
    vi.spyOn(apiModule, 'apiFetch').mockImplementation(async (url, opts) => {
      if (url === '/api/tickets/ALREADY_IN' && !opts?.method) {
        return {
          ok: true,
          status: 200,
          data: {
            status: 'confirmed',
            ticket_code: 'ALREADY_IN',
            position_in_waitlist: null,
            event: { id: 1, title: 'Checkin Event', starts_at: '2026-11-20T10:00:00Z' },
          },
        };
      }
      if (url === '/api/tickets/ALREADY_IN' && opts?.method === 'DELETE') {
        return {
          ok: false,
          status: 409,
          data: { detail: 'Registration is already checked in and cannot be cancelled' },
        };
      }
      return { ok: true, status: 200, data: {} };
    });

    render(
      <MemoryRouter initialEntries={['/ticket/ALREADY_IN']}>
        <Routes>
          <Route path="/ticket/:code" element={<TicketPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Билет ALREADY_IN')).toBeInTheDocument();
    expect(screen.getByText('Подтверждён')).toBeInTheDocument();

    // Click cancel
    fireEvent.click(screen.getByRole('button', { name: /Отказаться от участия/i }));

    // 409 error shown
    expect(
      await screen.findByText(/Registration is already checked in and cannot be cancelled/i)
    ).toBeInTheDocument();
  });
});
