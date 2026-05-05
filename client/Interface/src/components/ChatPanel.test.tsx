/* @vitest-environment jsdom */

import { createRef } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import ChatPanel, { type ChatPanelHandle } from './ChatPanel';

vi.mock('axios');

const mockedAxios = vi.mocked(axios, true);

describe('ChatPanel', () => {
  beforeAll(() => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    mockedAxios.post.mockReset();
  });

  it('warms the coaching service with an intro request on mount and speaks the reply', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: { response: 'Welcome to Chinese chess. The goal is to checkmate the opposing general.' },
    } as never);
    const speechService = { speak: vi.fn(() => Promise.resolve()) };

    render(
      <ChatPanel
        moveHistory={[]}
        aiThinking={false}
        suggestedMove={null}
        gameStateFen="test-fen"
        speechService={speechService as never}
      />
    );

    await waitFor(() => {
        expect(mockedAxios.post).toHaveBeenCalledWith(
          expect.stringContaining('/dashboard/chat'),
          expect.objectContaining({
          message: expect.stringContaining('Introduce yourself as a Chinese chess coach'),
          session_id: expect.stringContaining('-warmup'),
        })
      );
    });

    expect(await screen.findByText(/Welcome to Chinese chess/)).toBeTruthy();
    await waitFor(() => {
      expect(speechService.speak).toHaveBeenCalledWith(
        'Welcome to Chinese chess. The goal is to checkmate the opposing general.'
      );
    });
  });

  it('replays the coaching intro and TTS after a reset trigger', async () => {
    mockedAxios.post
      .mockResolvedValueOnce({
        data: { response: 'Welcome to Chinese chess. Let us start with the goal and piece movement.' },
      } as never)
      .mockResolvedValueOnce({
        data: { response: 'Welcome back to Chinese chess. We will use this reset to quickly review the basics.' },
      } as never);

    const speechService = { speak: vi.fn(() => Promise.resolve()) };
    const { rerender } = render(
      <ChatPanel
        moveHistory={[]}
        aiThinking={false}
        suggestedMove={null}
        gameStateFen="test-fen"
        speechService={speechService as never}
        resetVersion={0}
      />
    );

    expect(await screen.findByText(/Welcome to Chinese chess/)).toBeTruthy();

    rerender(
      <ChatPanel
        moveHistory={[]}
        aiThinking={false}
        suggestedMove={null}
        gameStateFen="test-fen"
        speechService={speechService as never}
        resetVersion={1}
      />
    );

    expect(await screen.findByText(/Welcome back to Chinese chess/)).toBeTruthy();
    expect(screen.queryByText(/Let us start with the goal/)).toBeNull();
    await waitFor(() => {
      expect(speechService.speak).toHaveBeenCalledTimes(2);
    });
  });

  it('posts user chat messages to the coaching dashboard endpoint and renders the reply', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: { response: 'Welcome to Chinese chess.' },
    } as never).mockResolvedValueOnce({
      data: { response: 'Develop your cannon before launching an attack.' },
    } as never);

    render(
      <ChatPanel
        moveHistory={[]}
        aiThinking={false}
        suggestedMove={null}
        gameStateFen="test-fen"
        speechService={null}
      />
    );

    await screen.findByText('Welcome to Chinese chess.');

    fireEvent.change(screen.getByPlaceholderText('Type a message...'), {
      target: { value: 'What should I do here?' },
    });
    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(
        mockedAxios.post.mock.calls.some(([, payload]) =>
          payload.message === 'What should I do here?'
          && payload.fen === 'test-fen'
          && typeof payload.session_id === 'string')
      ).toBe(true);
    });

    expect(await screen.findByText('Develop your cannon before launching an attack.')).toBeTruthy();
  });

  it('sends move-event prompts with fen and move context', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: { response: 'Welcome to Chinese chess.' },
    } as never).mockResolvedValueOnce({
      data: { response: 'b0c2 develops the knight and helps control the center.' },
    } as never);

    const ref = createRef<ChatPanelHandle>();
    render(
      <ChatPanel
        ref={ref}
        moveHistory={[]}
        aiThinking={false}
        suggestedMove={null}
        gameStateFen="test-fen"
        speechService={null}
      />
    );

    await act(async () => {
      ref.current?.sendMoveEvent('b0c2', 'test-fen', 'red', 'in_progress', false, 35);
    });

    await waitFor(() => {
      expect(
        mockedAxios.post.mock.calls.some(([, payload]) =>
          typeof payload.message === 'string'
          && payload.message.includes('red played b0c2')
          && payload.fen === 'test-fen'
          && payload.move === 'b0c2'
          && typeof payload.session_id === 'string')
      ).toBe(true);
    });
  });

  it('renders coaching text without stripping markdown-like or structured cues', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: { response: 'Welcome to Chinese chess.' },
    } as never).mockResolvedValueOnce({
      data: {
        response: '**Coach:** Control the center first.\n- Improve cannon activity\n- Delay premature attacks',
      },
    } as never);

    render(
      <ChatPanel
        moveHistory={[]}
        aiThinking={false}
        suggestedMove={null}
        gameStateFen="test-fen"
        speechService={null}
      />
    );

    await screen.findByText('Welcome to Chinese chess.');

    fireEvent.change(screen.getAllByPlaceholderText('Type a message...')[0], {
      target: { value: 'Give me coaching advice.' },
    });
    fireEvent.click(screen.getByRole('button'));

    expect(await screen.findByText(/\*\*Coach:\*\*/)).toBeTruthy();
    expect(screen.getByText(/Improve cannon activity/)).toBeTruthy();
    expect(screen.getByText(/Delay premature attacks/)).toBeTruthy();
  });
});
