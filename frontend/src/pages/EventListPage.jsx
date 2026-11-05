import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '../api';

export default function EventListPage() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Form state
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [startsAt, setStartsAt] = useState('');
  const [capacity, setCapacity] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  // New event created info
  const [createdEvent, setCreatedEvent] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadEvents();
  }, []);

  async function loadEvents() {
    setLoading(true);
    const res = await apiFetch('/api/events');
    if (res.ok) {
      setEvents(res.data);
    } else {
      setError('Не удалось загрузить мероприятия');
    }
    setLoading(false);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);

    if (!startsAt) {
      setFormError('Укажите дату и время начала');
      setSubmitting(false);
      return;
    }

    // Convert local datetime to ISO 8601 with timezone offset
    const dateObj = new Date(startsAt);
    if (isNaN(dateObj.getTime())) {
      setFormError('Неверный формат даты и времени');
      setSubmitting(false);
      return;
    }
    const isoString = dateObj.toISOString();

    const payload = {
      title,
      description: description || null,
      starts_at: isoString,
      capacity: parseInt(capacity, 10),
    };

    const res = await apiFetch('/api/events', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    setSubmitting(false);

    if (res.ok) {
      setCreatedEvent(res.data);
      setTitle('');
      setDescription('');
      setStartsAt('');
      setCapacity('');
      loadEvents();
    } else {
      if (res.status === 422) {
        if (Array.isArray(res.data?.detail)) {
          const msg = res.data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
          setFormError(`Ошибка валидации: ${msg}`);
        } else {
          setFormError(`Ошибка валидации: ${res.data?.detail || 'Проверьте введённые данные'}`);
        }
      } else {
        setFormError(res.data?.detail || 'Не удалось создать мероприятие');
      }
    }
  }

  function handleCopy() {
    if (!createdEvent?.organizer_secret) return;
    const url = `${window.location.origin}/organizer/${createdEvent.organizer_secret}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    });
  }

  return (
    <div className="container">
      <div className="header">
        <h1>Мероприятия</h1>
      </div>

      {createdEvent && (
        <div className="card" style={{ borderColor: '#28a745', backgroundColor: '#f4fff4' }}>
          <h3 style={{ marginTop: 0, color: '#155724' }}>Мероприятие успешно создано!</h3>
          <div className="alert alert-warning">
            <strong>Внимание!</strong> Ссылка организатора показывается только один раз и даёт полный доступ к управлению мероприятием. Сохраните её сейчас.
          </div>
          <p>
            <strong>Ссылка организатора:</strong>{' '}
            <Link to={`/organizer/${createdEvent.organizer_secret}`}>
              {`${window.location.origin}/organizer/${createdEvent.organizer_secret}`}
            </Link>
          </p>
          <button className="btn btn-secondary" onClick={handleCopy}>
            {copied ? 'Скопировано!' : 'Копировать ссылку'}
          </button>
        </div>
      )}

      <div className="card">
        <h2>Создать мероприятие</h2>
        {formError && <div className="alert alert-danger">{formError}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Название *</label>
            <input
              type="text"
              className="form-control"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label>Описание</label>
            <textarea
              className="form-control"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>Дата и время начала *</label>
            <input
              type="datetime-local"
              className="form-control"
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label>Лимит мест (вместимость) *</label>
            <input
              type="number"
              min="1"
              className="form-control"
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? 'Создание...' : 'Создать мероприятие'}
          </button>
        </form>
      </div>

      <h2>Список мероприятий</h2>
      {loading && <p>Загрузка...</p>}
      {error && <div className="alert alert-danger">{error}</div>}
      {!loading && events.length === 0 && <p>Мероприятий пока нет.</p>}

      <div className="events-list">
        {events.map((ev) => (
          <div key={ev.id} className="card">
            <h3 style={{ marginTop: 0 }}>
              <Link to={`/events/${ev.id}`}>{ev.title}</Link>
            </h3>
            {ev.description && <p>{ev.description}</p>}
            <p>
              <strong>Начало:</strong> {new Date(ev.starts_at).toLocaleString('ru-RU')}
            </p>
            <div className="counters-grid">
              <div className="counter-box">
                <div className="counter-value">{ev.confirmed_count} / {ev.capacity}</div>
                <div className="counter-label">Участники</div>
              </div>
              <div className="counter-box">
                <div className="counter-value">{ev.waitlist_count}</div>
                <div className="counter-label">В листе ожидания</div>
              </div>
            </div>
            <Link to={`/events/${ev.id}`} className="btn">
              Подробнее и регистрация
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
