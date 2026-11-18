import { Link } from 'react-router-dom';

export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <div className="text-6xl">♚</div>
      <h1 className="mt-4 text-2xl font-black">Shah! This page doesn't exist.</h1>
      <p className="mt-2 text-ink-300">The link may be old, or the game may have expired.</p>
      <Link to="/" className="btn-primary mt-6">
        Back to the lobby
      </Link>
    </div>
  );
}
