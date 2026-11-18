import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Card, ErrorBox, RequireAuth } from '../components/ui';
import { del, patch } from '../lib/api';
import { logout, useAuth } from '../lib/auth';

function SettingsInner() {
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const navigate = useNavigate();
  const [chesscom, setChesscom] = useState(user.chesscom_username ?? '');
  const [saved, setSaved] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState(null);

  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      const res = await patch('/api/me', { chesscom_username: chesscom.trim() || null });
      setUser({ chesscom_username: res.chesscom_username });
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setError(err);
    }
  }

  async function deleteAccount() {
    try {
      await del('/api/me', { confirm_username: confirm });
      await logout();
      navigate('/');
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <h1 className="text-2xl font-black">Settings</h1>
      <Card title="chess.com account">
        <form onSubmit={save} className="space-y-3">
          <p className="text-sm text-ink-300">
            Link your chess.com username so mistakes in your imported games turn into puzzles (we need to know which
            side you played).
          </p>
          <input className="input" placeholder="chess.com username" value={chesscom} onChange={(e) => setChesscom(e.target.value)} />
          <button className="btn-primary">{saved ? 'Saved ✓' : 'Save'}</button>
        </form>
      </Card>
      <Card title="Danger zone">
        <p className="mb-3 text-sm text-ink-300">
          Deleting your account removes your games, ratings, reviews and puzzles for good. Type <b>{user.username}</b> to
          confirm.
        </p>
        <div className="flex gap-2">
          <input className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button className="btn-danger" disabled={confirm !== user.username} onClick={deleteAccount}>
            Delete
          </button>
        </div>
      </Card>
      <ErrorBox error={error} />
    </div>
  );
}

export default function Settings() {
  return (
    <RequireAuth>
      <SettingsInner />
    </RequireAuth>
  );
}
