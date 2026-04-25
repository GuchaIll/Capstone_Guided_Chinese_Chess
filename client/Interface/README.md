# Chinese Chess (象棋) React Frontend

A React-based interactive Chinese Chess board interface with WebSocket support for real-time updates.

## Features

- **9×10 Grid Board**: Displays the Chinese Chess board with faint red grid lines for debugging
- **Piece Rendering**: Pieces displayed as circular tokens with Chinese character labels
- **Intersection-based Movement**: Pieces are positioned on grid intersections (not in squares)
- **Drag & Drop**: Click-to-select or drag-and-drop piece movement
- **Move Validation**: Basic client-side validation with server-authoritative validation via WebSocket
- **Real-time Updates**: WebSocket connection for syncing game state
- **Move History**: Visual move history panel
- **Turn Indicator**: Shows current player's turn

## Getting Started

### Install Dependencies
```bash
cd client/Interface
npm install
```

### Run Development Server
```bash
npm run dev
```

The app will be available at `http://localhost:3000`

## Use iPhone (Client) with Laptop Backend

### 1) Start the bridge and coaching server on the laptop
- State bridge should be reachable on `http://<laptop-ip>:5003` (gameplay WebSocket at `ws://<laptop-ip>:5003/ws`)
- Coaching server should be reachable on `http://<laptop-ip>:5000`

### 2) Run the React dev server on all interfaces
```bash
cd client/Interface
npm run dev -- --host 0.0.0.0 --port 3000
```

### 3) Open the app from your iPhone
1. Make sure the iPhone and laptop are on the same Wi-Fi network.
2. Find your laptop IP (Windows: `ipconfig`, look for IPv4 Address).
3. In Safari on the iPhone, open: `http://<laptop-ip>:3000`

### 4) (Optional) Override backend URLs
By default the client uses the current page hostname and the co-located `/bridge` proxy for gameplay plus port `5000` for coaching.
You can override via Vite env vars:
```bash
VITE_STATE_BRIDGE_BASE=http://<laptop-ip>:5003
VITE_COACH_URL=http://<laptop-ip>:5000
```

### Build for Production
```bash
npm run build
```

## Project Structure

```
src/
├── components/
│   ├── ChessBoard.tsx    # Main board component with grid rendering
│   ├── ChessBoard.css    # Board styling
│   ├── Piece.tsx         # Individual piece component
│   ├── Piece.css         # Piece styling (red/black circles)
│   ├── GameInfo.tsx      # Side panel with game info
│   └── GameInfo.css      # Info panel styling
├── hooks/
│   ├── useGameState.ts   # Game state management hook
│   └── useWebSocket.ts   # WebSocket connection hook
├── types/
│   └── index.ts          # TypeScript types and piece definitions
├── App.tsx               # Main application component
├── App.css               # App layout styling
├── main.tsx              # Entry point
└── index.css             # Global styles
```

## Gameplay Bridge Protocol

The frontend expects the state bridge WebSocket at `ws://localhost:5003/ws` with the following message format:

### Client → Server
```json
{ "type": "move", "move": "e2e4" }
{ "type": "reset" }
```

### Server → Client
```json
{ "type": "state", "fen": "rnbakabnr/9/..." }
{ "type": "move_result", "valid": true, "fen": "..." }
{ "type": "move_result", "valid": false, "reason": "Invalid move" }
{ "type": "error", "message": "..." }
```

## Coordinate System

- Files: `a` to `i` (left to right, 0-8)
- Ranks: `0` to `9` (bottom to top)
- Red starts at bottom (ranks 0-4)
- Black starts at top (ranks 5-9)
- Move notation: `{from}{to}` e.g., `h2e2` (cannon from h2 to e2)

## Piece Labels

| Red (红) | Black (黑) | English |
|----------|------------|---------|
| 帥 | 將 | General (King) |
| 仕 | 士 | Advisor |
| 相 | 象 | Elephant |
| 傌 | 馬 | Horse (Knight) |
| 俥 | 車 | Chariot (Rook) |
| 炮 | 砲 | Cannon |
| 兵 | 卒 | Soldier (Pawn) |
