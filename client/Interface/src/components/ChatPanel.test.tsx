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

  it('posts user chat messages to the coaching dashboard endpoint and renders the reply', async () => {
    mockedAxios.post.mockResolvedValueOnce({
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

    fireEvent.change(screen.getByPlaceholderText('Type a message...'), {
      target: { value: 'What should I do here?' },
    });
    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(mockedAxios.post).toHaveBeenCalledWith(
        expect.stringContaining('/dashboard/chat'),
        expect.objectContaining({
          message: 'What should I do here?',
          session_id: expect.any(String),
        })
      );
    });

    expect(await screen.findByText('Develop your cannon before launching an attack.')).toBeTruthy();
  });

  it('sends move-event prompts with fen and move context', async () => {
    mockedAxios.post.mockResolvedValueOnce({
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
      expect(mockedAxios.post).toHaveBeenCalledWith(
        expect.stringContaining('/dashboard/chat'),
        expect.objectContaining({
          message: expect.stringContaining('red played b0c2'),
          fen: 'test-fen',
          move: 'b0c2',
          session_id: expect.any(String),
        })
      );
    });
  });

  it('renders coaching text without stripping markdown-like or structured cues', async () => {
    mockedAxios.post.mockResolvedValueOnce({
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

    fireEvent.change(screen.getAllByPlaceholderText('Type a message...')[0], {
      target: { value: 'Give me coaching advice.' },
    });
    fireEvent.click(screen.getByRole('button'));

    expect(await screen.findByText(/\*\*Coach:\*\*/)).toBeTruthy();
    expect(screen.getByText(/Improve cannon activity/)).toBeTruthy();
    expect(screen.getByText(/Delay premature attacks/)).toBeTruthy();
  });
});
