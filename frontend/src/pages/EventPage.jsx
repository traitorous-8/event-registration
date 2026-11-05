import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';
import { useEventSource } from '../useEventSource';

export default function EventPage() {
  const { id } = useParams();
  const [event, setEvent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Counters
  const [counters, setCounters] = useState({ confirmed: 0, waitlist: 0 });

  // Registration state
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [regResult, setRegResult] = useState(null);
  const [regError, setRegError] = useState(null);

  // Saved tickets in localStorage for this event
  const [savedTickets, setSavedTickets] = useState([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(`event_tickets_${id}`);
      if (stored) {
        setSavedTickets(JSON.parse(stored));
      }
    } catch (e) {
      // ignore localStorage errors
    }
  }, [id]);

  const handleCountsUpdate = useCallback((data) => {
    if (data && typeof data.confirmed === 'number') {
      setCounters({
        confirmed: data.confirmed,
        waitlist: data.waitlist,
      });
    }
  }, []);

  const { status: sseStatus } = useEventSource(
    id ? `/api/events/${id}/stream` : null,
    { counts: handleCountsUpdate }
  );

  useEffect(() => {
    loadEvent();
  }, [id]);

  async function loadEvent() {
    setLoading(true);
    setError(null);
    const res = await apiFetch(`/api/events/${id}`);
    if (res.ok) {
      setEvent(res.data);
      setCounters({
        confirmed: res.data.confirmed_count,
        waitlist: res.data.waitlist_count,
      });
    } else {
      if (res.status === 404) {
        setError('Мероприятие не найдено (404)');
      } else {
        setError(res.data?.detail || 'Ошибка при загрузке мероприятия');
      }
    }
    setLoading(false);
  }

  async function handleRegister(e) {
    e.preventDefault();
    setRegError(null);
    setRegResult(null);
    setSubmitting(true);

    const res = await apiFetch(`/api/events/${id}/registrations`, {
      method: 'POST',
      body: JSON.stringify({ email }),
    });

    setSubmitting(false);

    if (res.ok) {
      setRegResult(res.data);
      setEmail('');

      // Save ticket to localStorage
      try {
        const currentStored = localStorage.getItem(`event_tickets_${id}`);
        const parsed = currentStored ? JSON.parse(currentStored) : [];
        if (!parsed.some((t) => t.ticket_code === res.data.ticket_code)) {
          const updated = [...parsed, res.data];
          localStorage.setItem(`event_tickets_${id}`, JSON.stringify(updated));
          setSavedTickets(updated);
        }
      } catch (e) {
        // ignore
      }
    } else {
      if (res.status === 409) {
        setRegError('Регистрация закрыта: мероприятие уже началось (409)');
      } else if (res.status === 422) {
        setRegError('Некорректный email адрес');
      } else {
        setRegError(res.data?.detail || 'Не удалось зарегистрироваться');
      }
    }
  }

  if (loading) {
    return (
      <div className="container">
        <p>Загрузка...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <div className="alert alert-danger">{error}</div>
        <Link to="/" className="btn btn-secondary">
          ← К списку мероприятий
        </Link>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="header">
        <div>
          <Link to="/" style={{ textDecoration: 'none', color: '#6c757d', fontSize: '14px' }}>
            ← К списку мероприятий
          </Link>
          <h1 style={{ marginTop: '5px' }}>{event.title}</h1>
        </div>
        <div>
          {sseStatus === 'connected' ? (
            <span className="badge badge-live">● live</span>
          ) : sseStatus === 'connecting' ? (
            <span className="badge badge-connecting">подключение...</span>
          ) : (
            <span className="badge badge-error">нет связи</span>
          )}
        </div>
      </div>

      <div className="card">
        {event.description && <p style={{ fontSize: '16px' }}>{event.description}</p>}
        <p>
          <strong>Дата и время начала:</strong>{' '}
          {new Date(event.starts_at).toLocaleString('ru-RU')}
        </p>

        <div className="counters-grid">
          <div className="counter-box">
            <div className="counter-value">{counters.confirmed} / {event.capacity}</div>
            <div className="counter-label">Участники (подтверждено)</div>
          </div>
          <div className="counter-box">
            <div className="counter-value">{counters.waitlist}</div>
            <div className="counter-label">В листе ожидания</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Регистрация на мероприятие</h2>
        {regResult && (
          <div className={`alert ${regResult.status === 'confirmed' ? 'alert-success' : 'alert-warning'}`}>
            <p style={{ margin: '0 0 10px 0', fontWeight: 'bold' }}>
              {regResult.status === 'confirmed'
                ? 'Регистрация подтверждена! Место забронировано.'
                : 'Мест нет. Вы добавлены в лист ожидания.'}
            </p>
            <p style={{ margin: 0 }}>
              Ваш билет:{' '}
              <Link to={`/ticket/${regResult.ticket_code}`} style={{ fontWeight: 'bold' }}>
                Перейти к билету ({regResult.ticket_code})
              </Link>
            </p>
          </div>
        )}

        {regError && <div className="alert alert-danger">{regError}</div>}

        <form onSubmit={handleRegister}>
          <div className="form-group">
            <label>Ваш Email *</label>
            <input
              type="email"
              className="form-control"
              placeholder="name@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? 'Отправка...' : 'Зарегистрироваться'}
          </button>
        </form>
      </div>

      {savedTickets.length > 0 && (
        <div className="card">
          <h3>Ваши сохранённые билеты на это мероприятие</h3>
          <ul>
            {savedTickets.map((t) => (
              <li key={t.ticket_code} style={{ marginBottom: '8px' }}>
                <Link to={`/ticket/${t.ticket_code}`}>
                  Билет <code>{t.ticket_code}</code>
                </Link>{' '}
                ({t.status === 'confirmed' ? 'подтверждён' : 'лист ожидания'})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
