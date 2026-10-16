import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/LuckiestGuy";

interface WordEntry {
  word: string;
  start: number;
  end: number;
}

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

// Match each title word to the spoken word in order, so it lights up when the voice says it.
// Words the voice skips (the series name) light up with the word before them.
const wordTimes = (titleWords: string[], spoken: WordEntry[]): number[] => {
  let j = 0;
  let last = 0;
  return titleWords.map((w) => {
    for (let k = j; k < spoken.length; k++) {
      if (norm(spoken[k].word) === norm(w)) {
        j = k + 1;
        last = spoken[k].start;
        return last;
      }
    }
    return last;
  });
};

// Full hook question on screen from frame 0. Each word pops into an accent box
// as the voice says it, so the card moves with the narration.
export const HookCard: React.FC<{
  text: string;
  endSec: number;
  accent: string;
  topPct: number;
  wordsData: WordEntry[];
}> = ({ text, endSec, accent, topPct, wordsData }) => {
  // Loaded here, not at module scope (same reason as Thumbnail.tsx)
  const { fontFamily } = loadFont();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const endFrame = Math.round(endSec * fps);
  if (frame >= endFrame) return null;

  const words = text.toUpperCase().split(/\s+/);
  const times = wordTimes(words, wordsData.filter((w) => w.start < endSec));
  const t = frame / fps;
  const activeTime = Math.max(-1, ...times.filter((s) => s <= t));

  // Slam in with a bounce, then a slow float so the block never looks frozen
  const slam = spring({ frame, fps, config: { damping: 10, stiffness: 220, mass: 0.6 } });
  const scale = interpolate(slam, [0, 1], [1.12, 1]);
  const bob = Math.sin(frame / 8) * 5;
  const opacity = interpolate(frame, [endFrame - 4, endFrame], [1, 0], { extrapolateLeft: "clamp" });
  const fontSize = text.length <= 24 ? 112 : text.length <= 44 ? 94 : 80;
  const stroke = Math.round(fontSize * 0.06);

  return (
    <div
      style={{
        position: "absolute",
        top: `${topPct}%`,
        left: 0,
        right: 0,
        transform: `translateY(calc(-50% + ${bob}px)) scale(${scale}) rotate(-2deg)`,
        opacity,
        textAlign: "center",
        padding: "0 6%",
      }}
    >
      <div style={{ fontFamily, fontSize, lineHeight: 1.2 }}>
        {words.map((w, i) => {
          const active = times[i] === activeTime;
          const pop = spring({
            frame: frame - Math.round(times[i] * fps),
            fps,
            config: { damping: 12, stiffness: 320, mass: 0.5 },
          });
          const wordScale = active ? interpolate(pop, [0, 1], [1.15, 1]) : 1;
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                margin: "0 8px",
                padding: "0 10px",
                borderRadius: 14,
                transform: `scale(${wordScale})`,
                background: active ? accent : "transparent",
                color: active ? "#000" : "white",
                WebkitTextStroke: active ? undefined : `${stroke}px #000`,
                paintOrder: "stroke fill",
                textShadow: active ? "none" : "0 8px 20px rgba(0,0,0,0.8)",
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
    </div>
  );
};
