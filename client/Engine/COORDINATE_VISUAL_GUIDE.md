# Xiangqi Board Coordinate System - Visual Guide

## Standard Board View (From Red's Perspective)

```
     Black Side
     =========

9  ┌─┬─┬─┬─┬─┬─┬─┬─┬─┐
   │r│n│b│a│k│a│b│n│r│  Black's back rank (generals start here)
8  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤
   │ │ │ │ │ │ │ │ │ │
7  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤
   │ │c│ │ │ │ │ │c│ │  Black cannons
6  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤
   │p│ │p│ │p│ │p│ │p│  Black pawns
5  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤  ═══════════
   │ │ │ │ │ │ │ │ │ │  River (上)
4  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤  River (下)
   │ │ │ │ │ │ │ │ │ │  ═══════════
3  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤
   │P│ │P│ │P│ │P│ │P│  Red pawns
2  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤
   │ │C│ │ │ │ │ │C│ │  Red cannons
1  ├─┼─┼─┼─┼─┼─┼─┼─┼─┤
   │ │ │ │ │ │ │ │ │ │
0  └─┴─┴─┴─┴─┴─┴─┴─┴─┘
   │R│N│B│A│K│A│B│N│R│  Red's back rank (generals start here)
   
   a b c d e f g h i     Files (9 columns)

     Red Side
     ========
```

## Palace Areas

```
Black Palace (Top):
9  . . . ┌─┬─┬─┐ . . .
       d │ │k│ │ f
8  . . . ├─┼─┼─┤ . . .
         │ │ │ │
7  . . . └─┴─┴─┘ . . .
         
       Palace squares: d9,e9,f9, d8,e8,f8, d7,e7,f7

Red Palace (Bottom):
2  . . . ┌─┬─┬─┐ . . .
       d │ │ │ │ f
1  . . . ├─┼─┼─┤ . . .
         │ │ │ │
0  . . . └─┴─┴─┘ . . .
         │ │K│ │
         
       Palace squares: d0,e0,f0, d1,e1,f1, d2,e2,f2
```

## Mailbox Representation (11x14 Array)

```
Index Layout:
════════════════════════════════════════════════════════

     0  1  2  3  4  5  6  7  8  9 10    ← File index
   ┌──────────────────────────────────┐
 0 │ x  x  x  x  x  x  x  x  x  x  x │  Border (offboard)
 1 │ x  x  x  x  x  x  x  x  x  x  x │  Border (offboard)
   ├──────────────────────────────────┤
 2 │ x a9 b9 c9 d9 e9 f9 g9 h9 i9  x │  Rank 9 (Black back)
 3 │ x a8 b8 c8 d8 e8 f8 g8 h8 i8  x │  Rank 8
 4 │ x a7 b7 c7 d7 e7 f7 g7 h7 i7  x │  Rank 7
 5 │ x a6 b6 c6 d6 e6 f6 g6 h6 i6  x │  Rank 6
 6 │ x a5 b5 c5 d5 e5 f5 g5 h5 i5  x │  Rank 5 (River)
 7 │ x a4 b4 c4 d4 e4 f4 g4 h4 i4  x │  Rank 4 (River)
 8 │ x a3 b3 c3 d3 e3 f3 g3 h3 i3  x │  Rank 3
 9 │ x a2 b2 c2 d2 e2 f2 g2 h2 i2  x │  Rank 2
10 │ x a1 b1 c1 d1 e1 f1 g1 h1 i1  x │  Rank 1
11 │ x a0 b0 c0 d0 e0 f0 g0 h0 i0  x │  Rank 0 (Red back)
   ├──────────────────────────────────┤
12 │ x  x  x  x  x  x  x  x  x  x  x │  Border (offboard)
13 │ x  x  x  x  x  x  x  x  x  x  x │  Border (offboard)
   └──────────────────────────────────┘
   ↑                                 ↑
Rank index                           

Formula: square_index = rank × 11 + file

Examples:
  e0 (Red king)   = 11 × 11 + 5 = 126
  e9 (Black king) =  2 × 11 + 5 = 27
  a0 (Red rook)   = 11 × 11 + 1 = 122
  i9 (Black rook) =  2 × 11 + 9 = 31
```

## Direction Offsets

```
Movement directions in mailbox:

       UP (-11)
          ↑
          │
LEFT (-1) ■ → RIGHT (+1)
          │
          ↓
      DOWN (+11)

Diagonals:
  UP-LEFT (-12)    UP-RIGHT (-10)
        ↖            ↗
           \        /
              ■
           /        \
        ↙            ↘
 DOWN-LEFT (+10)  DOWN-RIGHT (+12)
```

## Piece Movement Patterns

### Pawn (兵/卒)
```
Before crossing river:
   │
   ■    (Forward only)

After crossing river:
  ─ ■ ─  (Forward, Left, Right)
   │
```

### Advisor (仕/士)
```
Palace only, diagonal:
  \ ■ /
   \■/
    ■
   /■\
  / ■ \
```

### Bishop (相/象)
```
Two squares diagonal (no river crossing):
       ■
      / 
     ·    (Must not be blocked)
    /
   ■
```

### Knight (傌/馬)
```
L-shape, must not be blocked:
      ■
      
   ·  ■   (· = blocking point)
   
   ■
```

### Cannon (炮/炮)
```
Moves like Rook:
   │
───■───

Captures by jumping over one piece:
 x ○ ■  (○ = jump piece, x = capture)
```

### Rook (俥/車)
```
Orthogonal, any distance:
   │
───■───
   │
```

### King (帥/將)
```
Palace only, one square orthogonal:
   │
 ─ ■ ─
   │
```

## Square Numbering Reference

```
Quick lookup for common squares:

Black King:  e9 = index 27
Red King:    e0 = index 126

Black Rooks: a9 = 23,  i9 = 31
Red Rooks:   a0 = 122, i0 = 130

Center:      e5 = 71 (approx. board center)

River boundary: Ranks 5 and 4 (indices 67-75, 78-86)
```

## FEN String Format

```
rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1
└─────────────────────────────────────────────────────────┘ │ │ │ │ └─ Move number
                    Position                                │ │ │ └─── Halfmove clock
                                                            │ │ └───── Castling (N/A)
                                                            │ └─────── En passant (N/A)
                                                            └───────── Side to move (w/b)

Position breakdown:
  rnbakabnr  ← Black rank 9
  9          ← 9 empty squares (rank 8)
  1c5c1      ← 1 empty, cannon, 5 empty, cannon, 1 empty (rank 7)
  p1p1p1p1p  ← Black pawns (rank 6)
  9          ← 9 empty squares (rank 5)
  9          ← 9 empty squares (rank 4)
  P1P1P1P1P  ← Red pawns (rank 3)
  1C5C1      ← Red cannons (rank 2)
  9          ← 9 empty squares (rank 1)
  RNBAKABNR  ← Red rank 0
```

## Color-Coded Zones

```
Zone 0 (Offboard - X):  Border squares, movement not allowed
Zone 1 (Normal - ·):    Regular board squares
Zone 2 (Palace - P):    Special squares for King/Advisor

9  X X X X X X X X X X X
   X · · · P P P · · · X   Black palace
   X · · · P P P · · · X
   X · · · P P P · · · X
   X · · · · · · · · · X
   X · · · · · · · · · X   River
   X · · · · · · · · · X   River
   X · · · · · · · · · X
   X · · · P P P · · · X
   X · · · P P P · · · X   Red palace
   X · · · P P P · · · X
0  X X X X X X X X X X X
```

---

## Implementation Notes

### Accessing a Square
```rust
let square = board.squares[rank * 11 + file];
```

### Checking if Square is Valid
```rust
if board.squares[square] != OFFBOARD {
    // Square is valid
}
```

### Getting Coordinate String
```rust
let coord = COORDINATES[square];  // e.g., "e0"
```

### Moving in a Direction
```rust
let new_square = square + UP;     // Move up one rank
let new_square = square + RIGHT;  // Move right one file
```

This visual guide helps understand the board layout, coordinate system, and how pieces move in the Xiangqi engine implementation.
