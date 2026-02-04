# Chinese Chess (Xiangqi) Engine

A Rust implementation of a Xiangqi engine, using the [Wukong Xiangqi engine](https://github.com/maksimKorzh/wukong-xiangqi) as reference.

## Quick Start

```bash
# Build the engine
cargo build

# Run the demo
cargo run

# Run tests
cargo test
```

## Current Status: Step 2 Complete ✅

### Implemented Features

- ✅ **Board Representation** - 11×14 mailbox with 9×10 playable area
- ✅ **Piece Encoding** - Standard Xiangqi pieces (Red 1-7, Black 8-14)
- ✅ **Coordinate System** - Files a-i, Ranks 0-9
- ✅ **FEN Parsing** - Load positions from FEN strings
- ✅ **Board Display** - ASCII visualization with labels
- ✅ **Board Zones** - Palace and river restrictions
- ✅ **Unit Tests** - 5 tests covering core functionality

### Example Output

```
Starting position:

9  r n b a k a b n r 
8  . . . . . . . . . 
7  . c . . . . . c . 
6  p . p . p . p . p 
5  . . . . . . . . . 
4  . . . . . . . . . 
3  P . P . P . P . P 
2  . C . . . . . C . 
1  . . . . . . . . . 
0  R N B A K A B N R 
   a b c d e f g h i

   side:     Red
   sixty:    0
   kings:    [e0, e9]
```

## Next Steps (Step 3)

- Move generation for all piece types
- Attack detection
- Move validation (legal moves only)
- Check/checkmate detection

## Documentation

See [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md) for detailed documentation.

## File Structure

```
src/
├── board.rs       - Board representation, FEN parsing, display
├── Game.rs        - Game logic (to be expanded)
├── GameState.rs   - Game state management
├── main.rs        - Entry point and demo
├── State.rs       - State pattern (unused)
├── Util.rs        - Utilities (empty)
└── TODO.txt       - Implementation checklist
```

## Piece Notation

### Red Pieces (Uppercase)
- P: Pawn (兵)
- A: Advisor (仕)
- B/E: Bishop/Elephant (相)
- N/H: Knight/Horse (傌)
- C: Cannon (炮)
- R: Rook (俥)
- K: King (帥)

### Black Pieces (Lowercase)
- p: Pawn (卒)
- a: Advisor (士)
- b/e: Bishop/Elephant (象)
- n/h: Knight/Horse (馬)
- c: Cannon (炮)
- r: Rook (車)
- k: King (將)

## Testing

```bash
# Run all tests
cargo test

# Run tests with output
cargo test -- --nocapture

# Run specific test
cargo test test_starting_position
```

## Dependencies

- `tokio` - Async runtime (for future WebSocket support)
- `warp` - Web framework (for future WebSocket support)
- `serde` - Serialization (for future API)
- `serde_json` - JSON support (for future API)

## License

MIT

## References

- [Wukong Xiangqi Engine](https://github.com/maksimKorzh/wukong-xiangqi) - Reference implementation
- [Xiangqi Rules](https://www.ymimports.com/pages/how-to-play-xiangqi-chinese-chess)
- [Xiangqi on Wikipedia](https://en.wikipedia.org/wiki/Xiangqi)
