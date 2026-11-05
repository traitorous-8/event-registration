import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiFetch } from '../api';

describe('apiFetch', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('handles successful 200 response with JSON', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ message: 'success' }),
    });

    const res = await apiFetch('/api/test');
    expect(res.ok).toBe(true);
    expect(res.status).toBe(200);
    expect(res.data).toEqual({ message: 'success' });
  });

  it('handles 404 response without throwing', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      headers: { get: () => 'application/json' },
      json: async () => ({ detail: 'Not found' }),
    });

    const res = await apiFetch('/api/notfound');
    expect(res.ok).toBe(false);
    expect(res.status).toBe(404);
    expect(res.data).toEqual({ detail: 'Not found' });
  });

  it('handles 409 response without throwing', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      headers: { get: () => 'application/json' },
      json: async () => ({ detail: 'Conflict' }),
    });

    const res = await apiFetch('/api/conflict');
    expect(res.ok).toBe(false);
    expect(res.status).toBe(409);
    expect(res.data).toEqual({ detail: 'Conflict' });
  });

  it('handles 422 response without throwing', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      headers: { get: () => 'application/json' },
      json: async () => ({ detail: [{ msg: 'Invalid email' }] }),
    });

    const res = await apiFetch('/api/validation');
    expect(res.ok).toBe(false);
    expect(res.status).toBe(422);
    expect(res.data).toEqual({ detail: [{ msg: 'Invalid email' }] });
  });

  it('handles network failure gracefully without throwing', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

    const res = await apiFetch('/api/error');
    expect(res.ok).toBe(false);
    expect(res.status).toBe(0);
    expect(res.data).toEqual({ detail: 'Network error' });
  });
});
