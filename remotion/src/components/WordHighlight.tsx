import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";

interface WordEntry {
  word: string;
  start: number;
  end: number;
}

const WORDS_PER_LINE = 3;
const FONT_FAMILY = '"Helvetica Neue", Helvetica, Arial, sans-serif';
const FONT_SIZE = 82;
const GAP = 16;
const SIDE_PADDING = 0.04; // 4% per side, matches the container padding
const STROKE_PAD = 12; // the black text stroke bleeds past the glyph box
const MIN_SCALE = 0.55; // never shrink past this, even for freak-long words

// Measure the line for real instead of guessing from character count. One
// canvas is reused across frames; measureText is synchronous, so the fitted
// size is known during the same render that paints the frame.
let measureCtx: CanvasRenderingContext2D | null = null;
const measureWords = (words: string[]): number => {
  if (!measureCtx) {
    measureCtx = document.createElement("canvas").getContext("2d");
    if (!measureCtx) return 0;
  }
  measureCtx.font = `800 ${FONT_SIZE}px ${FONT_FAMILY}`;
  // Chrome honours letterSpacing on the 2d context; engines that ignore it
  // just over-estimate slightly, which errs toward fitting.
  (measureCtx as unknown as { letterSpacing: string }).letterSpacing = "-1px";
  return words.reduce((sum, w) => sum + measureCtx!.measureText(w).width, 0);
};

export const WordHighlight: React.FC<{ wordsData: WordEntry[] }> = ({
  wordsData,
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const currentTime = frame / fps;

  // Hold the current line through pauses. Whisper leaves gaps between words at
  // punctuation and suspense beats, so requiring a strictly active word made the
  // whole line blink off and back on. Track the last word that has started
  // instead, which keeps the line on screen across those gaps.
  let activeIdx = -1;
  for (let i = 0; i < wordsData.length; i++) {
    if (currentTime >= wordsData[i].start) activeIdx = i;
    else break;
  }

  // Before the first word: nothing to show yet.
  if (activeIdx === -1) return null;

  // After the last word: clear, so stale text does not sit under the CTA.
  const lastIdx = wordsData.length - 1;
  if (activeIdx === lastIdx && currentTime >= wordsData[lastIdx].end) return null;

  const lineIdx = Math.floor(activeIdx / WORDS_PER_LINE);
  const lineStart = lineIdx * WORDS_PER_LINE;
  const line = wordsData.slice(lineStart, lineStart + WORDS_PER_LINE);
  const activeInLine = activeIdx - lineStart;

  // Shrink the whole line to fit the safe width rather than letting it run
  // under the frame edge.
  const available = width * (1 - SIDE_PADDING * 2) - STROKE_PAD * 2;
  const measured = measureWords(line.map((e) => e.word)) + GAP * (line.length - 1);
  const fit = measured > available ? Math.max(MIN_SCALE, available / measured) : 1;
  const fontSize = Math.round(FONT_SIZE * fit);

  return (
    <div
      style={{
        position: "absolute",
        top: "27%",
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        padding: "0 4%",
        // No overflow:hidden here. With the fit-to-width scale above nothing
        // should overflow, and clipping is exactly the bug this replaces.
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: Math.round(GAP * fit),
        }}
      >
        {line.map((entry, i) => {
          const isActive = i === activeInLine;
          const isPast = i < activeInLine;

          const wordPopFrame = Math.round(entry.start * fps);
          const popProgress = spring({
            fps,
            frame: frame - wordPopFrame,
            config: { damping: 18, stiffness: 320, mass: 0.5 },
          });

          const scale = interpolate(popProgress, [0, 1], [0.5, 1.0], {
            extrapolateRight: "clamp",
          });
          const opacity = interpolate(popProgress, [0, 0.2, 1], [0, 1, 1], {
            extrapolateRight: "clamp",
          });

          return (
            <span
              key={i}
              style={{
                fontSize,
                fontFamily: FONT_FAMILY,
                fontWeight: 800,
                letterSpacing: -1,
                color: isActive ? "#FFE000" : "white",
                opacity: opacity * (isPast ? 0.5 : 1),
                textShadow: isActive
                  ? "0 0 20px rgba(255,224,0,0.4), 3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 4px 4px 0 #000"
                  : "3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 4px 4px 0 #000",
                display: "inline-block",
                transform: `scale(${scale})`,
                whiteSpace: "nowrap",
              }}
            >
              {entry.word}
            </span>
          );
        })}
      </div>
    </div>
  );
};
