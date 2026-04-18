# Revised Design Presentation: Chinese Chess Guided Learning

I've revised the presentation based on your feedback, with expanded chess engine and LLM orchestration sections. For each diagram, I've included the draw.io prompts you can use.

---

## P1: Title Slide

### Chinese Chess Guided Learning
**Team [Number] | Section [A/B]**

**Team Members:**
- Charlie Ai (yacil)
- Claire Lee (clairele)
- Yoyo Zhong (ziyanzho)

**Presenter:** [Name]

**Key Features:**
- 🎯 Real-time LED move guidance on physical board
- 🗣️ Voice-controlled hands-free interaction
- 🤖 Xiangqi-GPT: Unified move + explanation model
- 📷 Computer vision board state detection
- 🎓 Adaptive guidance: Full → Assistive → Challenge modes

---

## P2: Use Case & Design Requirements

### Evolution Since Proposal

| Original Plan         | Updated Design      | Why Changed                              |
| --------------------- | ------------------- | ---------------------------------------- |
| Separate engine + LLM | Unified Xiangqi-GPT | Simpler architecture, better coherence   |
| ESP32 LED driver      | Raspberry Pi        | Better library support, debugging        |
| Generic LLM prompting | Fine-tuned + RAG    | Tested Gemini—poor Xiangqi understanding |

### Requirements Mapping

| Use Case Requirement      | Design Requirement  | Justification                       |     |
| ------------------------- | ------------------- | ----------------------------------- | --- |
| Feedback feels responsive | Voice latency ≤1.5s | Human conversation threshold        |     |
| Board updates real-time   | CV detection ≤500ms | Below perception threshold          |     |
| Move validation instant   | Rule check ≤100ms   | Human reaction time ~200ms          |     |
| Explanations helpful      | LLM ≤2.5s           | Acceptable wait for quality content |     |

### Cultural & Social Considerations
- **Cultural preservation**: Maintains traditional tactile Xiangqi experience
- **Accessibility**: Low cost (~$200) enables broad access
- **Educational**: Lowers barrier to cultural heritage game

---

## P3: Board Layout & Manufacturing

### Physical Design

**Draw.io Prompt:**
```
Create a technical diagram of a Chinese Chess (Xiangqi) board layout showing:
1. A 9x10 grid of intersection points (90 total)
2. Each intersection has a 5mm LED hole
3. The "river" dividing the board in the middle
4. Palace regions (3x3) on each side
5. Dimensions: 45cm x 50cm
6. Material layers: top acrylic (3mm), LED mounting layer, base
7. Show cross-section view on the side
Use engineering drawing style with measurements labeled.
```

### Manufacturing Status

| Component | Method | Status | Evidence |
| --------- | ------ | ------ | -------- |
| Board surface | Laser cutting | ✅ CAD complete | [Show screenshot] |
| LED holes | 5mm drill template | ✅ Ready | [Show template] |
| Housing frame | 3D print | 🔄 In progress | [Show CAD] |

---

## P4: Board State Detection & Trade-offs

### CV Pipeline Architecture

**Draw.io Prompt:**
```
Create a flowchart for computer vision board state detection:
1. Start: Camera captures image
2. Preprocessing: Perspective correction, noise reduction
3. Grid Detection: Hough transform finds 9x10 intersections
4. Piece Segmentation: Extract 90 regions of interest
5. Character Recognition: CNN classifies Chinese characters (14 classes: 7 piece types x 2 colors + empty)
6. Decision: Confidence > 95%?
   - Yes: Output FEN string
   - No: Request recapture or manual correction
7. Send to Rust validator
Include timing annotations: preprocessing 50ms, grid 100ms, segmentation 150ms, OCR 200ms
```

### Trade-off Analysis

| Approach | Accuracy | Cost | Complexity | Decision |
| -------- | -------- | ---- | ---------- | -------- |
| **Overhead CV** | 95%+ | $0-50 | Medium | ✅ Primary |
| Hall Effect Array | 99%+ | $200+ | High (PCB) | Stretch goal |
| RFID Tags | 98%+ | $100+ | Medium | ❌ Modifies pieces |

**Why CV as Primary:**
- Uses phone camera (no additional hardware)
- Works with standard Xiangqi pieces
- Sufficient accuracy for guided learning
- Hall effect remains stretch goal for competition-grade reliability

---

## P5: Circuit Block Diagram & LED System

### System Architecture

**Draw.io Prompt:**
```
Create a system architecture diagram with these components and connections:

Top Layer (User Interface):
- React PWA on Phone (displays board, explanations, controls)

Middle Layer (Compute):
- Rust Engine Server (game logic, validation)
- Python Flask Server (CV, LLM, LED control)
- Xiangqi-GPT Model (move generation, explanations)

Bottom Layer (Hardware):
- Raspberry Pi 4 (LED driver)
- SK6812 LED Strip (90 addressable LEDs)
- Camera (phone or USB)

Connections:
- Phone <-> Rust: WebSocket (real-time), HTTP (commands)
- Rust <-> Python: HTTP REST API
- Python <-> Pi: HTTP (LED commands)
- Phone -> Python: Camera stream
- Pi -> LEDs: GPIO data line

Label each connection with protocol and data type (JSON, image stream, etc.)
Use color coding: blue for data flow, green for control signals, orange for hardware.
```

### LED Wiring Detail

```
Power Supply (5V 10A) ──┬──► Raspberry Pi 4
                        │
                        └──► SK6812 Strip (90 LEDs)
                               │
GPIO 18 ──► Level Shifter ─────┘
            (3.3V → 5V)

LED Indexing: LED[i] = file + (rank × 9)
Example: Position c5 = 2 + (5 × 9) = LED[47]
```

---

## P6: Guided Lighting Configuration

### Color Semantics by Game Mode

**Draw.io Prompt:**
```
Create a comparison diagram showing LED color usage across three game modes:

Three columns: Full Guidance | Assistive | Challenge

Row 1 - Selected Piece:
- Full: Green (always shown)
- Assistive: Green (on request)
- Challenge: None

Row 2 - Legal Moves:
- Full: Yellow (all shown automatically)
- Assistive: Yellow (on request only)
- Challenge: None

Row 3 - Best Move:
- Full: Red (highlighted)
- Assistive: Red (on request)
- Challenge: None

Row 4 - Last Opponent Move:
- Full: Blue
- Assistive: Blue
- Challenge: Blue (only feedback)

Row 5 - Piece Under Threat:
- Full: White pulsing (automatic warning)
- Assistive: White pulsing (automatic warning)
- Challenge: None

Include a legend showing RGB values for each color.
```

### Blunder Warning System

When player is about to make a bad move (detected via CV seeing piece lifted):

| Situation | LED Response | Voice/UI Response |
| --------- | ------------ | ----------------- |
| Piece lifted, bad move likely | Destination pulses white | "Consider your options" |
| Hanging piece detected | Threatened piece pulses red | "Your [piece] is undefended" |
| Better move available (>2 pawns) | Best destination pulses green | "There may be a stronger move" |

---

## P7: Chess Engine - Classical + ML Hybrid

### Dual Approach Architecture

**Draw.io Prompt:**
```
Create a flowchart showing the hybrid chess engine with two parallel paths:

START: Board Position (FEN)

Path A - Classical Engine (Rust):
1. Move Generation: Enumerate all legal moves
2. Move Ordering: MVV-LVA, killer heuristic
3. Negamax Search: α-β pruning, depth 6
4. Position Evaluation: Material + PST + King Safety
5. Output: Best move + evaluation score

Path B - Xiangqi-GPT (Python):
1. Encode Position: FEN → token sequence
2. Add Task Token: <|predict_move|>
3. Constrained Decoding: Legal move mask from Path A
4. Output: Move + confidence

MERGE: Validator
- Compare outputs
- Select based on confidence
- Guarantee legal move

Path to LLM Orchestration:
- Pass position + analysis to explanation graph

Include timing annotations: Classical ~500ms, Xiangqi-GPT ~1s
```

### Classical Engine: Negamax with Alpha-Beta

```
function negamax(position, depth, α, β):
    if depth == 0 or game_over:
        return evaluate(position)
    
    for move in ordered_moves(position):
        score = -negamax(make_move(position, move), depth-1, -β, -α)
        α = max(α, score)
        if α >= β:
            break  // Pruning
    return α

Evaluation Function:
  Score = Σ (piece_value × count) 
        + Σ (piece_square_table[piece][square])
        + king_safety_bonus
        + mobility_bonus
```

### Xiangqi-GPT: LoRA Fine-tuning on Qwen2-7B

**Why Qwen2-7B:**
- Native Chinese tokenization (炮, 馬, 車 as single tokens)
- 3x fewer tokens than Llama for Chinese text
- Apache 2.0 license (allows fine-tuning + deployment)
- Strong reasoning for board understanding

**Training Data Requirements:**

| Task | Examples | Source |
| ---- | -------- | ------ |
| Move prediction | 500K-1M | DPXQ game database |
| Position explanation | 20K | Synthetic + annotations |
| Move feedback | 15K | Engine + templates |
| Opening commentary | 5K | Xiangqi books |

**Constrained Decoding (Guarantees Legal Moves):**
```python
def generate_move(position, model, rust_engine):
    legal_moves = rust_engine.get_legal_moves(position)
    legal_tokens = [tokenize(m) for m in legal_moves]
    
    # Mask all tokens except legal move starts
    logits = model.forward(position)
    masked_logits = apply_legal_mask(logits, legal_tokens)
    
    return decode(masked_logits)  # Always legal!
```

---

## P8: LLM Agent Orchestration (Expanded)

### LangGraph State Machine

**Draw.io Prompt:**
```
Create a state machine diagram for LLM orchestration with these nodes and transitions:

ENTRY POINT: User Input (voice/text/move)

NODE 1: Intent Router
- Conditions: move_request, explain_request, question, player_moved
- Routes to appropriate handler

NODE 2: Position Analyzer
- Inputs: current FEN, move history
- Outputs: threats, hanging pieces, tactical patterns
- Calls: Rust engine for analysis

NODE 3: RAG Retriever
- Inputs: position features, game phase
- Queries: Vector DB (openings, tactics, endgames)
- Outputs: relevant context documents

NODE 4: Game Phase Detector
- Conditions: opening (moves < 15), middlegame, endgame
- Affects: which RAG collection to query

NODE 5: Blunder Detector
- Inputs: player's intended move, engine best move
- Condition: eval_loss > 200 centipawns?
- Yes → Warning Node
- No → Continue

NODE 6: Warning Generator
- Outputs: warning message, alternative suggestions
- Triggers: LED warning animation

NODE 7: Puzzle Generator (Full Guidance Mode)
- Condition: Tactical pattern detected?
- Yes → Convert to puzzle, hide best move, ask player
- No → Provide direct guidance

NODE 8: Explanation Generator
- Inputs: position, analysis, RAG context, game mode
- Adjusts: verbosity based on mode
- Outputs: natural language explanation

NODE 9: Response Formatter
- Adapts output for: voice TTS, UI display, LED commands

GAME MODE AFFECTS:
- Full Guidance: All nodes active, proactive warnings
- Assistive: Nodes activate on request only
- Challenge: Only Position Analyzer + minimal feedback

Draw with swimlanes for each game mode showing which nodes are active.
```

### RAG Content Collections

**Draw.io Prompt:**
```
Create a diagram showing RAG vector database structure:

Database: ChromaDB

Collection 1: Openings
- Documents: 50+ named openings
- Metadata: {name, first_moves, key_ideas, common_responses}
- Example: "Central Cannon" - "C2-C5 on move 1, controls center..."
- Triggers: Game phase = opening, cannon moved to center

Collection 2: Tactical Patterns
- Documents: 30+ patterns
- Metadata: {pattern_type, piece_involved, setup_conditions}
- Examples: Double Cannon Checkmate, Horse Fork, Chariot Pin
- Triggers: Pattern detected in position analysis

Collection 3: Endgame Techniques
- Documents: 20+ endgame types
- Metadata: {material_balance, winning_side, key_squares}
- Examples: Chariot vs Cannon, Cannon + Pawn endings
- Triggers: Game phase = endgame, few pieces remaining

Collection 4: Beginner Principles
- Documents: General advice
- Metadata: {topic, difficulty_level}
- Examples: "Develop chariots early", "Protect your king"
- Triggers: Full guidance mode, common beginner mistakes

Embedding Model: BAAI/bge-m3 (multilingual Chinese+English)

Show retrieval flow: Position → Feature Extraction → Query → Top-3 Documents → Inject into Prompt
```

### Game Mode Behavior Matrix

| Node | Full Guidance | Assistive | Challenge |
| ---- | ------------- | --------- | --------- |
| Intent Router | ✅ Auto-trigger | ✅ On request | ✅ Minimal |
| Position Analyzer | ✅ Every move | ✅ Every move | ✅ Every move |
| RAG Retriever | ✅ Auto | ✅ On request | ❌ Off |
| Blunder Detector | ✅ Proactive warn | ✅ Proactive warn | ❌ Off |
| Puzzle Generator | ✅ Active | ❌ Off | ❌ Off |
| Explanation Generator | ✅ Verbose | ✅ Concise | ❌ Off |
| LED Guidance | ✅ Full colors | ✅ On request | ❌ Last move only |

### Opening Learning Flow

**Draw.io Prompt:**
```
Create a sequence diagram for opening learning in Full Guidance mode:

Actor: Player
System: Xiangqi-GPT System

1. Player makes move (e.g., C2-C5)
2. System: Position Analyzer detects opening move
3. System: Game Phase Detector → "opening"
4. System: RAG Retriever queries Openings collection
   - Retrieves: "Central Cannon Opening (当头炮)"
5. System: Checks if move matches known opening
   - Yes: Retrieve opening context
6. System: Explanation Generator creates response:
   "Great choice! You've played the Central Cannon opening (当头炮).
    This is the most popular opening in Xiangqi because:
    - It controls the center file
    - It threatens Black's king directly
    - It prepares for attacking formations
    
    Black will likely respond with Screen Horse (屏风马) or
    Counter-Central Cannon (顺炮). Watch for these patterns!"
7. System: LED highlights common response squares
8. Player makes next move
9. System: If deviates from book → "This is a less common continuation..."
   If follows book → "Continuing the main line..."
```

### Puzzle Mode Flow (Tactical Training)

**Draw.io Prompt:**
```
Create a flowchart for puzzle generation during gameplay:

START: Position after opponent's move

1. Position Analyzer runs
2. Tactical Pattern Detector checks:
   - Fork opportunity?
   - Pin available?
   - Checkmate in N?
   - Winning exchange?

3. IF strong tactic found (eval gain > 300cp):
   a. Puzzle Generator activates
   b. Hide the best move from LED display
   c. Generate puzzle prompt:
      "There's a strong move here! Can you find it?"
   d. Wait for player's move
   e. IF player finds it:
      - "Excellent! You found the [tactic type]!"
      - Explain why it works
   f. IF player misses it:
      - "Good try, but there was something stronger."
      - Reveal the tactic with explanation
      - Option to undo and try again

4. ELSE (no strong tactic):
   - Continue normal guidance flow

5. Track puzzle success rate for adaptive difficulty
```

### Blunder Prevention Flow

**Draw.io Prompt:**
```
Create a decision tree for blunder prevention:

TRIGGER: CV detects player lifting a piece

1. Predict likely destination squares (based on piece type)

2. For each possible move:
   a. Evaluate with engine
   b. Compare to best move

3. IF any likely move loses > 200 centipawns:
   
   IMMEDIATE (while piece is lifted):
   - Pulse destination square white (warning)
   - If in Full/Assistive mode:
     - Voice: "Consider your options carefully"
   
   IF player places piece on bad square:
   - Pulse placed position red
   - "That move may not be optimal."
   - Show eval change: "Position went from +1.5 to -0.5"
   - "Would you like to see alternatives?" (Assistive)
   - Auto-show alternatives (Full Guidance)
   - No comment (Challenge)
   
   ALTERNATIVES SHOWN:
   - Best move in green
   - Other good moves in yellow
   - Explain why current move is problematic:
     - "Your Cannon is now undefended"
     - "This allows a Horse fork on e6"
     - "You missed checkmate in 2"

4. IF move is acceptable (within 100cp):
   - Normal flow, no warning

5. Log for later review:
   - "In this game, you made 3 inaccuracies. 
      Review positions 12, 24, 31."
```

---

## P9: System Deployment Architecture

### Deployment Diagram

**Draw.io Prompt:**
```
Create a deployment diagram with three tiers:

TIER 1 - User Device (Phone):
┌─────────────────────────────────────────┐
│  React Progressive Web App              │
│  ├── Board visualization                │
│  ├── Move history panel                 │
│  ├── Explanation display                │
│  ├── Voice input (Web Speech API)       │
│  └── Camera access (MediaDevices API)   │
└─────────────────────────────────────────┘
     │ WebSocket        │ HTTP/Camera
     ▼                  ▼

TIER 2 - Compute Server (Laptop):
┌─────────────────────────────────────────┐
│  Rust Engine Server (Port 8080)         │
│  ├── Game state management              │
│  ├── Move validation                    │
│  ├── Legal move generation              │
│  └── WebSocket handler                  │
├─────────────────────────────────────────┤
│  Python Flask Server (Port 5000)        │
│  ├── CV Processing module               │
│  ├── Xiangqi-GPT inference              │
│  ├── LangGraph orchestration            │
│  ├── RAG retrieval (ChromaDB)           │
│  └── LED command generator              │
└─────────────────────────────────────────┘
     │ HTTP (JSON)
     ▼

TIER 3 - Hardware Layer:
┌─────────────────────────────────────────┐
│  Raspberry Pi 4 (LED Controller)        │
│  ├── HTTP server (Port 8000)            │
│  ├── rpi_ws281x driver                  │
│  └── LED animation engine               │
├─────────────────────────────────────────┤
│  SK6812 LED Strip                       │
│  └── 90 addressable RGB+W LEDs          │
└─────────────────────────────────────────┘

Show network: All on same WiFi network
Data formats: JSON for all APIs
```

### Component Source Matrix

| Component | Type | Source |
| --------- | ---- | ------ |
| Rust Xiangqi engine | **Design from scratch** | Custom implementation |
| Xiangqi-GPT model | **Design + train** | LoRA fine-tune Qwen2-7B |
| LangGraph orchestration | **Design** | Custom state machine |
| RAG knowledge base | **Curate** | Compile from Xiangqi sources |
| CV pipeline | **Adapt** | OpenCV + custom OCR model |
| React frontend | **Assemble** | Standard React + custom UI |
| LED driver code | **Adapt** | rpi_ws281x + custom mapping |
| Hardware | **Buy** | Pi, LEDs, power supply |

---

## P10: System Interaction Flows

### Complete Move Cycle Sequence

**Draw.io Prompt:**
```
Create a detailed sequence diagram with these actors and messages:

Actors (left to right):
Player | Phone UI | Rust Engine | Python Server | LangGraph | Xiangqi-GPT | RAG DB | Raspberry Pi | LEDs

Sequence - Player Makes Move:

1. Player lifts piece
2. Phone UI: Camera detects motion
3. Phone UI → Python: Stream frame
4. Python: CV processes, detects lifted piece
5. Python → Rust: GET /legal_moves?piece=cannon&from=c2
6. Rust → Python: [c5, c6, c7, c3, c1, ...]
7. Python → Pi: POST /leds {highlight legal moves yellow}
8. Pi → LEDs: Update
9. LEDs: Yellow lights appear

10. Player places piece
11. Phone UI → Python: Stream frame
12. Python: CV detects new position
13. Python → Rust: POST /move {from: c2, to: c5}
14. Rust: Validate move (legal)
15. Rust: Update game state
16. Rust → Python: {valid: true, new_fen: "..."}

17. Python → LangGraph: Process move
18. LangGraph → Position Analyzer: Analyze
19. Position Analyzer → Rust: GET /evaluate
20. Rust → Position Analyzer: {eval: +1.2, threats: [...]}
21. LangGraph → RAG: Query openings
22. RAG → LangGraph: "Central Cannon Opening..."
23. LangGraph → Xiangqi-GPT: Generate explanation
24. Xiangqi-GPT → LangGraph: "Great move! The Central Cannon..."
25. LangGraph → Python: {explanation, led_commands}

26. Python → Phone UI: WebSocket {explanation}
27. Phone UI: Display + TTS
28. Python → Pi: POST /leds {clear yellow, show blue for move}
29. Pi → LEDs: Update

Total time annotations: ~2s for full cycle
```

### Blunder Warning Sequence

**Draw.io Prompt:**
```
Create a sequence diagram for blunder prevention:

Actors: Player | CV | Rust | LangGraph | Blunder Detector | Pi | LEDs | UI

1. Player lifts piece (Chariot from a1)
2. CV detects piece lifted, sends to analysis
3. CV → Rust: Piece lifted from a1, predict destinations
4. Rust: Generate move candidates [a2, a3, ..., a10, b1, c1, ...]
5. Rust: Evaluate each candidate quickly (depth 4)
6. Rust: Finds a1-a5 loses queen to fork!
7. Rust → LangGraph: {warning: true, bad_moves: [a5], reason: "fork"}

8. LangGraph → Blunder Detector: Activate
9. Blunder Detector: Severity = HIGH (loses major piece)
10. Blunder Detector → Pi: Flash a5 white (warning)
11. Pi → LEDs: a5 pulsing white
12. Blunder Detector → UI: "Be careful with this move"

13. BRANCH A - Player heeds warning:
    13a. Player places on a3 instead
    13b. Normal flow continues
    
14. BRANCH B - Player ignores warning:
    14a. Player places on a5 (bad move)
    14b. CV → Rust: Move a1-a5 made
    14c. Rust: Validate (legal but bad)
    14d. LangGraph: Generate feedback
    14e. UI: "Your Chariot is now in danger. 
             Black can play H3-E5 forking your Chariot and Cannon."
    14f. UI: "Would you like to take back this move?" (Full Guidance only)
```

---

## P11: Testing & Verification Plan

### Test Matrix with Specific Inputs/Outputs

| Requirement | Test Input | Expected Output | Pass Criteria |
| ----------- | ---------- | --------------- | ------------- |
| Rule validation ≤100ms | 1000 random FEN + random move | Legal/Illegal + time | 100% correct, 99% <100ms |
| CV accuracy ≥95% | 100 board photos, varied lighting | Detected FEN | ≥95 positions correct |
| LED latency ≤1s | Voice command "show moves" | LEDs illuminate | <1s from command end |
| LLM latency ≤2.5s | 50 explanation requests | Text response | Mean <2.5s, max <4s |
| Blunder detection | 20 positions with tactical blunders | Warning triggered | ≥90% blunders caught |
| Opening recognition | 10 known openings played | Correct identification | 100% recognized |

### Risk Mitigation

| Risk | If Occurs... | Mitigation |
| ---- | ------------ | ---------- |
| Xiangqi-GPT suggests weak move | Falls through to validator | Rust engine provides backup |
| CV fails in lighting | Board state unknown | Manual correction UI; controlled lighting setup |
| LLM latency exceeds target | Poor UX | Pre-compute common explanations; use templates |
| RAG returns irrelevant context | Confusing explanations | Filter by confidence; fallback to base prompt |

---

## P12: Project Management & Conclusion

### Gantt Chart

**Draw.io Prompt:**
```
Create a Gantt chart for weeks 6-15 with these tasks and assignments:

Tasks (rows):
1. Board manufacturing (Yoyo) - W6-W7
2. LED wiring + testing (Claire) - W6-W8
3. Rust engine core (Charlie) - W6-W8
4. CV pipeline (Yoyo) - W6-W9
5. Training data collection (Charlie) - W7-W8
6. Xiangqi-GPT fine-tuning (Charlie) - W8-W9
7. RAG knowledge base (Charlie) - W8-W9
8. LangGraph orchestration (Charlie) - W9-W10
9. React frontend (Charlie) - W7-W10
10. System integration (All) - W9-W11
11. Testing + debugging (All) - W10-W12
12. User testing (Claire) - W11-W13
13. Documentation (All) - W12-W14
14. Final demo prep (All) - W13-W14

Milestones (diamonds):
- W7: Hardware MVP (LEDs work)
- W9: Software MVP (engine + CV work)
- W11: Integration complete
- W14: Demo ready

Color code by team member: Charlie=blue, Claire=green, Yoyo=orange
Show parallel tracks clearly
```

### Key Design Decisions Seeking Feedback

1. **Hybrid Engine Strategy**: Is Classical + Xiangqi-GPT with Rust validator appropriate for reliability?

2. **Blunder Warning UX**: Should warnings be proactive (while piece lifted) or reactive (after move)?

3. **Puzzle Integration**: Is pausing gameplay for puzzles disruptive or valuable for learning?

4. **Data Requirements**: Is 500K game positions + 40K explanations achievable and sufficient?

### Success Criteria

| Metric | Target | Measurement |
| ------ | ------ | ----------- |
| Beginner learning effectiveness | Complete game with ≤3 rule errors | User study |
| Explanation quality | User rating ≥4/5 | Post-game survey |
| System responsiveness | 95% responses within latency targets | Automated logging |
| Move accuracy | ≥90% moves rated "good" or better | Engine analysis |

### Bill of Materials

| Item | Qty | Cost | Source |
| ---- | --- | ---- | ------ |
| SK6812 LED Strip (1m, 60/m) | 2 | $30 | Amazon |
| Raspberry Pi 4 (4GB) | 1 | $55 | Adafruit |
| 5V 10A Power Supply | 1 | $20 | Amazon |
| Level Shifter | 2 | $10 | Digikey |
| Acrylic sheets | 2 | $30 | CMU Maker |
| Xiangqi pieces | 1 | $15 | Amazon |
| Misc (wires, connectors) | - | $40 | Various |
| **Total** | | **$200** | |

---

## Summary of Draw.io Prompts

For easy reference, here are all the diagram prompts:

### P3 - Board Layout
```
Create a technical diagram of a Chinese Chess (Xiangqi) board layout showing: 1. A 9x10 grid of intersection points (90 total) 2. Each intersection has a 5mm LED hole 3. The "river" dividing the board in the middle 4. Palace regions (3x3) on each side 5. Dimensions: 45cm x 50cm 6. Material layers: top acrylic (3mm), LED mounting layer, base 7. Show cross-section view on the side. Use engineering drawing style with measurements labeled.
```

### P4 - CV Pipeline
```
Create a flowchart for computer vision board state detection: 1. Start: Camera captures image 2. Preprocessing: Perspective correction, noise reduction 3. Grid Detection: Hough transform finds 9x10 intersections 4. Piece Segmentation: Extract 90 regions of interest 5. Character Recognition: CNN classifies Chinese characters 6. Decision diamond: Confidence > 95%? Yes outputs FEN, No requests recapture 7. Send to Rust validator. Include timing annotations for each step.
```

### P5 - System Architecture
```
Create a system architecture diagram with three layers: Top (React PWA on Phone), Middle (Rust Engine Server and Python Flask Server with Xiangqi-GPT), Bottom (Raspberry Pi and SK6812 LEDs). Show WebSocket and HTTP connections between components. Label each connection with protocol and data format. Use color coding: blue for data, green for control, orange for hardware.
```

### P6 - LED Color Matrix
```
Create a comparison table diagram showing LED color usage across three game modes (Full Guidance, Assistive, Challenge). Rows: Selected Piece, Legal Moves, Best Move, Last Move, Threat Warning. Show which colors appear in which modes with checkmarks or X marks. Include RGB values in legend.
```

### P7 - Hybrid Engine
```
Create a flowchart showing hybrid chess engine with two parallel paths from Board Position input: Path A (Classical): Move Generation → Move Ordering → Negamax Search → Evaluation → Output. Path B (Xiangqi-GPT): Encode Position → Add Task Token → Constrained Decoding → Output. Both merge at Validator node. Include timing annotations.
```

### P8 - LangGraph State Machine
```
Create a state machine diagram with nodes: Intent Router, Position Analyzer, RAG Retriever, Game Phase Detector, Blunder Detector, Warning Generator, Puzzle Generator, Explanation Generator, Response Formatter. Show transitions between nodes with conditions. Use swimlanes to show which nodes are active in Full Guidance, Assistive, and Challenge modes.
```

### P8 - RAG Collections
```
Create a diagram showing RAG vector database with four collections: Openings (50+ docs), Tactical Patterns (30+ docs), Endgame Techniques (20+ docs), Beginner Principles. Show metadata fields and trigger conditions for each. Include retrieval flow: Position → Features → Query → Top-3 Docs → Prompt.
```

### P10 - Move Cycle Sequence
```
Create a sequence diagram with actors: Player, Phone UI, Rust Engine, Python Server, LangGraph, Xiangqi-GPT, RAG, Raspberry Pi, LEDs. Show complete flow from player lifting piece through explanation delivery. Number each message. Include timing annotations.
```

### P10 - Blunder Warning Sequence
```
Create a sequence diagram showing blunder prevention: Player lifts piece → CV detects → Rust evaluates candidates → Finds bad move → LangGraph activates Blunder Detector → Pi flashes warning LED → Two branches: Player heeds warning OR ignores and gets feedback. Show timing and decision points.
```

### P12 - Gantt Chart
```
Create a Gantt chart for weeks 6-15 with 14 tasks: Board manufacturing, LED wiring, Rust engine, CV pipeline, Training data, Xiangqi-GPT fine-tuning, RAG knowledge base, LangGraph, React frontend, Integration, Testing, User testing, Documentation, Demo prep. Assign to Charlie (blue), Claire (green), Yoyo (orange). Show milestones at W7, W9, W11, W14.
```

---

Would you like me to expand on any section or create additional diagrams for specific components?