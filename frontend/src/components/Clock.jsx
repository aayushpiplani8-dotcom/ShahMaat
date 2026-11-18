import { useEffect, useRef, useState } from 'react';

import { formatClock } from '../lib/format';
import { sounds } from '../lib/sounds';

/**
 * Counts down locally between server updates. `baseMs` is the time left when the
 * snapshot arrived and `since` is performance.now() at that moment, so the display
 * stays correct no matter how the browser's wall clock differs from the server's.
 */
export default function Clock({ baseMs, since, running, active }) {
  const [now, setNow] = useState(() => performance.now());
  const warned = useRef(false);

  useEffect(() => {
    if (!running) return;
    let raf;
    const tick = () => {
      setNow(performance.now());
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running]);

  const ms = running ? Math.max(0, baseMs - (now - since)) : baseMs;
  const low = ms < 20_000;

  useEffect(() => {
    if (running && low && !warned.current) {
      warned.current = true;
      sounds.lowTime();
    }
    if (!low) warned.current = false;
  }, [running, low]);

  return (
    <div
      className={`min-w-[6.5rem] rounded-xl px-3 py-1.5 text-right font-mono text-2xl font-bold tabular-nums transition ${
        active
          ? low
            ? 'bg-blunder text-white'
            : 'bg-ink-100 text-ink-950'
          : 'bg-ink-800 text-ink-300'
      }`}
      aria-live="off"
    >
      {formatClock(ms)}
    </div>
  );
}
