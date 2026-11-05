import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import EventListPage from '../pages/EventListPage';
import * as apiModule from '../api';

describe('EventListPage', () => {
  beforeEach(() => {
    vi.spyOn(apiModule, 'apiFetch').mockImplementation(async (url, opts) => {
      if (url === '/api/events' && (!opts || !opts.method)) {
        return {
          ok: true,
          status: 200,
          data: [
            {
              id: 1,
              title: 'Тестовое событие',
              description: 'Описание',
              starts_at: '2026-11-04T15:00:00Z',
              capacity: 10,
              confirmed_count: 5,
              waitlist_count: 2,
            },
          ],
        };
      }
      return { ok: true, status: 200, data: {} };
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders event list and creates event, showing organizer link with copy button', async () => {
    render(
      <BrowserRouter>
        <EventListPage />
      </BrowserRouter>
    );

    // Initial event loads
    expect(await screen.findByText('Тестовое событие')).toBeInTheDocument();
    expect(screen.getByText('5 / 10')).toBeInTheDocument();

    // Mock create response
    vi.spyOn(apiModule, 'apiFetch').mockImplementation(async (url, opts) => {
      if (opts?.method === 'POST') {
        return {
          ok: true,
          status: 201,
          data: {
            id: 2,
            title: 'Новый митап',
            organizer_secret: 'secret_abc_123',
            starts_at: '2026-12-01T10:00:00Z',
            capacity: 5,
          },
        };
      }
      return { ok: true, status: 200, data: [] };
    });

    // Fill form by selector
    const titleInput = document.querySelector('input[type="text"]');
    fireEvent.change(titleInput, {
      target: { value: 'Новый митап' },
    });

    const dateInput = document.querySelector('input[type="datetime-local"]');
    fireEvent.change(dateInput, {
      target: { value: '2026-12-01T10:00' },
    });

    const capacityInput = document.querySelector('input[type="number"]');
    fireEvent.change(capacityInput, {
      target: { value: '5' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Создать мероприятие/i }));

    // Organizer link is displayed with warning
    expect(await screen.findByText(/Мероприятие успешно создано!/i)).toBeInTheDocument();
    expect(screen.getByText(/Ссылка организатора показывается только один раз/i)).toBeInTheDocument();
    expect(screen.getByText(/secret_abc_123/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Копировать ссылку/i })).toBeInTheDocument();
  });
});
