/* @vitest-environment jsdom */

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

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
  default: () => <div data-testid="chess-board" />,
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
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
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
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
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
});
