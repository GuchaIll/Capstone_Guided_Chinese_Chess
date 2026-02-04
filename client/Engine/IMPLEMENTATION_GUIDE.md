# Xiangqi Engine Implementation Guide

## Overview
This is a Rust implementation of a Xiangqi (Chinese Chess) engine, using the [Wukong Xiangqi engine](https://github.com/maksimKorzh/wukong-xiangqi) as a reference.

## Implementation Progress

### ✅ Step 1: Project Setup
- Cargo workspace configuration
- Basic project structure
- Dependencies added (tokio, warp, serde for future WebSocket support)

### ✅ Step 2: Define Coordinate System for Board
**Status:** COMPLETE

**Implementation Details:**

#### Board Representation
- **Mailbox representation:** 11x14 array (154 squares total)
  - 9 files (a-i) × 10 ranks (0-9) = 90 playable squares
  - Border squares marked as OFFBOARD for efficient bounds checking
  - No need for explicit boundary checks in move generation

#### Coordinate System
- Files: a, b, c, d, e, f, g, h, i (9 files)
- Ranks: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 (10 ranks)
- Square notation: file + rank (e.g., "e0" for Red king, "e9" for Black king)
- Board layout (from Red's perspective):
  ```
  9  r n b a k a b n r  <- Black's back rank
  8  . . . . . . . . .
  7  . c . . . . . c .  <- Black cannons
  6  p . p . p . p . p  <- Black pawns
  5  . . . . . . . . .  <- River
  4  . . . . . . . . .  <- River
  3  P . P . P . P . P  <- Red pawns
  2  . C . . . . . C .  <- Red cannons
  1  . . . . . . . . .
  0  R N B A K A B N R  <- Red's back rank
     a b c d e f g h i
  ```

#### Piece Encoding
- **Empty:** 0
- **Red pieces:** 1-7
  - 1: Pawn (兵), 2: Advisor (仕), 3: Bishop (相), 4: Knight (傌)
  - 5: Cannon (炮), 6: Rook (俥), 7: King (帥)
- **Black pieces:** 8-14
  - 8: Pawn (卒), 9: Advisor (士), 10: Bishop (象), 11: Knight (馬)
  - 12: Cannon (炮), 13: Rook (車), 14: King (將)
- **Offboard:** 15

#### Board Zones
Two zone maps for movement restrictions:
- Zone 0: Offboard
- Zone 1: Normal squares
- Zone 2: Palace (3×3 area where Kings and Advisors can move)
  - Red palace: d0-f0, d1-f1, d2-f2
  - Black palace: d9-f9, d8-f8, d7-f7

#### FEN Support
- Standard Xiangqi FEN format
- Starting position: `rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1`
- Parser handles:
  - Piece placement
  - Side to move (w/b)
  - 60-move draw rule counter

#### Direction Offsets
For efficient move generation:
```rust
UP = -11, DOWN = 11, LEFT = -1, RIGHT = 1
ORTHOGONALS = [LEFT, RIGHT, UP, DOWN]
DIAGONALS = [UP+LEFT, UP+RIGHT, DOWN+LEFT, DOWN+RIGHT]
```

### 🔄 Step 3: Implement Rule Validation (NEXT)
**Status:** PENDING

Based on Wukong reference, this should include:

#### Move Generation
1. **Pawn (兵/卒) moves:**
   - Before crossing river: forward only
   - After crossing river: forward, left, right
   
2. **Advisor (仕/士) moves:**
   - Diagonal one square within palace
   
3. **Bishop (相/象) moves:**
   - Diagonal two squares (cannot cross river)
   - Cannot jump over pieces ("blocking eye")
   
4. **Knight (傌/馬) moves:**
   - L-shape: one square orthogonal + one square diagonal
   - Cannot jump over pieces ("hobbling leg")
   
5. **Cannon (炮/炮) moves:**
   - Moves like Rook
   - Captures by jumping over exactly one piece
   
6. **Rook (俥/車) moves:**
   - Any number of squares orthogonally
   - Cannot jump over pieces
   
7. **King (帥/將) moves:**
   - One square orthogonally within palace
   - Flying general rule: Kings cannot face each other

#### Attack Detection
- `isSquareAttacked(square, color)` function
- Used for:
  - Check detection
  - Move legality (can't leave king in check)
  - Flying general rule

#### Move Encoding
Compact move representation (24-bit):
```
0-7:   source square
8-15:  target square
16-19: source piece
20-23: target piece
24:    capture flag
```

### 🔄 Step 4: Game State Transitions and Turns
**Status:** PENDING

Will include:
- Make/unmake move
- Move stack for undo
- Game state management (check, checkmate, stalemate, draw)
- Turn management
- Move history
- Zobrist hashing for position repetition detection

### 🔄 Step 5: WebSocket Integration
**Status:** PENDING

Will include:
- WebSocket server setup with warp
- Real-time game state streaming
- Frontend React integration
- Move validation and response

### 🔄 Step 6: Unit Testing
**Status:** PARTIAL

Current tests:
- ✅ Board creation
- ✅ Coordinate mapping
- ✅ Offboard detection
- ✅ FEN parsing (starting position)
- ✅ Side operations

Needed tests:
- Move generation for each piece type
- Move validation
- Check/checkmate detection
- Game state transitions
- Edge cases (stalemate, draw conditions)

## Code Structure

```
client/Engine/src/
├── board.rs        # Board representation, FEN parsing, coordinate system
├── Game.rs         # Game logic (move generation, validation) - TBD
├── GameState.rs    # Game state management
├── State.rs        # State pattern implementation  - TBD
├── Util.rs         # Utility functions - TBD
├── main.rs         # Entry point, demo application
└── TODO.txt        # Implementation checklist
```

## Building and Running

```bash
# Build
cd client/Engine
cargo build

# Run
cargo run

# Test
cargo test

# Run with output
cargo test -- --nocapture
```

## Key Design Decisions

1. **Mailbox Board Representation:**
   - Chosen for simplicity and efficiency
   - Eliminates need for bounds checking
   - Direct square indexing with arithmetic

2. **Piece Encoding:**
   - Numeric encoding (0-15) for compact storage
   - Easy color detection: `piece >= 8` means Black
   - Easy type detection with lookup tables

3. **Following Wukong:**
   - Proven working engine
   - Well-structured code
   - Good balance of simplicity and efficiency

## Next Steps

1. **Implement Move Generation (Step 3):**
   - Start with simple pieces (King, Advisor)
   - Add complex pieces (Knight, Bishop)
   - Implement Rook and Cannon
   - Add Pawn with river crossing logic

2. **Implement Attack Detection:**
   - Required for move validation
   - Check if square is attacked by given side

3. **Add Move Validation:**
   - Legal move generation
   - Check detection
   - Filtering illegal moves

4. **Add Move Execution:**
   - Make move (update board, switch sides)
   - Unmake move (for search/validation)
   - Update zobrist hash
   - Track move history

## References

- [Wukong Xiangqi Engine](https://github.com/maksimKorzh/wukong-xiangqi)
- [Xiangqi Rules](https://www.ymimports.com/pages/how-to-play-xiangqi-chinese-chess)
- [Xiangqi on Wikipedia](https://en.wikipedia.org/wiki/Xiangqi)

## Notes for Future Implementation

### Move Generation Optimization
- Consider using bitboards for attack generation (optional)
- Pre-calculate attack tables for knights and bishops
- Implement MVV-LVA (Most Valuable Victim - Least Valuable Attacker) for move ordering

### Search Algorithm (Future)
- Alpha-beta pruning
- Iterative deepening
- Transposition table
- Quiescence search
- Null move pruning

### Evaluation (Future)
- Material counting
- Piece-square tables
- Mobility evaluation
- King safety
- Pawn structure
