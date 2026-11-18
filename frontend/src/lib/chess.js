// Small chess helpers shared by pages.
import { Chess } from 'chess.js';

export const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

/** Positions (FEN) after each move: fens[0] = start, fens[i+1] = after move i. */
export function fensFromMoves(moves, initialFen = START_FEN) {
  const chess = new Chess(initialFen || START_FEN);
  const fens = [chess.fen()];
  for (const uci of moves) {
    chess.move(uciToMove(uci));
    fens.push(chess.fen());
  }
  return fens;
}

export function uciToMove(uci) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || undefined };
}

export function moveToUci(m) {
  return `${m.from}${m.to}${m.promotion || ''}`;
}

/** UCI line -> SAN list, stopping at the first move that doesn't fit the position. */
export function uciLineToSan(fen, line, limit = 8) {
  const chess = new Chess(fen);
  const out = [];
  for (const uci of line.slice(0, limit)) {
    try {
      out.push(chess.move(uciToMove(uci)).san);
    } catch {
      break;
    }
  }
  return out;
}

const VALUES = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
const START_COUNT = { p: 8, n: 2, b: 2, r: 2, q: 1 };

/** Pieces each side has captured, and the material balance (positive = White ahead). */
export function captured(fen) {
  const board = fen.split(' ')[0];
  const count = { w: { p: 0, n: 0, b: 0, r: 0, q: 0 }, b: { p: 0, n: 0, b: 0, r: 0, q: 0 } };
  for (const ch of board) {
    const lower = ch.toLowerCase();
    if (!(lower in START_COUNT)) continue;
    count[ch === lower ? 'b' : 'w'][lower] += 1;
  }
  const takenBy = { w: [], b: [] };
  let balance = 0;
  for (const piece of ['q', 'r', 'b', 'n', 'p']) {
    const missingBlack = Math.max(0, START_COUNT[piece] - count.b[piece]);
    const missingWhite = Math.max(0, START_COUNT[piece] - count.w[piece]);
    for (let i = 0; i < missingBlack; i++) takenBy.w.push(piece);
    for (let i = 0; i < missingWhite; i++) takenBy.b.push(piece);
    balance += (count.w[piece] - count.b[piece]) * VALUES[piece];
  }
  return { takenBy, balance };
}

export function pgnFromMoves(moves, headers = {}, initialFen) {
  const chess = new Chess(initialFen || START_FEN);
  for (const [k, v] of Object.entries(headers)) chess.setHeader(k, String(v));
  for (const uci of moves) chess.move(uciToMove(uci));
  return chess.pgn();
}

/** Parses PGN or FEN text typed by the user. Returns { moves, initialFen } or throws. */
export function parseUserGame(text) {
  const trimmed = text.trim();
  if (!trimmed) throw new Error('Paste a PGN or a FEN first.');
  if (/^[rnbqkpRNBQKP1-8]+(\/[rnbqkpRNBQKP1-8]+){7}\s[wb]\s/.test(trimmed)) {
    new Chess(trimmed); // throws on an invalid FEN
    return { moves: [], initialFen: trimmed };
  }
  const chess = new Chess();
  chess.loadPgn(trimmed);
  const history = chess.history({ verbose: true });
  const initialFen = chess.getHeaders?.().FEN || START_FEN;
  return { moves: history.map(moveToUci), initialFen };
}
