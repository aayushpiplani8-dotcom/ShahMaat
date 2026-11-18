// The chessboard: drag-and-drop AND click-to-move, legal-move dots, last-move and
// check highlights, promotion picker, premoves, and engine arrows.
//
// The board never decides what's legal on its own for live games: it only
// proposes a move to its parent (onMove), which asks the server.
import { Chess } from 'chess.js';
import { useMemo, useState } from 'react';
import { Chessboard } from 'react-chessboard';

const LIGHT = { backgroundColor: '#efe4cf' };
const DARK = { backgroundColor: '#6d7fa8' };
const LAST_MOVE = { backgroundColor: 'rgba(245, 165, 36, 0.42)' };
const SELECTED = { backgroundColor: 'rgba(124, 108, 242, 0.55)' };
const PREMOVE = { backgroundColor: 'rgba(124, 108, 242, 0.35)' };
const DOT = { background: 'radial-gradient(circle, rgba(13,16,32,.35) 22%, transparent 24%)' };
const RING = { background: 'radial-gradient(circle, transparent 58%, rgba(13,16,32,.35) 60%)' };
const CHECK = { background: 'radial-gradient(circle, rgba(235,87,87,.95) 0%, rgba(235,87,87,.4) 45%, transparent 75%)' };

function withTurn(fen, turn) {
  const parts = fen.split(' ');
  parts[1] = turn;
  parts[3] = '-'; // en passant only exists for the side that just got it
  return parts.join(' ');
}

/** Legal targets for a square; for premoves, computed as if it were our turn. */
function targetsFor(fen, square, color) {
  try {
    const chess = new Chess(fen.split(' ')[1] === color ? fen : withTurn(fen, color));
    return chess.moves({ square, verbose: true });
  } catch {
    return [];
  }
}

function kingInCheckSquare(fen) {
  try {
    const chess = new Chess(fen);
    if (!chess.inCheck()) return null;
    const turn = chess.turn();
    for (const row of chess.board()) {
      for (const sq of row) if (sq && sq.type === 'k' && sq.color === turn) return sq.square;
    }
  } catch {
    /* invalid fen while typing */
  }
  return null;
}

/**
 * @param {object} props
 * @param {string} props.fen
 * @param {'white'|'black'} props.orientation
 * @param {'w'|'b'|'both'|null} props.movable  which side the user may move
 * @param {(m:{from:string,to:string,promotion?:string}) => boolean|void} props.onMove
 * @param {(m:{from,to,promotion}) => void} [props.onPremove]  allows premoves when set
 * @param {{from:string,to:string,promotion?:string}|null} [props.premove]
 * @param {[string,string]|null} [props.lastMove]
 * @param {Array<[string,string,string]>} [props.arrows]
 */
export default function Board({
  fen,
  orientation = 'white',
  movable = null,
  onMove,
  onPremove,
  premove = null,
  lastMove = null,
  arrows = [],
  id = 'board',
}) {
  const [selected, setSelected] = useState(null);
  const [promotion, setPromotion] = useState(null); // { from, to } waiting for a piece choice
  const turn = fen.split(' ')[1];

  const myColor = movable === 'both' ? turn : movable;
  const isMyTurn = movable === 'both' || movable === turn;
  const canPremove = Boolean(onPremove) && movable && movable !== 'both' && !isMyTurn;

  const targets = useMemo(
    () => (selected && myColor ? targetsFor(fen, selected, myColor) : []),
    [fen, selected, myColor],
  );

  const checkSquare = useMemo(() => kingInCheckSquare(fen), [fen]);

  const styles = useMemo(() => {
    const s = {};
    if (lastMove) {
      s[lastMove[0]] = LAST_MOVE;
      s[lastMove[1]] = LAST_MOVE;
    }
    if (premove) {
      s[premove.from] = PREMOVE;
      s[premove.to] = PREMOVE;
    }
    if (checkSquare) s[checkSquare] = { ...(s[checkSquare] || {}), ...CHECK };
    if (selected) s[selected] = SELECTED;
    for (const m of targets) s[m.to] = { ...(s[m.to] || {}), ...(m.captured ? RING : DOT) };
    return s;
  }, [lastMove, premove, checkSquare, selected, targets]);

  function pieceColorAt(square) {
    try {
      return new Chess(fen).get(square)?.color ?? null;
    } catch {
      return null;
    }
  }

  function needsPromotion(from, to) {
    const piece = new Chess(fen).get(from);
    return piece?.type === 'p' && (to[1] === '8' || to[1] === '1');
  }

  function attempt(from, to, promo) {
    setSelected(null);
    if (!isMyTurn) {
      if (canPremove) onPremove({ from, to, promotion: promo });
      return true;
    }
    const legal = targetsFor(fen, from, myColor).some((m) => m.to === to);
    if (!legal) return false;
    return onMove({ from, to, promotion: promo }) !== false;
  }

  function onSquareClick(square) {
    if (!movable) return;
    if (selected && selected !== square) {
      const isTarget = targets.some((m) => m.to === square);
      if (isTarget) {
        if (needsPromotion(selected, square)) {
          setPromotion({ from: selected, to: square });
          return;
        }
        attempt(selected, square);
        return;
      }
    }
    if (canPremove && premove) onPremove(null); // clicking cancels a premove
    const color = pieceColorAt(square);
    setSelected(color && color === myColor && square !== selected ? square : null);
  }

  function onPieceDrop(from, to) {
    return attempt(from, to);
  }

  function onPromotionPieceSelect(piece, from, to) {
    const origin = from || promotion?.from;
    const dest = to || promotion?.to;
    setPromotion(null);
    if (!piece || !origin || !dest) return false;
    return attempt(origin, dest, piece[1].toLowerCase());
  }

  function isDraggablePiece({ piece }) {
    if (!movable) return false;
    return piece[0] === myColor;
  }

  return (
    <div className="w-full select-none" aria-label="Chess board">
      <Chessboard
        id={id}
        position={fen}
        boardOrientation={orientation}
        onSquareClick={onSquareClick}
        onPieceDrop={onPieceDrop}
        onPieceDragBegin={(_, square) => setSelected(square)}
        onPromotionCheck={(from, to, piece) =>
          piece[1] === 'P' && ((piece[0] === 'w' && to[1] === '8') || (piece[0] === 'b' && to[1] === '1'))
        }
        onPromotionPieceSelect={onPromotionPieceSelect}
        showPromotionDialog={Boolean(promotion)}
        promotionToSquare={promotion?.to ?? null}
        isDraggablePiece={isDraggablePiece}
        arePiecesDraggable={Boolean(movable)}
        customSquareStyles={styles}
        customArrows={arrows}
        customLightSquareStyle={LIGHT}
        customDarkSquareStyle={DARK}
        customBoardStyle={{ borderRadius: '10px', boxShadow: '0 12px 40px rgba(0,0,0,.45)' }}
        customDropSquareStyle={{ boxShadow: 'inset 0 0 1px 4px rgba(245,165,36,.75)' }}
        animationDuration={160}
        areArrowsAllowed
      />
    </div>
  );
}
