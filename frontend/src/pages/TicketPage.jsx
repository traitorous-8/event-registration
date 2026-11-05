import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../api';
import { useEventSource } from '../useEventSource';

export default function TicketPage() {
  const { code } = useParams();
  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Cancellation state
  const [cancelling, setCancelling] = useState(false);
  const [cancelMessage, setCancelMessage] = useState(null);
  const [cancelError, setCancelError] = useState(null);

  const handleTicketUpdate = useCallback((data) => {
    if (data && data.status) {
      setTicket((prev) => (prev ? { ...prev, ...data } : data));
    }
  }, []);

  const { status: sseStatus } = useEventSource(
    code ? `/api/tickets/${code}/stream` : null,
    { ticket: handleTicketUpdate }
  );

  useEffect(() => {
    loadTicket();
  }, [code]);

  async function loadTicket() {
    setLoading(true);
    setError(null);
    const res = await apiFetch(`/api/tickets/${code}`);
    if (res.ok) {
      setTicket(res.data);
    } else {
      if (res.status === 404) {
        setError('Билет не найден (404)');
      } else {
        setError(res.data?.detail || 'Ошибка при загрузке билета');
      }
    }
    setLoading(false);
  }

  async function handleCancel() {
    if (!window.confirm('Вы действительно хотите отказаться от участия и аннулировать билет?')) {
      return;
    }

    setCancelling(true);
    setCancelError(null);
    setCancelMessage(null);

    const res = await apiFetch(`/api/tickets/${code}`, {
      method: 'DELETE',
    });

    setCancelling(false);

    if (res.ok) {
      setCancelMessage('Регистрация успешно отменена.');
      setTicket((prev) => (prev ? { ...prev, status: 'cancelled' } : prev));
    } else {
      if (res.status === 409) {
        setCancelError(
          res.data?.detail || 'Участник уже отмечен на входе и регистрация не может быть отменена (409)'
        );
      } else if (res.status === 404) {
        setCancelError('Билет не найден (404)');
      } else {
        setCancelError(res.data?.detail || 'Не удалось отменить регистрацию');
      }
    }
  }

  function getStatusBadge(status) {
    switch (status) {
      case 'confirmed':
        return <span className="badge badge-confirmed">Подтверждён</span>;
      case 'waitlist':
        return <span className="badge badge-waitlist">В листе ожидания</span>;
      case 'cancelled':
        return <span className="badge badge-cancelled">Отменён</span>;
      default:
        return <span className="badge">{status}</span>;
    }
  }

  if (loading) {
    return (
      <div className="container">
        <p>Загрузка билета...</p>
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
          {ticket.event && (
            <Link
              to={`/events/${ticket.event.id}`}
              style={{ textDecoration: 'none', color: '#6c757d', fontSize: '14px' }}
            >
              ← К мероприятию «{ticket.event.title}»
            </Link>
          )}
          <h1 style={{ marginTop: '5px' }}>Билет {ticket.ticket_code}</h1>
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

      {cancelMessage && <div className="alert alert-success">{cancelMessage}</div>}
      {cancelError && <div className="alert alert-danger">{cancelError}</div>}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: '0 0 10px 0' }}>Статус билета</h3>
            <div style={{ fontSize: '18px' }}>{getStatusBadge(ticket.status)}</div>
          </div>
          {ticket.status === 'waitlist' && ticket.position_in_waitlist !== null && (
            <div className="counter-box" style={{ minWidth: '150px' }}>
              <div className="counter-value">{ticket.position_in_waitlist}</div>
              <div className="counter-label">Место в очереди</div>
            </div>
          )}
        </div>

        {ticket.status === 'waitlist' && (
          <p style={{ marginTop: '15px', color: '#856404', backgroundColor: '#fff3cd', padding: '10px', borderRadius: '4px' }}>
            Вы находитесь в листе ожидания. Если кто-то откажется от билета, ваше место автоматически подтвердится без перезагрузки этой страницы.
          </p>
        )}

        {ticket.status !== 'cancelled' && (
          <div style={{ marginTop: '20px', borderTop: '1px solid #dee2e6', paddingTop: '15px' }}>
            <button
              className="btn btn-danger"
              onClick={handleCancel}
              disabled={cancelling}
            >
              {cancelling ? 'Отмена регистрации...' : 'Отказаться от участия'}
            </button>
          </div>
        )}
      </div>

      {ticket.event && (
        <div className="card">
          <h3>Информация о мероприятии</h3>
          <p>
            <strong>Название:</strong> {ticket.event.title}
          </p>
          <p>
            <strong>Начало:</strong>{' '}
            {new Date(ticket.event.starts_at).toLocaleString('ru-RU')}
          </p>
          {ticket.event.description && <p>{ticket.event.description}</p>}
        </div>
      )}
    </div>
  );
}
