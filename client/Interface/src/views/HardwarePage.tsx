'use client';

/**
 * /hardware — Hardware & Bus Dashboard
 *
 * Real-time view of the state-bridge SSE bus, camera/CV service, and LED server.
 * Shows every event published on the bus, the LED call it triggered, and the
 * inferred state of each hardware service.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { bridgeBase, bridgeFetch, bridgeSseUrl } from '../services/bridgeClient';

// ── Config ────────────────────────────────────────────────────────────────────

const MAX_LOG = 300;
const STALE_THRESHOLD_MS = 60_000; // service considered "inactive" after 60 s

// ── Types ─────────────────────────────────────────────────────────────────────

type HardwareSource = 'bridge' | 'cv' | 'led' | 'engine' | 'player';
type LogFilter = 'all' | 'cv' | 'led' | 'engine' | 'player';

interface SseEventPayload {
  type: string;
  data: Record<string, unknown>;
  ts?: number;
}

interface LogEntry {
  id: number;
  ts: number;
  type: string;
  source: HardwareSource;
  description: string;
  ledAction: string;
  data: Record<string, unknown>;
}

interface BusStatus {
  connected: boolean;
  eventsTotal: number;
  recentCount: number;    // events in last 60 s for rate display
  lastEventTs: number | null;
}

interface CvStatus {
  healthy: boolean | null;
  probeUrl: string | null;
  healthDetail: string | null;
  lastCaptureTs: number | null;
  lastFen: string | null;
  errorCount: number;
  lastError: string | null;
}

interface LedStatus {
  lastCommandTs: number | null;
  lastCommand: string | null;
  lastLedEndpoint: string | null;
  mode: 'pieces' | 'moves' | 'opponent' | 'off' | 'idle';
}

// ── ID counter ────────────────────────────────────────────────────────────────

let _id = 0;
const nextId = () => ++_id;

// ── Helpers ───────────────────────────────────────────────────────────────────

function shortFen(fen?: unknown): string {
  if (typeof fen !== 'string' || !fen) return '—';
  const placement = fen.split(' ')[0] ?? '';
  return placement.length > 30 ? placement.substring(0, 30) + '…' : placement;
}

function relativeTime(ts: number | null): string {
  if (!ts) return 'never';
  const elapsed = Date.now() - ts * 1000;
  if (elapsed < 2000) return 'just now';
  if (elapsed < 60_000) return `${Math.floor(elapsed / 1000)}s ago`;
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}m ago`;
  return new Date(ts * 1000).toLocaleTimeString();
}

function formatTs(unixTs: number): string {
  const d = new Date(unixTs * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  const ms = String(d.getMilliseconds()).padStart(3, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${ms}`;
}

// ── Event classification ──────────────────────────────────────────────────────

function classifySource(type: string, data: Record<string, unknown>): HardwareSource {
  const source = data.source as string | undefined;
  if (type === 'cv_capture_requested' || type === 'cv_capture_result' || type === 'cv_capture' || type === 'cv_validation_error') return 'cv';
  if (type === 'fen_update' && source === 'cv') return 'cv';
  if (type === 'led_command') return 'led';
  if (type === 'move_made' && (source === 'ai' || source === 'opponent')) return 'engine';
  if (type === 'state_sync') return 'bridge';
  if (type === 'game_reset') return 'player';
  if (type === 'piece_selected') return 'player';
  return 'bridge';
}

/** Human-readable description of each SSE event. */
function describeEvent(type: string, data: Record<string, unknown>): string {
  const d = data;
  switch (type) {
    case 'state_sync':
      return `State sync — full board snapshot broadcast to all subscribers | FEN: ${shortFen(d.fen)}`;
    case 'fen_update':
      return `Board position updated (source: ${d.source ?? 'unknown'}) | FEN: ${shortFen(d.fen)}`;
    case 'move_made': {
      const from = d.from ?? '?';
      const to = d.to ?? '?';
      const src = d.source ?? '?';
      const result = d.result ?? 'in_progress';
      const check = d.is_check ? ' ⚠ check' : '';
      return `Move ${from}→${to} committed by ${src} | result: ${result}${check}`;
    }
    case 'cv_capture':
      return `Camera detected board position | FEN: ${shortFen(d.fen)}`;
    case 'cv_capture_requested':
      return `Camera recapture requested via ${d.endpoint ?? '/capture'}`;
    case 'cv_capture_result':
      return `Camera capture completed (${d.status ?? 'unknown'}) | FEN: ${shortFen(d.fen)}`;
    case 'cv_validation_error':
      return `CV validation failed — ${d.reason ?? 'no reason provided'}`;
    case 'led_command': {
      const cmd = d.command;
      const detail =
        cmd === 'off' || cmd === 'clear'
          ? 'turn all LEDs off (camera blackout)'
          : cmd === 'on'
          ? 'restore LED display after camera capture'
          : String(cmd);
      return `LED command "${cmd}" — ${detail}`;
    }
    case 'best_move':
      return `Engine suggests best move: ${d.from ?? '?'}→${d.to ?? '?'}`;
    case 'piece_selected': {
      const targets = Array.isArray(d.targets) ? d.targets.length : 0;
      return `Piece selected at ${d.square ?? '?'} — ${targets} legal target${targets !== 1 ? 's' : ''} highlighted`;
    }
    case 'game_reset':
      return 'Game reset — board returned to starting position, all state cleared';
    default:
      return `${type} — ${JSON.stringify(d).substring(0, 80)}`;
  }
}

/**
 * LED server call triggered by this SSE event (bridge_subscriber behavior).
 * Returns empty string if no LED call results.
 */
function describeLedAction(type: string, data: Record<string, unknown>): string {
  const d = data;
  switch (type) {
    case 'state_sync':
    case 'fen_update':
    case 'cv_capture':
      return `→ LED: POST /fen  {fen: "…"}  — redraw all pieces on the board`;
    case 'cv_capture_requested':
    case 'cv_capture_result':
      return '';
    case 'piece_selected': {
      const sq = d.square as string | undefined;
      const hint = sq
        ? ` (${sq}: col=${sq.charCodeAt(0) - 97}, row=${sq[1]})`
        : '';
      return `→ LED: POST /move  {row, col}${hint}  — red=selected, white=empty targets, orange=captures`;
    }
    case 'move_made': {
      const src = d.source as string | undefined;
      if (src === 'ai' || src === 'opponent') {
        return `→ LED: POST /opponent  {from_r, from_c, to_r, to_c}  — from=blue, to=purple`;
      }
      return '';
    }
    case 'best_move':
      return `→ LED: POST /move  {row, col}  — green destination highlight from ${d.from ?? '?'}`;
    case 'led_command': {
      const cmd = d.command;
      if (cmd === 'off' || cmd === 'clear')
        return '→ LED: POST /cv_pause  {}  — all LEDs off for camera capture';
      if (cmd === 'on')
        return '→ LED: POST /cv_resume  {}  — restore previous board lighting';
      return '';
    }
    case 'game_reset':
      return '→ LED: POST /fen (start FEN)  → POST /cv_pause  → POST /cv_resume  — reset sequence';
    default:
      return '';
  }
}

// ── Style maps ────────────────────────────────────────────────────────────────

const SOURCE_BADGE: Record<HardwareSource, string> = {
  bridge: 'bg-slate-600/80 text-slate-200',
  cv:     'bg-indigo-700/80 text-indigo-100',
  led:    'bg-amber-700/80 text-amber-100',
  engine: 'bg-purple-700/80 text-purple-100',
  player: 'bg-emerald-700/80 text-emerald-100',
};

const TYPE_BADGE: Record<string, string> = {
  state_sync:          'bg-slate-700/80 text-slate-300',
  fen_update:          'bg-blue-900/80 text-blue-200',
  cv_capture_requested:'bg-indigo-800/80 text-indigo-100',
  cv_capture_result:   'bg-cyan-900/80 text-cyan-200',
  move_made:           'bg-green-900/80 text-green-200',
  cv_capture:          'bg-indigo-900/80 text-indigo-200',
  cv_validation_error: 'bg-red-900/80 text-red-300',
  led_command:         'bg-amber-900/80 text-amber-200',
  best_move:           'bg-teal-900/80 text-teal-200',
  piece_selected:      'bg-violet-900/80 text-violet-200',
  game_reset:          'bg-orange-900/80 text-orange-200',
};

// ── Status Card ───────────────────────────────────────────────────────────────

function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full mr-2 flex-shrink-0 ${
        active
          ? 'bg-green-400 shadow-[0_0_8px_rgba(74,222,128,0.6)]'
          : 'bg-slate-600'
      }`}
    />
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-900/60 border border-white/10 rounded-xl p-4">
      <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-3">
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between items-start gap-2 text-xs mb-1.5">
      <span className="text-slate-500 flex-shrink-0">{label}</span>
      <span className={`text-right text-slate-200 ${mono ? 'font-mono text-[10px]' : ''}`}>
        {value}
      </span>
    </div>
  );
}

// ── Log Entry ─────────────────────────────────────────────────────────────────

function LogRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const typeCls = TYPE_BADGE[entry.type] ?? 'bg-slate-700/80 text-slate-300';
  const srcCls = SOURCE_BADGE[entry.source];

  return (
    <div
      className="border-b border-white/5 py-1.5 px-3 hover:bg-white/5 cursor-pointer select-none"
      onClick={() => setExpanded((v) => !v)}
    >
      {/* Main row */}
      <div className="flex items-start gap-2 min-w-0">
        <span className="font-mono text-[10px] text-slate-500 flex-shrink-0 mt-0.5 w-24">
          {formatTs(entry.ts)}
        </span>
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded flex-shrink-0 ${typeCls}`}>
          {entry.type}
        </span>
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded flex-shrink-0 ${srcCls}`}>
          {entry.source}
        </span>
        <span className="text-xs text-slate-300 min-w-0 leading-relaxed">
          {entry.description}
        </span>
      </div>

      {/* LED action sub-row */}
      {entry.ledAction && (
        <div className="ml-26 mt-0.5 text-[10px] text-amber-400/80 pl-[8.5rem] font-mono">
          {entry.ledAction}
        </div>
      )}

      {/* Expanded raw JSON */}
      {expanded && (
        <pre className="mt-1 ml-[8.5rem] text-[10px] text-slate-500 bg-black/30 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
          {JSON.stringify(entry.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HardwarePage() {
  const [log, setLog] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<LogFilter>('all');
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);

  const [bus, setBus] = useState<BusStatus>({
    connected: false,
    eventsTotal: 0,
    recentCount: 0,
    lastEventTs: null,
  });
  const [cv, setCv] = useState<CvStatus>({
    healthy: null,
    probeUrl: null,
    healthDetail: null,
    lastCaptureTs: null,
    lastFen: null,
    errorCount: 0,
    lastError: null,
  });
  const [led, setLed] = useState<LedStatus>({
    lastCommandTs: null,
    lastCommand: null,
    lastLedEndpoint: null,
    mode: 'idle',
  });

  const logRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  // Ticker: refresh relative timestamps every 5 s
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 5000);
    return () => clearInterval(t);
  }, []);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log, autoScroll]);

  const pushEntry = useCallback((payload: SseEventPayload) => {
    if (pausedRef.current) return;
    const { type, data, ts = Date.now() / 1000 } = payload;
    const source = classifySource(type, data);
    const entry: LogEntry = {
      id: nextId(),
      ts,
      type,
      source,
      description: describeEvent(type, data),
      ledAction: describeLedAction(type, data),
      data,
    };
    setLog((prev) => {
      const next = [...prev, entry];
      return next.length > MAX_LOG ? next.slice(next.length - MAX_LOG) : next;
    });
  }, []);

  // SSE subscription to /bridge/state/events
  useEffect(() => {
    const url = bridgeSseUrl('/state/events');
    let es: EventSource | null = null;
    let cancelled = false;
    // Cap consecutive failures so a misconfigured token doesn't generate
    // a 401-retry storm on the bridge. Reset on successful onopen.
    let failures = 0;
    const MAX_FAILURES = 5;

    function connect() {
      if (cancelled) return;
      es = new window.EventSource(url);

      es.onopen = () => {
        failures = 0;
        setBus((b) => ({ ...b, connected: true }));
      };

      es.onmessage = (ev: MessageEvent<string>) => {
        let payload: SseEventPayload;
        try {
          payload = JSON.parse(ev.data) as SseEventPayload;
        } catch {
          return;
        }

        const { type, data = {}, ts = Date.now() / 1000 } = payload;

        // Update bus status
        setBus((b) => ({
          ...b,
          eventsTotal: b.eventsTotal + 1,
          lastEventTs: ts,
        }));

        // Update CV status
        if (type === 'cv_capture') {
          setCv((c) => ({
            ...c,
            lastCaptureTs: ts,
            lastFen: (data.fen as string) ?? c.lastFen,
          }));
        } else if (type === 'cv_capture_result') {
          setCv((c) => ({
            ...c,
            lastCaptureTs: ts,
            lastFen: typeof data.fen === 'string' ? data.fen : c.lastFen,
            lastError: Array.isArray(data.issues) && data.issues.length > 0
              ? String(data.issues[0])
              : c.lastError,
          }));
        } else if (type === 'cv_validation_error') {
          setCv((c) => ({
            ...c,
            errorCount: c.errorCount + 1,
            lastError: (data.reason as string) ?? 'unknown',
          }));
        } else if (type === 'fen_update' && data.source === 'cv') {
          setCv((c) => ({
            ...c,
            lastCaptureTs: ts,
            lastFen: (data.fen as string) ?? c.lastFen,
          }));
        }

        // Update LED status
        const ledAction = describeLedAction(type, data);
        if (ledAction) {
          const endpoint = ledAction.split('POST ')[1]?.split(' ')[0] ?? null;
          let mode: LedStatus['mode'] = 'idle';
          if (type === 'fen_update' || type === 'cv_capture' || type === 'state_sync' || type === 'game_reset') mode = 'pieces';
          else if (type === 'piece_selected' || type === 'best_move') mode = 'moves';
          else if (type === 'move_made') mode = 'opponent';
          else if (type === 'led_command' && (data.command === 'off' || data.command === 'clear')) mode = 'off';
          else if (type === 'led_command' && data.command === 'on') mode = 'pieces';
          setLed((l) => ({
            ...l,
            lastCommandTs: ts,
            lastCommand: type === 'led_command' ? (data.command as string) : type,
            lastLedEndpoint: endpoint,
            mode,
          }));
        }

        pushEntry(payload);
      };

      es.onerror = () => {
        setBus((b) => ({ ...b, connected: false }));
        es?.close();
        failures += 1;
        if (cancelled || failures >= MAX_FAILURES) {
          if (failures >= MAX_FAILURES) {
            console.error(
              `[HardwarePage] SSE failed ${failures} times in a row — ` +
              `giving up. Likely auth or bridge unreachable. Reload the ` +
              `page after fixing.`,
            );
          }
          return;
        }
        // Reconnect after 3 s
        setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      cancelled = true;
      es?.close();
      setBus((b) => ({ ...b, connected: false }));
    };
  }, [pushEntry]);

  useEffect(() => {
    let cancelled = false;

    async function refreshHealth() {
      try {
        const response = await bridgeFetch('/health');
        if (!response.ok) {
          throw new Error(`Health request failed with ${response.status}`);
        }
        const payload = await response.json() as {
          cv_service_healthy?: boolean;
          cv_service?: {
            url?: string;
            detail?: unknown;
          };
        };
        if (!cancelled) {
          setCv((current) => ({
            ...current,
            healthy: payload.cv_service_healthy ?? false,
            probeUrl: payload.cv_service?.url ?? null,
            healthDetail: payload.cv_service?.detail
              ? JSON.stringify(payload.cv_service.detail)
              : null,
          }));
        }
      } catch {
        if (!cancelled) {
          setCv((current) => ({
            ...current,
            healthy: false,
            healthDetail: 'bridge health probe failed',
          }));
        }
      }
    }

    void refreshHealth();
    const interval = window.setInterval(() => {
      void refreshHealth();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  // Filtered log view
  const filteredLog = filter === 'all'
    ? log
    : log.filter((e) => e.source === filter);

  const cvActive = cv.lastCaptureTs !== null &&
    Date.now() - cv.lastCaptureTs * 1000 < STALE_THRESHOLD_MS;
  const ledActive = led.lastCommandTs !== null &&
    Date.now() - led.lastCommandTs * 1000 < STALE_THRESHOLD_MS;

  const FILTERS: { key: LogFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'cv', label: 'Camera / CV' },
    { key: 'led', label: 'LED' },
    { key: 'engine', label: 'Engine' },
    { key: 'player', label: 'Player' },
  ];

  return (
    <div className="bg-background-dark text-slate-100 flex flex-col font-display h-screen w-screen overflow-hidden">

      {/* ── Header ── */}
      <header className="h-12 shrink-0 flex items-center gap-4 px-5 border-b border-white/10 bg-black/20">
        <Link
          href="/"
          className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors text-xs"
        >
          <span className="material-icons text-sm">arrow_back</span>
          Board
        </Link>
        <span className="text-slate-700">/</span>
        <span className="text-sm font-bold text-slate-200 tracking-wide">Hardware Dashboard</span>

        <div className="ml-auto flex items-center gap-2 text-[11px]">
          <span
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              bus.connected
                ? 'bg-green-400 shadow-[0_0_8px_rgba(74,222,128,0.5)]'
                : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'
            }`}
          />
          <span className="text-slate-400 font-mono">
            Bridge SSE: {bus.connected ? 'connected' : 'disconnected'}
          </span>
        </div>
      </header>

      {/* ── Status Cards ── */}
      <div className="shrink-0 grid grid-cols-3 gap-3 px-4 py-3 border-b border-white/10">

        {/* SSE Bus */}
        <Card title="SSE Event Bus">
          <div className="flex items-center mb-2">
            <StatusDot active={bus.connected} />
            <span className="text-sm font-semibold">
              {bus.connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <Row label="Total events" value={String(bus.eventsTotal)} />
          <Row label="Last event" value={relativeTime(bus.lastEventTs)} />
          <Row label="Stream URL" value={bridgeSseUrl('/state/events')} mono />
          <div className="mt-2 text-[10px] text-slate-500">
            All hardware services subscribe to this stream.
          </div>
        </Card>

        {/* Camera / CV */}
        <Card title="Camera / CV Service">
          <div className="flex items-center mb-2">
            <StatusDot active={cv.healthy === true} />
            <span className="text-sm font-semibold">
              {cv.healthy === false
                ? 'Unavailable'
                : cv.lastCaptureTs === null
                ? 'Running'
                : cvActive
                ? 'Active'
                : 'Idle'}
            </span>
          </div>
          <Row label="Last capture" value={relativeTime(cv.lastCaptureTs)} />
          <Row
            label="Last FEN"
            value={cv.lastFen ? shortFen(cv.lastFen) : '—'}
            mono
          />
          <Row label="Validation errors" value={String(cv.errorCount)} />
          <Row label="Health" value={cv.healthy === null ? 'checking...' : cv.healthy ? 'ok' : 'down'} />
          <Row label="Probe URL" value={cv.probeUrl ?? '—'} mono />
          {cv.lastError && (
            <div className="mt-1 text-[10px] text-red-400 font-mono truncate" title={cv.lastError}>
              ⚠ {cv.lastError}
            </div>
          )}
          {cv.healthDetail && cv.healthy === false && (
            <div className="mt-1 text-[10px] text-amber-400 font-mono break-all" title={cv.healthDetail}>
              probe: {cv.healthDetail}
            </div>
          )}
          <div className="mt-2 text-[10px] text-slate-500">
            Triggered by <span className="font-mono">POST /bridge/capture</span>, then posts{' '}
            <span className="font-mono">POST /bridge/state/fen</span> with{' '}
            <span className="font-mono">source: "cv"</span>.
          </div>
        </Card>

        {/* LED Server */}
        <Card title="LED Server (Raspberry Pi)">
          <div className="flex items-center mb-2">
            <StatusDot active={ledActive} />
            <span className="text-sm font-semibold capitalize">
              {led.mode === 'idle' && !ledActive ? 'Idle' : led.mode}
            </span>
          </div>
          <Row
            label="Last trigger"
            value={relativeTime(led.lastCommandTs)}
          />
          <Row
            label="Last endpoint"
            value={led.lastLedEndpoint ?? '—'}
            mono
          />
          <Row label="Triggered by" value={led.lastCommand ?? '—'} />
          <div className="mt-2 text-[10px] text-slate-500">
            Driven by <span className="font-mono">bridge_subscriber.py</span>{' '}
            reacting to SSE events. Port 5000.
          </div>
        </Card>
      </div>

      {/* ── Log Header ── */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-white/10 bg-black/10">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
          Event Log
        </span>

        {/* Filter tabs */}
        <div className="flex bg-white/5 rounded-md p-0.5">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`px-2.5 py-1 text-[10px] font-bold rounded transition-all uppercase ${
                filter === key
                  ? 'bg-primary text-white'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <span className="text-[10px] text-slate-600 ml-1">
          {filteredLog.length} event{filteredLog.length !== 1 ? 's' : ''}
          {filter !== 'all' ? ` (${log.length} total)` : ''}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {/* Auto-scroll toggle */}
          <button
            onClick={() => setAutoScroll((v) => !v)}
            className={`flex items-center gap-1 px-2.5 py-1 text-[10px] font-bold rounded border transition-all uppercase ${
              autoScroll
                ? 'bg-primary/20 border-primary/40 text-primary'
                : 'border-white/10 text-slate-500 hover:text-slate-300'
            }`}
          >
            <span className="material-icons text-xs">
              {autoScroll ? 'vertical_align_bottom' : 'pause'}
            </span>
            Auto-scroll
          </button>

          {/* Pause toggle */}
          <button
            onClick={() => setPaused((v) => !v)}
            className={`flex items-center gap-1 px-2.5 py-1 text-[10px] font-bold rounded border transition-all uppercase ${
              paused
                ? 'bg-amber-500/20 border-amber-500/40 text-amber-400'
                : 'border-white/10 text-slate-500 hover:text-slate-300'
            }`}
          >
            <span className="material-icons text-xs">{paused ? 'play_arrow' : 'pause'}</span>
            {paused ? 'Resume' : 'Pause'}
          </button>

          {/* Clear */}
          <button
            onClick={() => setLog([])}
            className="flex items-center gap-1 px-2.5 py-1 text-[10px] font-bold rounded border border-white/10 text-slate-500 hover:text-red-400 hover:border-red-500/40 transition-all uppercase"
          >
            <span className="material-icons text-xs">delete_sweep</span>
            Clear
          </button>
        </div>
      </div>

      {/* ── Log Body ── */}
      <div
        ref={logRef}
        className="flex-1 overflow-y-auto font-mono text-xs"
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          if (!atBottom && autoScroll) setAutoScroll(false);
        }}
      >
        {/* Legend */}
        <div className="sticky top-0 bg-slate-950/90 backdrop-blur flex items-center gap-2 px-3 py-1.5 border-b border-white/5 text-[9px]">
          <span className="text-slate-600 mr-1">Source:</span>
          {(Object.keys(SOURCE_BADGE) as HardwareSource[]).map((s) => (
            <span key={s} className={`px-1.5 py-0.5 rounded font-bold uppercase ${SOURCE_BADGE[s]}`}>
              {s}
            </span>
          ))}
          <span className="ml-4 text-slate-600">Click row to expand raw JSON</span>
          <span className="ml-2 text-amber-400/70">Amber lines = LED server call triggered</span>
        </div>

        {filteredLog.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-slate-600 gap-2">
            <span className="material-icons text-3xl">sensors_off</span>
            <span className="text-sm">
              {bus.connected ? 'Waiting for events…' : 'Not connected to bridge'}
            </span>
          </div>
        ) : (
          filteredLog.map((entry) => <LogRow key={entry.id} entry={entry} />)
        )}
      </div>

      {/* ── Footer ── */}
      <footer className="h-9 shrink-0 flex items-center px-4 border-t border-white/10 bg-black/20 text-[10px] text-slate-600 gap-4">
        <span>Bridge: <span className="font-mono text-slate-500">{bridgeBase}</span></span>
        <span>LED port: <span className="font-mono text-slate-500">5000</span></span>
        <span>SSE events capped at {MAX_LOG} entries</span>
        {paused && (
          <span className="text-amber-400 font-semibold ml-auto animate-pulse">
            ⏸ Logging paused — new events discarded
          </span>
        )}
      </footer>
    </div>
  );
}
