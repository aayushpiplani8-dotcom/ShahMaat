// First Google sign-in: pick a username. Google's account id waits in a signed,
// httpOnly cookie set by the callback; this page only sends the chosen name.
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ErrorBox } from '../components/ui';
import { post } from '../lib/api';
import { useAuth } from '../lib/auth';

export default function Welcome() {
  const navigate = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const [username, setUsername] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSession(await post('/api/auth/google/complete', { username }, { auth: false }));
      navigate('/', { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="panel mx-auto max-w-sm space-y-4 p-6">
      <h1 className="text-xl font-black">Choose your username</h1>
      <p className="text-sm text-ink-300">This is how other players will see you. You can't change it later.</p>
      <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={20} required />
      <ErrorBox error={error} />
      <button className="btn-primary w-full" disabled={busy}>
        Continue
      </button>
    </form>
  );
}
