import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";

interface WordEntry {
  word: string;
  start: number;
  end: number;
}

const WORDS_PER_LINE = 3;

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
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
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
                fontSize: 82,
                fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
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
