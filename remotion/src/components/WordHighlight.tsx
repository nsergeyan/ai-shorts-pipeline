import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";

interface WordEntry {
  word: string;
  start: number;
  end: number;
}

const WORDS_PER_LINE = 3;

function chunkWords(words: WordEntry[], size: number): WordEntry[][] {
  const lines: WordEntry[][] = [];
  for (let i = 0; i < words.length; i += size) {
    lines.push(words.slice(i, i + size));
  }
  return lines;
}

export const WordHighlight: React.FC<{ wordsData: WordEntry[] }> = ({
  wordsData,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  const activeIdx = wordsData.findIndex(
    (w) => currentTime >= w.start && currentTime < w.end
  );

  if (activeIdx === -1) return null;

  const lineIdx = Math.floor(activeIdx / WORDS_PER_LINE);
  const lineStart = lineIdx * WORDS_PER_LINE;
  const line = wordsData.slice(lineStart, lineStart + WORDS_PER_LINE);
  const activeInLine = activeIdx - lineStart;

  // Animate line entrance: slide down + fade in when line changes
  const lineFirstWordFrame = Math.round(line[0].start * fps);
  const entranceProgress = interpolate(
    frame,
    [lineFirstWordFrame, lineFirstWordFrame + 8],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <div
      style={{
        position: "absolute",
        top: "20%",
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        padding: "0 4%",
        opacity: entranceProgress,
        transform: `translateY(${interpolate(entranceProgress, [0, 1], [-12, 0])}px)`,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          backgroundColor: "rgba(0,0,0,0.48)",
          borderRadius: 18,
          padding: "14px 28px",
        }}
      >
      {line.map((entry, i) => {
        const isActive = i === activeInLine;
        // Pop animation when word becomes active
        const wordActivationFrame = Math.round(entry.start * fps);
        const popProgress = spring({
          fps,
          frame: frame - wordActivationFrame,
          config: { damping: 14, stiffness: 200, mass: 0.6 },
        });
        const scale = isActive ? interpolate(popProgress, [0, 1], [0.85, 1.08]) : 1;

        return (
          <span
            key={i}
            style={{
              fontSize: 76,
              fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
              fontWeight: 800,
              letterSpacing: -1,
              color: isActive ? "#FFE000" : "white",
              // Multi-layer text shadow for thick black outline
              textShadow: isActive
                ? "0 0 20px rgba(255,224,0,0.4), 3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 4px 4px 0 #000, -4px -4px 0 #000"
                : "3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 4px 4px 0 #000",
              display: "inline-block",
              transform: `scale(${scale})`,
              transition: "color 0.05s",
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
