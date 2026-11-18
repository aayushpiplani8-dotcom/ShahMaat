import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ErrorBox, RequireAuth, Spinner } from '../components/ui';
import { get, post } from '../lib/api';
import { useAuth } from '../lib/auth';
import { TIME_CLASS_ICON } from '../lib/format';

function ChallengeInner() {
  const { code } = useParams();
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const [challenge, setChallenge] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get(`/api/challenges/${code}`, { auth: false }).then(setChallenge).catch(setError);
  }, [code]);

  async function accept() {
    try {
      const { game_id } = await post(`/api/challenges/${code}/accept`);
      navigate(`/game/${game_id}`);
    } catch (e) {
      setError(e);
    }
  }

  if (error) return <ErrorBox error={error} />;
  if (!challenge) return <Spinner />;
  const mine = challenge.creator_id === user?.id;
  const yourColor = { white: 'Black', black: 'White', random: 'Random' }[challenge.color];

  return (
    <div className="panel mx-auto max-w-md space-y-4 p-6 text-center">
      <div className="text-4xl">{TIME_CLASS_ICON[challenge.tc.time_class]}</div>
      <h1 className="text-xl font-black">
        {mine ? 'Your challenge' : `${challenge.creator} challenges you`}
      </h1>
      <p className="text-ink-300">
        {challenge.tc.key} · {challenge.rated ? 'Rated' : 'Casual'} · you play {mine ? '' : yourColor}
      </p>
      {mine ? (
        <p className="text-sm text-ink-300">Waiting for your friend to open this link…</p>
      ) : (
        <button className="btn-primary w-full" onClick={accept}>
          Accept and play
        </button>
      )}
    </div>
  );
}

export default function Challenge() {
  return (
    <RequireAuth>
      <ChallengeInner />
    </RequireAuth>
  );
}
