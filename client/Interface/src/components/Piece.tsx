import { PieceType, PIECE_INFO } from '../types';
import './Piece.css';

interface PieceProps {
  piece: PieceType;
  draggable?: boolean;
  onDragStart?: () => void;
}

export default function Piece({ piece, draggable = false, onDragStart }: PieceProps) {
  const info = PIECE_INFO[piece];

  if (!info) return null;

  const handleDragStart = (e: React.DragEvent<HTMLDivElement>) => {
    if (!draggable) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', ''); // Required for Firefox
    onDragStart?.();
  };

  return (
    <div
      className={`piece ${info.color} ${draggable ? 'draggable' : ''}`}
      draggable={draggable}
      onDragStart={handleDragStart}
    >
      <span className="piece-char">{info.char}</span>
      <span className="piece-name">{info.name}</span>
    </div>
  );
}
