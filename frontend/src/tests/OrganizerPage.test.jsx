import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import OrganizerPage from '../pages/OrganizerPage';
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

describe('OrganizerPage', () => {
  const originalES = global.EventSource;

  beforeEach(() => {
    global.EventSource = MockEventSource;
  });

  afterEach(() => {
    global.EventSource = originalES;
    vi.restoreAllMocks();
  });

  it('displays access denied screen for invalid secret (404)', async () => {
    vi.spyOn(apiModule, 'apiFetch').mockResolvedValue({
      ok: false,
      status: 404,
      data: { detail: 'Event not found' },
    });

    render(
      <MemoryRouter initialEntries={['/organizer/WRONG_SECRET']}>
        <Routes>
          <Route path="/organizer/:secret" element={<OrganizerPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText(/Доступ запрещён \/ Мероприятие не найдено/i)).toBeInTheDocument();
  });

  it('renders organizer view and handles 200, 409, and 422 checkin responses', async () => {
    vi.spyOn(apiModule, 'apiFetch').mockImplementation(async (url, opts) => {
      if (url === '/api/organizer/VALID_SECRET' && !opts?.method) {
        return {
          ok: true,
          status: 200,
          data: {
            event: { id: 1, title: 'Organizer Event', capacity: 10, starts_at: '2026-11-20T10:00:00Z' },
            counters: { confirmed: 2, waitlist: 1, checked_in: 0 },
            participants: [
              {
                email: 'attendee@example.com',
                status: 'confirmed',
                ticket_code: 'CODE1',
                queued_at: '2026-11-01T10:00:00Z',
                checked_in_at: null,
              },
            ],
          },
        };
      }
      if (url === '/api/organizer/VALID_SECRET/checkin' && opts?.method === 'POST') {
        const body = JSON.parse(opts.body);
        if (body.ticket_code === 'CODE1') {
          return {
            ok: true,
            status: 200,
            data: {
              email: 'attendee@example.com',
              ticket_code: 'CODE1',
              checked_in_at: '2026-11-04T12:00:00Z',
            },
          };
        }
        if (body.ticket_code === 'ALREADY_IN') {
          return {
            ok: false,
            status: 409,
            data: { detail: 'Ticket already checked in' },
          };
        }
        if (body.ticket_code === 'WAITLIST_CODE') {
          return {
            ok: false,
            status: 422,
            data: { detail: 'Ticket status is waitlist' },
          };
        }
      }
      return { ok: true, status: 200, data: {} };
    });

    render(
      <MemoryRouter initialEntries={['/organizer/VALID_SECRET']}>
        <Routes>
          <Route path="/organizer/:secret" element={<OrganizerPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText(/Панель организатора: Organizer Event/i)).toBeInTheDocument();
    expect(screen.getByText('attendee@example.com')).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/Введите код билета/i);
    const submitBtn = screen.getByRole('button', { name: /Отметить вход/i });

    // 1. Success checkin (200)
    fireEvent.change(input, { target: { value: 'CODE1' } });
    fireEvent.click(submitBtn);
    expect(await screen.findByText(/Успешный чекин! Билет CODE1/i)).toBeInTheDocument();

    // 2. Already checked in (409)
    fireEvent.change(input, { target: { value: 'ALREADY_IN' } });
    fireEvent.click(submitBtn);
    expect(await screen.findByText(/Ошибка 409: Ticket already checked in/i)).toBeInTheDocument();

    // 3. Waitlist ticket (422)
    fireEvent.change(input, { target: { value: 'WAITLIST_CODE' } });
    fireEvent.click(submitBtn);
    expect(await screen.findByText(/Ошибка 422: Ticket status is waitlist/i)).toBeInTheDocument();
  });
});
