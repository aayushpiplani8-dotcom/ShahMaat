// Tiny synthesised sounds (Web Audio): no audio files to download or license.
let ctx = null;
let muted = (() => {
  try {
    return localStorage.getItem('sm-muted') === '1';
  } catch {
    return false;
  }
})();

function tone(freq, duration, type = 'sine', gain = 0.08, delay = 0) {
  if (muted) return;
  try {
    ctx ??= new AudioContext();
    const t = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    amp.gain.setValueAtTime(gain, t);
    amp.gain.exponentialRampToValueAtTime(0.0001, t + duration);
    osc.connect(amp).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + duration);
  } catch {
    /* audio not available (e.g. autoplay policy before first click) */
  }
}

export const sounds = {
  move: () => tone(420, 0.07, 'triangle'),
  capture: () => tone(260, 0.12, 'square', 0.05),
  check: () => tone(660, 0.1, 'sawtooth', 0.04),
  start: () => {
    tone(523, 0.12);
    tone(659, 0.12, 'sine', 0.08, 0.12);
  },
  end: () => {
    tone(659, 0.15);
    tone(440, 0.25, 'sine', 0.08, 0.15);
  },
  lowTime: () => tone(880, 0.05, 'square', 0.03),
  isMuted: () => muted,
  setMuted(v) {
    muted = v;
    try {
      localStorage.setItem('sm-muted', v ? '1' : '0');
    } catch {
      /* private mode */
    }
  },
};

export function soundForSan(san) {
  if (!san) return;
  if (san.includes('+') || san.includes('#')) sounds.check();
  else if (san.includes('x')) sounds.capture();
  else sounds.move();
}
