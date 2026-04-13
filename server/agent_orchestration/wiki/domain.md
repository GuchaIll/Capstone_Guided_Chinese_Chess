# Core business domain concepts, processes, etc.

# Domain Knowledge - Xiangqi (Chinese Chess)
# =============================================

## Piece Types and Values

| Piece     | Chinese | Symbol | Value | Movement |
|-----------|---------|--------|-------|----------|
| King      | 帥/將   | K      | -     | 1 step orthogonal, palace only |
| Advisor   | 仕/士   | A      | ~2    | 1 step diagonal, palace only |
| Elephant  | 相/象   | E      | ~2    | 2 steps diagonal, same side of river, blockable |
| Horse     | 馬/馬   | H      | ~4    | L-shape (1+1 diagonal), leg blockable |
| Rook      | 車/車   | R      | ~9    | Any distance orthogonal |
| Cannon    | 炮/砲   | C      | ~4.5  | Moves like rook, captures by jumping 1 screen piece |
| Pawn      | 兵/卒   | P      | ~1-2  | 1 step forward; sideways after crossing river |

## Board Layout
- 9 columns (a-i) x 10 rows (0-9)
- Pieces move on intersections (90 points)
- Palace: 3x3 area at each end (d0-f2 for red, d7-f9 for black)
- River: divides the board between rows 4 and 5

## Special Rules
- **Flying General**: Kings cannot face each other on the same file with no pieces between
- **Perpetual Chase**: Forbidden - player chasing must change moves or accept draw
- **Perpetual Check**: Forbidden - checking side must stop or lose
- **Stalemate**: The stalemated side LOSES (unlike Western chess)
- **60-move Rule**: Draw if 60 moves without capture or pawn advance

## Game Phases
- **Opening**: First 10-15 moves, develop pieces, control center
- **Middlegame**: Tactical battles, piece exchanges
- **Endgame**: Reduced material, focus on checkmate or promotion (pawns crossing river)

## Common Tactical Patterns
- **Double Cannon**: Two cannons on same file/rank with screen between them
- **Rook-Cannon Battery**: Rook behind cannon for powerful attack
- **Horse Fork**: Knight attacks two pieces simultaneously
- **Smothered Mate**: Horse delivers mate in confined palace
- **Cannon Pin**: Cannon pins piece to king through a screen

## Common Openings
- **Central Cannon (Zhong Pao)**: Most popular, cannon to center file
- **Screen Horse Defense (Ping Feng Ma)**: Both horses defend center
- **Same-Direction Cannon**: Both sides place cannon on same file
- **Opposite-Direction Cannon**: Cannons on opposing files
