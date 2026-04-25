"""Quick smoke test for all services."""
import asyncio
import json
import urllib.request

# ── helpers ──────────────────────────────────────────────────────────
def http(method, url, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        return 0, str(e)

def check(label, code, body, expect_code=200):
    status = "PASS" if code == expect_code else "FAIL"
    print(f"  [{status}] {label}  ({code})")
    if status == "FAIL":
        print(f"         body: {body}")
    return status == "PASS"

# ── 1. State Bridge ──────────────────────────────────────────────────
print("\n=== 1. State Bridge (port 5003) ===")
code, body = http("GET", "http://localhost:5003/health")
check("1.1.1 Health", code, body)

code, body = http("GET", "http://localhost:5003/state")
ok = check("1.1.2 State snapshot", code, body)
if ok:
    stm = body.get("side_to_move", "?")
    check(f"1.6.1 side_to_move is 'red' (got '{stm}')", 200 if stm == "red" else 0, body)

code, body = http("POST", "http://localhost:5003/state/fen",
                   {"fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"})
check("1.2.1 Engine FEN update", code, body)

code, body = http("POST", "http://localhost:5003/state/fen",
                   {"fen": "test_cv_fen", "source": "cv"})
check("1.2.2 CV FEN update", code, body)

code, body = http("GET", "http://localhost:5003/state")
cv_fen = body.get("cv_fen", "?") if isinstance(body, dict) else "?"
check(f"1.2.3 CV FEN stored (got '{cv_fen}')", 200 if cv_fen == "test_cv_fen" else 0, body)

code, body = http("POST", "http://localhost:5003/state/best-move",
                   {"from_sq": "e3", "to_sq": "e4"})
check("1.3 Best-move", code, body)

code, body = http("POST", "http://localhost:5003/state/led-command",
                   {"command": "off"})
check("1.4 LED command", code, body)

code, body = http("POST", "http://localhost:5003/state/led-command",
                   {"command": "on"})
check("2.4b LED on", code, body)

# Engine passthrough
code, body = http("POST", "http://localhost:5003/engine/move",
                   {"move": "b0c2"})
check("2.4.1 Engine move passthrough", code, body)

code, body = http("POST", "http://localhost:5003/engine/ai-move",
                   {"difficulty": 3})
check("2.4.2 Engine AI move passthrough", code, body)

code, body = http("POST", "http://localhost:5003/engine/reset")
check("2.4.3 Engine reset passthrough", code, body)

# LED-compat
code, body = http("POST", "http://localhost:5003/fen",
                   {"fen": "compat_test"})
check("2.5.1 /fen compat", code, body)

code, body = http("POST", "http://localhost:5003/opponent",
                   {"from_r": 0, "from_c": 0, "to_r": 1, "to_c": 0})
check("2.5.2 /opponent compat", code, body)

# Side-to-move after b FEN
code, body = http("POST", "http://localhost:5003/state/fen",
                   {"fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR b - - 0 2"})
code2, body2 = http("GET", "http://localhost:5003/state")
stm = body2.get("side_to_move", "?") if isinstance(body2, dict) else "?"
check(f"2.6.3 FEN 'b' maps to 'black' (got '{stm}')", 200 if stm == "black" else 0, body2)

# ── 3. Coaching Server ───────────────────────────────────────────────
print("\n=== 3. Coaching Server (port 5001) ===")
code, body = http("GET", "http://localhost:5001/health")
check("3.1 Health", code, body)

code, body = http("GET", "http://localhost:5001/agent-state/graph")
check("3.2 Agent graph", code, body)

code, body = http("GET", "http://localhost:5001/agents")
check("3.3 Agent registry", code, body)

# ── 4. Go Coaching ───────────────────────────────────────────────────
print("\n=== 4. Go Coaching (port 5002) ===")
code, body = http("GET", "http://localhost:5002/health")
check("4.1 Health", code, body)

code, body = http("GET", "http://localhost:5002/dashboard/graph")
check("4.3 Graph API", code, body)

try:
    req = urllib.request.Request("http://localhost:5002/metrics")
    with urllib.request.urlopen(req, timeout=10) as resp:
        text = resp.read().decode()
        has_metrics = "process" in text or "go_" in text or "http" in text
        check(f"4.4 Metrics (len={len(text)}, has_metrics={has_metrics})", resp.status, has_metrics)
except Exception as e:
    check("4.4 Metrics", 0, str(e))

# ── 5. Client UI ─────────────────────────────────────────────────────
print("\n=== 5. Client UI (port 3000) ===")
try:
    req = urllib.request.Request("http://localhost:3000")
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode()
        has_root = "root" in html or "app" in html.lower()
        check(f"5.1 HTML serves (len={len(html)})", resp.status, has_root)
except Exception as e:
    check("5.1 HTML serves", 0, str(e))

# ── 6. Kibo ──────────────────────────────────────────────────────────
print("\n=== 6. Kibo Viewer (port 3001) ===")
try:
    req = urllib.request.Request("http://localhost:3001")
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode()
        check(f"6.1 HTML serves (len={len(html)})", resp.status, "ok")
except Exception as e:
    check("6.1 HTML serves", 0, str(e))

# ── Bridge WS tests ──────────────────────────────────────────────────
print("\n=== 7. Bridge WS Protocol ===")
import websockets

async def ws_recv_type(ws, expected_type, timeout=10):
    """Receive messages until we get one with the expected type (drain others)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return None
        try:
            raw = await asyncio.wait_for(ws.recv(), min(remaining, 5))
            msg = json.loads(raw)
            if msg.get("type") == expected_type:
                return msg
        except asyncio.TimeoutError:
            return None

async def ws_tests():
    async with websockets.connect("ws://localhost:5003/ws") as ws:
        # reset first to get a clean state
        await ws.send(json.dumps({"type": "reset"}))
        r = await ws_recv_type(ws, "state")
        check(f"7.0 Reset to clean state", 200 if r else 0, r)

        # get_state
        await ws.send(json.dumps({"type": "get_state"}))
        r = await ws_recv_type(ws, "state")
        check(f"7.1 get_state side={r.get('side_to_move') if r else '?'}", 200 if r and r.get('side_to_move') == 'red' else 0, r)

        # legal move (knight)
        await ws.send(json.dumps({"type": "move", "move": "b0c2"}))
        r = await ws_recv_type(ws, "move_result")
        valid = r.get('valid') if r else None
        check(f"7.2 Legal move valid={valid}", 200 if valid == True else 0, r)

        # illegal move (rook can't jump to a5)
        await ws.send(json.dumps({"type": "move", "move": "a9a5"}))
        r = await ws_recv_type(ws, "move_result")
        valid = r.get('valid') if r else None
        check(f"7.3 Illegal move valid={valid}", 200 if valid == False else 0, r)

        # AI move
        await ws.send(json.dumps({"type": "ai_move", "difficulty": 3}))
        r = await ws_recv_type(ws, "ai_move")
        check(f"7.4 AI move move={r.get('move','?') if r else '?'}", 200 if r else 0, r)

        # reset
        await ws.send(json.dumps({"type": "reset"}))
        r = await ws_recv_type(ws, "state")
        check(f"7.5 Reset side={r.get('side_to_move') if r else '?'}", 200 if r and r.get('side_to_move') == 'red' else 0, r)

asyncio.run(ws_tests())

print("\n=== SMOKE TEST COMPLETE ===\n")
