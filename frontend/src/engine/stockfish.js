// Stockfish 17.1 (WebAssembly) running in a Web Worker.
//
// A Worker is a separate thread: the engine can think hard for seconds without
// freezing the page. We talk to it in UCI (plain text commands).
// Searches are queued so two parts of the page can't mix their outputs, and a
// watchdog restarts the engine if it ever goes silent mid-search.
import { parseBestMove, parseInfo, toWhite } from './uci';

const WATCHDOG_MS = 20_000;

export class Engine {
  constructor(url = '/stockfish/stockfish.js') {
    this.url = url;
    this.options = {};
    this.queue = Promise.resolve();
    this.current = null;
    this.handlers = new Set();
    this.disposed = false;
    this.boot();
  }

  boot() {
    this.worker = new Worker(this.url);
    this.worker.onmessage = (e) => this.onLine(String(e.data));
    this.worker.onerror = () => this.restart('worker error');
    this.ready = (async () => {
      await this.waitFor('uci', (l) => l === 'uciok');
      for (const [name, value] of Object.entries(this.options)) this.post(`setoption name ${name} value ${value}`);
      await this.waitFor('isready', (l) => l === 'readyok');
    })();
  }

  restart(reason) {
    if (this.disposed) return;
    console.warn(`Stockfish restarting: ${reason}`);
    this.worker.terminate();
    if (this.current) {
      this.current.reject(new Error('engine restarted'));
      this.current = null;
    }
    this.boot();
  }

  post(cmd) {
    this.worker.postMessage(cmd);
  }

  waitFor(cmd, match) {
    return new Promise((resolve) => {
      const handler = (line) => {
        if (match(line)) {
          this.handlers.delete(handler);
          resolve();
        }
      };
      this.handlers.add(handler);
      this.post(cmd);
    });
  }

  kick() {
    clearTimeout(this.watchdog);
    if (this.current) this.watchdog = setTimeout(() => this.restart('no output'), WATCHDOG_MS);
  }

  onLine(line) {
    for (const h of [...this.handlers]) h(line);
    const job = this.current;
    if (!job) return;
    this.kick();
    const info = parseInfo(line);
    if (info) {
      if (info.multipv === 1) job.last = info;
      job.lines[info.multipv - 1] = { ...info, white: toWhite(info, job.side) };
      if (!job.cancelled) job.onInfo?.({ ...info, white: toWhite(info, job.side), lines: job.lines.slice() });
      return;
    }
    const best = parseBestMove(line);
    if (best === undefined) return;
    this.current = null;
    clearTimeout(this.watchdog);
    job.resolve({
      bestMove: best,
      score: toWhite(job.last, job.side),
      depth: job.last?.depth ?? 0,
      pv: job.last?.pv ?? [],
      lines: job.lines.map((l) => l && { ...l }),
      cancelled: job.cancelled,
    });
  }

  setOption(name, value) {
    this.options[name] = String(value);
    this.post(`setoption name ${name} value ${value}`);
  }

  /**
   * Searches `fen`. opts: { depth, movetime, multipv }. Calls onInfo as the search deepens.
   * Pass an AbortSignal to cancel just this search.
   */
  search(fen, opts = {}, onInfo, signal) {
    const cancelled = { bestMove: null, score: null, depth: 0, pv: [], lines: [], cancelled: true };
    const run = this.queue.then(async () => {
      await this.ready;
      if (signal?.aborted) return cancelled;
      return new Promise((resolve, reject) => {
        const job = { side: fen.split(' ')[1] === 'b' ? 'b' : 'w', onInfo, resolve, reject, last: null, lines: [], cancelled: false };
        this.current = job;
        signal?.addEventListener(
          'abort',
          () => {
            if (this.current === job && !job.cancelled) {
              job.cancelled = true;
              this.post('stop');
            }
          },
          { once: true },
        );
        this.post(`setoption name MultiPV value ${opts.multipv ?? 1}`);
        this.post(`position fen ${fen}`);
        const limits = [opts.depth && `depth ${opts.depth}`, opts.movetime && `movetime ${opts.movetime}`].filter(Boolean);
        this.post(`go ${limits.join(' ') || 'infinite'}`);
        this.kick();
      });
    });
    this.queue = run.catch(() => {});
    return run;
  }

  /** Clears the engine's memory between games so reviews are reproducible. */
  async newGame() {
    await this.queue;
    await this.ready;
    this.post('ucinewgame');
    await this.waitFor('isready', (l) => l === 'readyok');
  }

  dispose() {
    this.disposed = true;
    clearTimeout(this.watchdog);
    this.worker.terminate();
  }
}

let shared = null;
/** One engine for the whole tab: Stockfish's neural network is loaded once. */
export function getEngine() {
  if (!shared) {
    shared = new Engine();
    shared.setOption('Hash', 32);
  }
  return shared;
}
