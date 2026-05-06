'use client';

import { useEffect, useMemo, useState } from 'react';

interface Props {
  text: string;
  /** Time between ticks in ms. Default 60. */
  tickMs?: number;
  /** Tokens revealed per tick. Default 1. */
  tokensPerTick?: number;
  /** Show a blinking caret while typing. */
  showCaret?: boolean;
  className?: string;
  /**
   * If provided, every pill (markdown bold or label-colon) becomes a
   * <button> that invokes this callback with the pill's text content
   * when clicked. Use this to wire pills like `Best move:` to highlight
   * the corresponding move on the board.
   */
  onPillClick?: (label: string) => void;
}

const HAS_CJK = /[㐀-龿豈-﫿]/;

function tokenize(text: string): string[] {
  if (!text) return [];
  // For text with no whitespace (typically CJK), reveal one character at a
  // time so the typing rhythm still reads naturally. For mixed/Latin text,
  // split on whitespace and keep separators so spacing is preserved.
  if (HAS_CJK.test(text) && !/\s/.test(text)) {
    return Array.from(text);
  }
  return text.split(/(\s+)/).filter((token) => token.length > 0);
}

type Segment = { kind: 'text'; content: string } | { kind: 'badge'; content: string };

interface ParseHit {
  start: number;
  end: number;
  content: string;
}

// Pill candidates we recognise:
//   1. `**Title:**`  — explicit Markdown bold spans
//   2. `^Title:`     — Title-Case label at the start of a line
//   3. `... | Title:`— label following a pipe separator
//
// All three are normalised into rounded-pill badges. The label patterns
// require a capital first letter and ≤ 40 chars before the colon so we
// don't accidentally pillify mid-sentence phrases like "He said:".
function collectPillHits(text: string): ParseHit[] {
  const hits: ParseHit[] = [];
  let match: RegExpExecArray | null;

  const boldRegex = /\*\*([^*\n][^*]*?)\*\*/g;
  while ((match = boldRegex.exec(text)) !== null) {
    hits.push({
      start: match.index,
      end: match.index + match[0].length,
      content: match[1].trim(),
    });
  }

  const lineStartLabelRegex = /^([A-Z][^\n:|]{0,40}:)(?=\s|$)/gm;
  while ((match = lineStartLabelRegex.exec(text)) !== null) {
    hits.push({
      start: match.index,
      end: match.index + match[1].length,
      content: match[1].trim(),
    });
  }

  const pipeLabelRegex = /\|\s+([A-Z][^\n:|]{0,40}:)(?=\s|$)/g;
  while ((match = pipeLabelRegex.exec(text)) !== null) {
    const labelStart = match.index + match[0].length - match[1].length;
    hits.push({
      start: labelStart,
      end: labelStart + match[1].length,
      content: match[1].trim(),
    });
  }

  return hits;
}

function parseSegments(text: string): Segment[] {
  if (!text) return [];

  const hits = collectPillHits(text)
    .sort((a, b) => a.start - b.start)
    .reduce<ParseHit[]>((acc, hit) => {
      const last = acc[acc.length - 1];
      if (!last || hit.start >= last.end) acc.push(hit);
      return acc;
    }, []);

  if (hits.length === 0) {
    return [{ kind: 'text', content: text }];
  }

  const result: Segment[] = [];
  let cursor = 0;
  for (const hit of hits) {
    if (hit.start > cursor) {
      result.push({ kind: 'text', content: text.slice(cursor, hit.start) });
    }
    if (hit.content) {
      result.push({ kind: 'badge', content: hit.content });
    }
    cursor = hit.end;
  }
  if (cursor < text.length) {
    result.push({ kind: 'text', content: text.slice(cursor) });
  }
  return result;
}

export function Typewriter({
  text,
  tickMs = 60,
  tokensPerTick = 1,
  showCaret = true,
  className,
  onPillClick,
}: Props) {
  const segments = useMemo(() => parseSegments(text), [text]);

  // Per-segment token list. Badges count as a single atomic token so they
  // animate as one unit instead of revealing letter-by-letter.
  const segmentTokens = useMemo(
    () =>
      segments.map((seg) => (seg.kind === 'badge' ? [seg.content] : tokenize(seg.content))),
    [segments],
  );

  const totalTokens = useMemo(
    () => segmentTokens.reduce((sum, tokens) => sum + tokens.length, 0),
    [segmentTokens],
  );

  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    setRevealed(0);
    if (totalTokens === 0) return;

    let i = 0;
    const id = window.setInterval(() => {
      i += tokensPerTick;
      if (i >= totalTokens) {
        setRevealed(totalTokens);
        window.clearInterval(id);
      } else {
        setRevealed(i);
      }
    }, tickMs);

    return () => window.clearInterval(id);
  }, [text, tickMs, tokensPerTick, totalTokens]);

  const isTyping = revealed < totalTokens;

  let cursor = 0;
  const rendered = segments.map((seg, idx) => {
    const tokens = segmentTokens[idx];
    const segStart = cursor;
    cursor += tokens.length;
    if (revealed <= segStart) return null;

    const localRevealed = Math.min(tokens.length, revealed - segStart);

    if (seg.kind === 'badge') {
      // Wait until the badge is fully "typed" before revealing it. Empty
      // content falls back to plain text so we don't render an empty pill.
      if (localRevealed < tokens.length || !seg.content) return null;
      const pillClass =
        'inline-block align-middle px-3 py-0.5 mx-1 my-0.5 rounded-full bg-ink/[0.06] border border-ink/20 text-ink/85 text-[12px] font-calligraphy tracking-wider whitespace-nowrap';
      const pillStyle = { animation: 'typewriter-badge-in 0.35s cubic-bezier(0.22, 1, 0.36, 1) both' };
      if (onPillClick) {
        return (
          <button
            type="button"
            key={`badge-${idx}`}
            onClick={() => onPillClick(seg.content)}
            className={`${pillClass} cursor-pointer hover:bg-ink hover:text-rice-paper hover:border-ink transition-colors duration-200`}
            style={pillStyle}
          >
            {seg.content}
          </button>
        );
      }
      return (
        <span key={`badge-${idx}`} className={pillClass} style={pillStyle}>
          {seg.content}
        </span>
      );
    }

    return <span key={`text-${idx}`}>{tokens.slice(0, localRevealed).join('')}</span>;
  });

  return (
    <span className={className}>
      {rendered}
      {showCaret && isTyping && (
        <span
          aria-hidden
          className="inline-block ml-0.5 align-baseline"
          style={{
            width: '0.45em',
            height: '1em',
            background: 'currentColor',
            verticalAlign: '-0.1em',
            opacity: 0.7,
            animation: 'typewriter-caret 0.9s steps(2) infinite',
          }}
        />
      )}
      <style>{`
        @keyframes typewriter-caret {
          0%, 49% { opacity: 0.65; }
          50%, 100% { opacity: 0; }
        }
        @keyframes typewriter-badge-in {
          0% { opacity: 0; transform: translateY(2px) scale(0.92); filter: blur(2px); }
          100% { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
        }
      `}</style>
    </span>
  );
}
