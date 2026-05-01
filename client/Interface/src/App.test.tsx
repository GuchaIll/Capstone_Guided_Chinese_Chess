/* @vitest-environment jsdom */

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// next/link expects to be inside a Next App Router tree. For unit tests
// we replace it with a plain <a> so render() doesn't need a router shell.
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => <a href={href} {...props}>{children}</a>,
}));

const chatMocks = vi.hoisted(() => ({
  sendMoveEvent: vi.fn(),
  sendVoiceMessage: vi.fn(),
}));

const wsMocks = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  onMessage: null as ((message: string) => void) | null,
}));

class MockEventSource {
  static instances: MockEventSource[] = [];

  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {}
}

vi.mock('./components/ChessBoard', () => ({
  default: ({ onMove }: { onMove?: (from: string, to: string) => boolean }) => (
    <div>
      <div data-testid="chess-board" />
      <button type="button" onClick={() => onMove?.('a0', 'a1')}>Stage Move</button>
    </div>
  ),
}));

vi.mock('./components/AgentStateGraph', () => ({
  default: () => <div data-testid="agent-graph" />,
}));

vi.mock('./components/GameOverModal', () => ({
  default: () => null,
}));

vi.mock('./components/EndTurnButton', () => ({
  default: ({ onEndTurn }: { onEndTurn: () => void }) => <button type="button" onClick={onEndTurn}>End Turn</button>,
}));

vi.mock('./components/VoiceControl', () => ({
  VoiceButton: () => null,
  VoiceFeedback: () => null,
  VoiceSettings: () => null,
}));

vi.mock('./hooks/useWebSocket', () => ({
  useWebSocket: (config: { onMessage: (message: string) => void }) => {
    wsMocks.onMessage = config.onMessage;
    return ({
    sendMessage: wsMocks.sendMessage,
    isConnected: true,
    reconnect: vi.fn(),
    disconnect: vi.fn(),
    });
  },
}));

vi.mock('./hooks/useChessVoiceCommands', () => ({
  useChessVoiceCommands: () => ({
    startWakeWordDetection: vi.fn(),
    stopWakeWordDetection: vi.fn(),
    forceAwake: vi.fn(),
    isListening: false,
    isSpeaking: false,
    isAwake: false,
    wakeWordState: 'idle',
    transcript: '',
    interimTranscript: '',
    error: null,
  }),
}));

vi.mock('./services/speech/SpeechService', () => ({
  SpeechService: class {
    speak() {
      return Promise.resolve();
    }
    destroy() {}
  },
}));

vi.mock('./components/ChatPanel', async () => {
  const React = await import('react');

  const MockChatPanel = React.forwardRef((_props, ref) => {
    React.useImperativeHandle(ref, () => ({
      sendMoveEvent: chatMocks.sendMoveEvent,
      sendVoiceMessage: chatMocks.sendVoiceMessage,
    }));
    return <div data-testid="chat-panel" />;
  });

  return {
    default: MockChatPanel,
  };
});

import App from './App';

describe('App coaching integration', () => {
  beforeEach(() => {
    chatMocks.sendMoveEvent.mockReset();
    chatMocks.sendVoiceMessage.mockReset();
    wsMocks.sendMessage.mockReset();
    wsMocks.onMessage = null;
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('bridge unavailable')));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('forwards bridge AI move events to ChatPanel.sendMoveEvent', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen: '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2',
          }),
        } as Response);
      }
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    }));

    render(
      <App />
    );

    const events = MockEventSource.instances[0];
    expect(events).toBeTruthy();

    await act(async () => {
      events.onmessage?.({
        data: JSON.stringify({
          type: 'move_made',
          data: {
            from: 'a9',
            to: 'a8',
            fen: '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2',
            source: 'ai',
            result: 'in_progress',
            is_check: false,
            score: -12,
          },
          ts: Date.now(),
          seq: 1,
        }),
      } as MessageEvent<string>);
    });

    expect(chatMocks.sendMoveEvent).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(chatMocks.sendMoveEvent).toHaveBeenCalledWith(
        'a9a8',
        '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2',
        'black',
        'in_progress',
        false,
        -12,
      );
    });
  });

  it('dedupes bridge command and SSE AI move updates into one coaching event on acknowledgement', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen,
          }),
        } as Response);
      }
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    }));

    render(
      <App />
    );

    const fen = '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2';
    const events = MockEventSource.instances[0];

    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'ai_move',
        move: 'a9a8',
        fen,
        result: 'in_progress',
        is_check: false,
        score: -12,
      }));
    });

    await act(async () => {
      events.onmessage?.({
        data: JSON.stringify({
          type: 'move_made',
          data: {
            from: 'a9',
            to: 'a8',
            fen,
            source: 'ai',
            result: 'in_progress',
            is_check: false,
            score: -12,
          },
          ts: Date.now(),
          seq: 1,
        }),
      } as MessageEvent<string>);
    });

    expect(chatMocks.sendMoveEvent).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(chatMocks.sendMoveEvent).toHaveBeenCalledTimes(1);
    });
  });

  it('requests a fresh board capture before submitting a physical move on end turn', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen: '4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2',
          }),
        } as Response);
      }
      if (url.endsWith('/engine/is-move-legal')) {
        expect(init?.method).toBe('POST');
        return Promise.resolve({
          ok: true,
          json: async () => ({ legal: true }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <App />
    );

    // Wait for the initial /health probe to fire AND its state update to
    // settle. Without this the player_idle End Turn guard short-circuits
    // because liveBoardCheckEnabled is still its default `false`.
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/health'))).toBe(true);
    });
    await act(async () => {});

    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'state',
        fen: '4k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1',
        result: 'in_progress',
        is_check: false,
        seq: 1,
      }));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(wsMocks.sendMessage).toHaveBeenCalledWith(JSON.stringify({ type: 'move', move: 'a0a1' }));
    });
  });

  it('requests a fresh board capture before acknowledging the engine move', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen: '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2',
          }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <App />
    );

    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'ai_move',
        move: 'a9a8',
        fen: '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2',
        result: 'in_progress',
        is_check: false,
        score: -12,
      }));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/capture$/),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('requests an AI move after reconnecting into a bridge state where the engine is on move', async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/health')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ cv_service_healthy: false }),
          } as Response);
        }
        return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
      }));

      render(<App />);

      await act(async () => {
        wsMocks.onMessage?.(JSON.stringify({
          type: 'state',
          fen: 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/4P4/P1P3P1P/1C5C1/9/RNBAKABNR b - - 0 1',
          result: 'in_progress',
          is_check: false,
          seq: 1,
        }));
      });

      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      expect(wsMocks.sendMessage).toHaveBeenCalledWith(
        JSON.stringify({ type: 'ai_move', difficulty: 4 }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('submits a staged player move without touching CV when live board check is off', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: false }),
        } as Response);
      }
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen: '4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2',
          }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <App />
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /stage move/i }));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(wsMocks.sendMessage).toHaveBeenCalledWith(
        JSON.stringify({ type: 'move', move: 'a0a1' }),
      );
    });

    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/capture'))).toBe(false);
  });

  it('rejects a staged move on live-board-check failure but keeps it staged so the next end turn retries validation', async () => {
    // Per docs/error_handling.md: when the CV-side check fails, the
    // submission is rejected, the staged move is preserved, and the
    // user can press End Turn again to retry the same validation flow.
    // Once /capture + /validate-fen + /make-move all agree, the move
    // commits to the WS without the user needing to re-stage it.
    let captureCount = 0;
    let validateCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      if (url.endsWith('/capture')) {
        captureCount += 1;
        // First capture: malformed CV FEN; second: matches engine.
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen: captureCount === 1
              ? 'not a fen'
              : '4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2',
          }),
        } as Response);
      }
      if (url.endsWith('/engine/validate-fen')) {
        validateCount += 1;
        return Promise.resolve({
          ok: true,
          // First validation: invalid → reject. Second: valid → continue.
          json: async () => ({ valid: validateCount > 1 }),
        } as Response);
      }
      if (url.endsWith('/engine/make-move')) {
        expect(init?.method).toBe('POST');
        return Promise.resolve({
          ok: true,
          // Engine's projection of staged move agrees with the second capture.
          json: async () => ({
            valid: true,
            fen: '4k4/9/9/9/9/9/9/9/R8/4K4 b - - 0 2',
          }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/health'))).toBe(true);
    });

    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'state',
        fen: '4k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1',
        result: 'in_progress',
        is_check: false,
        seq: 1,
      }));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /stage move/i }));
    });

    // First End Turn — validation fails, board-sync alert appears.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/dismiss board sync warning/i)).toBeTruthy();
    });

    expect(wsMocks.sendMessage).not.toHaveBeenCalledWith(
      JSON.stringify({ type: 'move', move: 'a0a1' }),
    );
    expect(chatMocks.sendMoveEvent).not.toHaveBeenCalled();
    expect(captureCount).toBe(1);

    // User dismisses the alert. The staged move must still be in place;
    // the user shouldn't have to re-pick the same move.
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/dismiss board sync warning/i));
    });

    // Second End Turn — same validation flow, this time everything agrees.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(wsMocks.sendMessage).toHaveBeenCalledWith(
        JSON.stringify({ type: 'move', move: 'a0a1' }),
      );
    });

    expect(captureCount).toBe(2);
    expect(validateCount).toBe(2);
    expect(chatMocks.sendMoveEvent).not.toHaveBeenCalled();
  });

  it('does not send engine coaching commentary when CV verification is unavailable', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'ok',
            fen: null,
          }),
        } as Response);
      }
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <App />
    );

    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'ai_move',
        move: 'a9a8',
        fen: '1nbakabnr/r8/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 1 2',
        result: 'in_progress',
        is_check: false,
        score: -12,
      }));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(screen.getByText(/cv service unavailable; continuing without physical-board verification\./i)).toBeTruthy();
    });

    expect(chatMocks.sendMoveEvent).not.toHaveBeenCalled();
  });

  it('prompts the user to pick a move when End Turn is pressed in player_idle without CV', async () => {
    // CV reports unhealthy → liveBoardCheckEnabled stays false → there's
    // no physical-detection path to fall through to. Pressing End Turn
    // without staging a move should produce the friendly prompt instead
    // of triggering a /capture call that fails with a 503.
    const captureFetch = vi.fn();
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: false }),
        } as Response);
      }
      if (url.endsWith('/capture')) {
        captureFetch();
        return Promise.resolve({
          ok: false,
          status: 503,
          text: async () => '{"error":"CV capture service unavailable"}',
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    }));

    render(
      <App />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(
        screen.getByText(/you need to pick a move before ending your turn\./i),
      ).toBeTruthy();
    });

    // The guard should short-circuit before any /capture POST happens.
    expect(captureFetch).not.toHaveBeenCalled();
    expect(wsMocks.sendMessage).not.toHaveBeenCalledWith(
      expect.stringContaining('"type":"move"'),
    );
  });

  it('submits the staged move when CV is healthy at click time but goes down mid-flight', async () => {
    // Health probe says CV is up → liveBoardCheckEnabled flips on. Then
    // when /capture is actually called the bridge returns 503 (CV went
    // down between probes). The move must still submit, with a notice
    // explaining verification was skipped — *not* be rejected with the
    // "Board out of sync" message.
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      if (url.endsWith('/capture')) {
        // Bridge reports CV-upstream-unavailable as 503; useBoardSync
        // turns this into the degraded `{status: 'unavailable', fen: null}`.
        return Promise.resolve({
          ok: false,
          status: 503,
          text: async () => '{"error":"CV capture service unavailable"}',
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    // Wait for /health to settle so liveBoardCheckEnabled flips on.
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/health'))).toBe(true);
    });
    await act(async () => {});

    // Stage a move via the mocked board.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /stage move/i }));
    });

    // Click End Turn — the staged move should be submitted to the bridge
    // even though /capture comes back 503.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await waitFor(() => {
      expect(wsMocks.sendMessage).toHaveBeenCalledWith(
        JSON.stringify({ type: 'move', move: 'a0a1' }),
      );
    });

    // And the user is told why verification was skipped.
    await waitFor(() => {
      expect(
        screen.getByText(/cv service unavailable; submitting move without physical-board verification\./i),
      ).toBeTruthy();
    });
  });

  it('shows the board-out-of-sync alert (not the bridge\'s server-shape error) when /capture returns 502', async () => {
    // Bridge returns 502 when CV responded but the FEN was structurally
    // invalid. The user-facing string must be the friendly "Board out
    // of sync" copy from docs/error_handling.md, not the bridge's
    // internal "unexpected payload shape" message.
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: true }),
        } as Response);
      }
      if (url.endsWith('/capture')) {
        return Promise.resolve({
          ok: false,
          status: 502,
          text: async () => '{"error":"CV service returned an unexpected payload shape"}',
        } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/health'))).toBe(true);
    });
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /stage move/i }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    // The user sees the friendly copy, not the server-internal error.
    // The same message lands in both the modal and the inline turn notice.
    await waitFor(() => {
      expect(
        screen.getAllByText(/board out of sync\. this can be caused by a misplaced move or low cv confidence\./i).length,
      ).toBeGreaterThan(0);
    });
    expect(screen.queryByText(/unexpected payload shape/i)).toBeNull();

    // And the move is *not* sent to the WS — the staged-move state stays
    // intact for the user to retry on the next End Turn click.
    expect(wsMocks.sendMessage).not.toHaveBeenCalledWith(
      expect.stringContaining('"type":"move"'),
    );
  });

  it('classifies the player move and posts the matching Kibo trigger to the bridge', async () => {
    // After an accepted move, the client should:
    //   1. POST /coach/classify-move with the FEN *before* + the move
    //   2. Map the classification to a Kibo trigger per docs/Kibo_flow.md
    //   3. POST that trigger to /kibo/trigger on the bridge
    // A "blunder" classification → "misses_move" trigger.
    const classifyCalls: Array<{ fen: string; move: string }> = [];
    const kiboTriggerCalls: string[] = [];

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: false }),
        } as Response);
      }
      if (url.endsWith('/coach/classify-move')) {
        const body = JSON.parse(String(init?.body)) as { fen: string; move: string };
        classifyCalls.push(body);
        return Promise.resolve({
          ok: true,
          json: async () => ({
            move: body.move,
            classification: 'blunder',
            centipawn_loss: 250,
            score_delta: -180,
          }),
        } as Response);
      }
      if (url.endsWith('/kibo/trigger')) {
        const body = JSON.parse(String(init?.body)) as { trigger: string };
        kiboTriggerCalls.push(body.trigger);
        return Promise.resolve({ ok: true, json: async () => ({ status: 'ok' }) } as Response);
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    // Settle the initial /health probe.
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/health'))).toBe(true);
    });
    await act(async () => {});

    // Seed the engine state so the staged-move FEN snapshot is meaningful.
    const fenBefore = '4k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1';
    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'state',
        fen: fenBefore,
        result: 'in_progress',
        is_check: false,
        seq: 1,
      }));
    });

    // Stage the move (mocked board fires a0→a1) then End Turn.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /stage move/i }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    // Engine confirms the move was valid.
    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'move_result',
        valid: true,
        move: 'a0a1',
        fen: '1k7/9/9/9/9/9/9/9/R8/4K4 b - - 0 1',
        result: 'in_progress',
        is_check: false,
        score: -180,
      }));
    });

    // classify-move runs with the snapshot taken at staging time, not
    // the post-move FEN that the engine echoed back.
    await waitFor(() => {
      expect(classifyCalls).toHaveLength(1);
    });
    expect(classifyCalls[0]).toEqual({ fen: fenBefore, move: 'a0a1' });

    // And the bridge gets the matching Kibo trigger.
    await waitFor(() => {
      expect(kiboTriggerCalls).toContain('misses_move');
    });
  });

  it('fires the illegal_move Kibo trigger when the engine rejects the staged move', async () => {
    const kiboTriggerCalls: string[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ cv_service_healthy: false }),
        } as Response);
      }
      if (url.endsWith('/kibo/trigger')) {
        const body = JSON.parse(String(init?.body)) as { trigger: string };
        kiboTriggerCalls.push(body.trigger);
        return Promise.resolve({ ok: true, json: async () => ({ status: 'ok' }) } as Response);
      }
      // classify-move shouldn't be hit on a rejected move.
      if (url.endsWith('/coach/classify-move')) {
        throw new Error('classify-move should not be called when move is invalid');
      }
      return Promise.reject(new Error(`Unexpected fetch call: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/health'))).toBe(true);
    });
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /stage move/i }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /end turn/i }));
    });

    await act(async () => {
      wsMocks.onMessage?.(JSON.stringify({
        type: 'move_result',
        valid: false,
        reason: 'piece cannot move there',
      }));
    });

    await waitFor(() => {
      expect(kiboTriggerCalls).toContain('illegal_move');
    });
  });
});
