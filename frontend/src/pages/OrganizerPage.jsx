import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';
import { useEventSource } from '../useEventSource';

export default function OrganizerPage() {
  const { secret } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState(null);

  // Live state
  const [counters, setCounters] = useState({ confirmed: 0, waitlist: 0, checked_in: 0 });
  const [participants, setParticipants] = useState([]);

  // Check-in form
  const [checkinCode, setCheckinCode] = useState('');
  const [checkingIn, setCheckingIn] = useState(false);
  const [checkinStatus, setCheckinStatus] = useState(null); // { type: 'success'|'error', text: '' }

  // Reschedule form
  const [newStartsAt, setNewStartsAt] = useState('');
  const [rescheduling, setRescheduling] = useState(false);
  const [rescheduleMsg, setRescheduleMsg] = useState(null);
  const [rescheduleErr, setRescheduleErr] = useState(null);

  const handleCountsUpdate = useCallback((newCounts) => {
    if (newCounts) {
      setCounters(newCounts);
    }
  }, []);

  const handleParticipantsUpdate = useCallback((newParticipants) => {
    if (Array.isArray(newParticipants)) {
      setParticipants(newParticipants);
    }
  }, []);

  const { status: sseStatus } = useEventSource(
    secret && !accessDenied ? `/api/organizer/${secret}/stream` : null,
    {
      counts: handleCountsUpdate,
      participants: handleParticipantsUpdate,
    }
  );

  useEffect(() => {
    loadOrganizerView();
  }, [secret]);

  async function loadOrganizerView() {
    setLoading(true);
    setAccessDenied(false);
    setError(null);

    const res = await apiFetch(`/api/organizer/${secret}`);
    if (res.ok) {
      setData(res.data);
      setCounters(res.data.counters);
      setParticipants(res.data.participants);
    } else {
      if (res.status === 404) {
        setAccessDenied(true);
      } else {
        setError(res.data?.detail || 'Ошибка загрузки данных организатора');
      }
    }
    setLoading(false);
  }

  async function handleCheckin(e) {
    e.preventDefault();
    if (!checkinCode.trim()) return;

    setCheckingIn(true);
    setCheckinStatus(null);

    const res = await apiFetch(`/api/organizer/${secret}/checkin`, {
      method: 'POST',
      body: JSON.stringify({ ticket_code: checkinCode.trim() }),
    });

    setCheckingIn(false);

    if (res.ok) {
      setCheckinStatus({
        type: 'success',
        text: `Успешный чекин! Билет ${res.data.ticket_code} (${res.data.email}) отмечен.`,
      });
      setCheckinCode('');
    } else {
      if (res.status === 404) {
        setCheckinStatus({
          type: 'error',
          text: 'Билет не найден или не относится к данному мероприятию (404)',
        });
      } else if (res.status === 409) {
        setCheckinStatus({
          type: 'error',
          text: `Ошибка 409: ${res.data?.detail || 'Участник уже был отмечен на входе'}`,
        });
      } else if (res.status === 422) {
        setCheckinStatus({
          type: 'error',
          text: `Ошибка 422: ${res.data?.detail || 'Чек-ин возможен только для участников со статусом "confirmed"'}`,
        });
      } else {
        setCheckinStatus({
          type: 'error',
          text: res.data?.detail || 'Ошибка при регистрации входа',
        });
      }
    }
  }

  async function handleReschedule(e) {
    e.preventDefault();
    setRescheduleMsg(null);
    setRescheduleErr(null);

    if (!newStartsAt) {
      setRescheduleErr('Укажите новую дату и время');
      return;
    }

    const dateObj = new Date(newStartsAt);
    if (isNaN(dateObj.getTime())) {
      setRescheduleErr('Неверный формат даты и времени');
      return;
    }

    setRescheduling(true);
    const res = await apiFetch(`/api/organizer/${secret}`, {
      method: 'PATCH',
      body: JSON.stringify({ starts_at: dateObj.toISOString() }),
    });
    setRescheduling(false);

    if (res.ok) {
      setRescheduleMsg('Мероприятие успешно перенесено!');
      setData((prev) => ({
        ...prev,
        event: {
          ...prev.event,
          starts_at: res.data.starts_at,
        },
      }));
      setNewStartsAt('');
    } else {
      if (res.status === 422) {
        setRescheduleErr('Ошибка 422: Новая дата должна быть в будущем и содержать часовой пояс');
      } else {
        setRescheduleErr(res.data?.detail || 'Не удалось перенести мероприятие');
      }
    }
  }

  if (loading) {
    return (
      <div className="container">
        <p>Загрузка панели организатора...</p>
      </div>
    );
  }

  if (accessDenied) {
    return (
      <div className="container">
        <div className="alert alert-danger">
          <h2>Доступ запрещён / Мероприятие не найдено (404)</h2>
          <p>Неверный секретный ключ организатора или мероприятие не существует.</p>
        </div>
        <Link to="/" className="btn btn-secondary">
          ← На главную
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <div className="alert alert-danger">{error}</div>
        <Link to="/" className="btn btn-secondary">
          ← На главную
        </Link>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="header">
        <div>
          <Link to="/" style={{ textDecoration: 'none', color: '#6c757d', fontSize: '14px' }}>
            ← На главную
          </Link>
          <h1 style={{ marginTop: '5px' }}>Панель организатора: {data.event.title}</h1>
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

      <div className="counters-grid">
        <div className="counter-box">
          <div className="counter-value">{counters.confirmed} / {data.event.capacity}</div>
          <div className="counter-label">Подтверждено</div>
        </div>
        <div className="counter-box">
          <div className="counter-value">{counters.waitlist}</div>
          <div className="counter-label">Лист ожидания</div>
        </div>
        <div className="counter-box" style={{ background: '#e8f5e9' }}>
          <div className="counter-value" style={{ color: '#2e7d32' }}>{counters.checked_in}</div>
          <div className="counter-label">Отмечено на входе (чекин)</div>
        </div>
      </div>

      {/* Check-in form */}
      <div className="card">
        <h2>Отметка на входе (Чек-ин)</h2>
        {checkinStatus && (
          <div className={`alert ${checkinStatus.type === 'success' ? 'alert-success' : 'alert-danger'}`}>
            {checkinStatus.text}
          </div>
        )}
        <form onSubmit={handleCheckin} style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            className="form-control"
            placeholder="Введите код билета (например, aB3_x9z-1)"
            value={checkinCode}
            onChange={(e) => setCheckinCode(e.target.value)}
            required
            style={{ flex: 1 }}
          />
          <button type="submit" className="btn" disabled={checkingIn}>
            {checkingIn ? 'Проверка...' : 'Отметить вход'}
          </button>
        </form>
      </div>

      {/* Reschedule form */}
      <div className="card">
        <h2>Перенос мероприятия</h2>
        <p>
          <strong>Текущее время начала:</strong>{' '}
          {new Date(data.event.starts_at).toLocaleString('ru-RU')}
        </p>
        {rescheduleMsg && <div className="alert alert-success">{rescheduleMsg}</div>}
        {rescheduleErr && <div className="alert alert-danger">{rescheduleErr}</div>}
        <form onSubmit={handleReschedule} style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <input
            type="datetime-local"
            className="form-control"
            value={newStartsAt}
            onChange={(e) => setNewStartsAt(e.target.value)}
            required
            style={{ flex: 1 }}
          />
          <button type="submit" className="btn btn-secondary" disabled={rescheduling}>
            {rescheduling ? 'Перенос...' : 'Изменить дату'}
          </button>
        </form>
      </div>

      {/* Participants table */}
      <div className="card">
        <h2>Список участников ({participants.length})</h2>
        {participants.length === 0 ? (
          <p>Зарегистрированных участников пока нет.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Статус</th>
                  <th>Код билета</th>
                  <th>Время в очереди</th>
                  <th>Чекин</th>
                </tr>
              </thead>
              <tbody>
                {participants.map((p) => (
                  <tr key={p.ticket_code}>
                    <td>{p.email}</td>
                    <td>
                      {p.status === 'confirmed' ? (
                        <span className="badge badge-confirmed">Подтверждён</span>
                      ) : p.status === 'waitlist' ? (
                        <span className="badge badge-waitlist">Лист ожидания</span>
                      ) : (
                        <span className="badge badge-cancelled">Отменён</span>
                      )}
                    </td>
                    <td>
                      <code>{p.ticket_code}</code>
                    </td>
                    <td>{new Date(p.queued_at).toLocaleString('ru-RU')}</td>
                    <td>
                      {p.checked_in_at ? (
                        <span style={{ color: '#2e7d32', fontWeight: 'bold' }}>
                          ✓ {new Date(p.checked_in_at).toLocaleTimeString('ru-RU')}
                        </span>
                      ) : (
                        <span style={{ color: '#6c757d' }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
