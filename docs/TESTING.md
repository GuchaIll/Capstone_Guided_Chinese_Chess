# State Bridge Testing

## Automated suite

Install bridge-local test dependencies into `server/state_bridge/.venv`:

```bash
server/state_bridge/.venv/bin/pip install -r server/state_bridge/requirements-dev.txt
```

Run the bridge-focused integration suite:

```bash
server/state_bridge/.venv/bin/pytest -c server/state_bridge/pytest.ini server/state_bridge/tests
```

## Manual smoke

1. Start the engine and state bridge.
2. Connect an SSE consumer such as `python ledsystem/bridge_subscriber.py --bridge-url http://localhost:5003`.
3. Verify initial engine sync appears on `/state`.
4. Submit one player move through the engine or `/engine/move`.
5. Trigger one AI move through `/engine/ai-move`.
6. Confirm `/state/events` emits the corresponding `fen_update` and `move_made` events and the LED subscriber reacts.
