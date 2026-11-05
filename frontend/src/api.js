/**
 * Small API client wrapper around fetch.
 * Returns { ok, status, data } and never throws on HTTP errors or network errors.
 */
export async function apiFetch(url, options = {}) {
  try {
    const defaultHeaders = {
      'Accept': 'application/json',
    };
    if (options.body && typeof options.body === 'string') {
      defaultHeaders['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    });

    let data = null;
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      try {
        data = await response.json();
      } catch (err) {
        data = null;
      }
    } else {
      try {
        data = await response.text();
      } catch (err) {
        data = null;
      }
    }

    return {
      ok: response.ok,
      status: response.status,
      data,
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: { detail: error.message || 'Ошибка сети' },
    };
  }
}
