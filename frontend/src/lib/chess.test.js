import { describe, expect, it } from 'vitest';

import { parseBestMove, parseInfo, scoreToCp, toWhite } from '../engine/uci';
import { captured, fensFromMoves, parseUserGame, uciLineToSan } from './chess';
import { describeResult, formatClock, formatEval } from './format';

describe('uci parsing', () => {
  it('reads score and principal variation', () => {
    const info = parseInfo('info depth 18 seldepth 25 multipv 1 score cp -34 nodes 1 pv e7e5 g1f3');
    expect(info).toMatchObject({ depth: 18, multipv: 1, cp: -34, mate: null, pv: ['e7e5', 'g1f3'] });
  });
  it('ignores bound scores and lines without pv', () => {
    expect(parseInfo('info depth 10 score cp 20 lowerbound pv e2e4')).toBeNull();
    expect(parseInfo('info string NNUE loaded')).toBeNull();
  });
  it('converts to white point of view', () => {
    expect(toWhite({ cp: 50, mate: null }, 'b')).toEqual({ cp: -50, mate: null });
    expect(scoreToCp({ mate: 2 })).toBe(9980);
    expect(scoreToCp({ mate: -1 })).toBe(-9990);
  });
  it('reads bestmove', () => {
    expect(parseBestMove('bestmove e2e4 ponder e7e5')).toBe('e2e4');
    expect(parseBestMove('bestmove (none)')).toBeNull();
    expect(parseBestMove('info depth 1')).toBeUndefined();
  });
});

describe('chess helpers', () => {
  it('builds positions and SAN', () => {
    const fens = fensFromMoves(['e2e4', 'e7e5']);
    expect(fens).toHaveLength(3);
    expect(uciLineToSan(fens[0], ['e2e4', 'e7e5', 'zzzz'])).toEqual(['e4', 'e5']);
  });
  it('counts captured material', () => {
    const fen = fensFromMoves(['e2e4', 'd7d5', 'e4d5'])[3];
    expect(captured(fen)).toEqual({ takenBy: { w: ['p'], b: [] }, balance: 1 });
  });
  it('parses PGN and FEN input', () => {
    expect(parseUserGame('1. e4 e5 2. Nf3 *').moves).toEqual(['e2e4', 'e7e5', 'g1f3']);
    const fen = '8/8/8/4k3/8/8/8/4K2Q w - - 0 1';
    expect(parseUserGame(fen)).toEqual({ moves: [], initialFen: fen });
    expect(() => parseUserGame('')).toThrow();
  });
});

describe('formatting', () => {
  it('formats clocks', () => {
    expect(formatClock(65_000)).toBe('1:05');
    expect(formatClock(9_400)).toBe('9.4');
  });
  it('formats evals', () => {
    expect(formatEval(123)).toBe('+1.2');
    expect(formatEval(null, -3)).toBe('-M3');
    expect(formatEval(9980)).toBe('M2');
  });
  it('describes results', () => {
    expect(describeResult('1-0', 'checkmate', 'A', 'B')).toBe('A won by checkmate');
    expect(describeResult('1/2-1/2', 'agreement')).toBe('Draw by agreement');
  });
});
