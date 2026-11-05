import React from 'react';
import { Routes, Route } from 'react-router-dom';
import EventListPage from './pages/EventListPage';
import EventPage from './pages/EventPage';
import TicketPage from './pages/TicketPage';
import OrganizerPage from './pages/OrganizerPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<EventListPage />} />
      <Route path="/events/:id" element={<EventPage />} />
      <Route path="/ticket/:code" element={<TicketPage />} />
      <Route path="/organizer/:secret" element={<OrganizerPage />} />
    </Routes>
  );
}
