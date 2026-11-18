import './styles.css';

import { lazy, StrictMode, Suspense, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import Layout from './components/Layout';
import { Spinner } from './components/ui';
import { refreshSession, useAuth } from './lib/auth';
import { socket } from './lib/socket';
import Home from './pages/Home';

// Heavier pages load on demand, so the first visit downloads less.
const Game = lazy(() => import('./pages/Game'));
const Analysis = lazy(() => import('./pages/Analysis'));
const Review = lazy(() => import('./pages/Review'));
const Import = lazy(() => import('./pages/Import'));
const Bot = lazy(() => import('./pages/Bot'));
const Puzzles = lazy(() => import('./pages/Puzzles'));
const Profile = lazy(() => import('./pages/Profile'));
const Leaderboard = lazy(() => import('./pages/Leaderboard'));
const Watch = lazy(() => import('./pages/Watch'));
const Auth = lazy(() => import('./pages/Auth'));
const Welcome = lazy(() => import('./pages/Welcome'));
const Challenge = lazy(() => import('./pages/Challenge'));
const Settings = lazy(() => import('./pages/Settings'));
const NotFound = lazy(() => import('./pages/NotFound'));

function App() {
  const userId = useAuth((s) => s.user?.id);
  const status = useAuth((s) => s.status);

  // On load: try to resume the session from the refresh cookie.
  useEffect(() => {
    refreshSession();
  }, []);

  // Open the socket once we know who we are; reconnect if that changes (sign in/out).
  useEffect(() => {
    if (status !== 'ready') return;
    if (socket.status === 'idle') socket.start();
    else socket.restart();
  }, [status, userId]);

  return (
    <BrowserRouter>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="game/:id" element={<Game />} />
            <Route path="analysis" element={<Analysis />} />
            <Route path="review/:kind/:id" element={<Review />} />
            <Route path="import" element={<Import />} />
            <Route path="bot" element={<Bot />} />
            <Route path="puzzles" element={<Puzzles />} />
            <Route path="u/:username" element={<Profile />} />
            <Route path="leaderboard" element={<Leaderboard />} />
            <Route path="watch" element={<Watch />} />
            <Route path="login" element={<Auth mode="login" />} />
            <Route path="register" element={<Auth mode="register" />} />
            <Route path="welcome" element={<Welcome />} />
            <Route path="challenge/:code" element={<Challenge />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
