import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY, Theme, VersusGraphicData, VersusSide, parseNumber } from "./types";

const STAGGER = 6;

const Row: React.FC<{
  side: VersusSide;
  share: number | null; // 0-1 bar width, null when values aren't numbers
  isWinner: boolean;
  delay: number;
  theme: Theme;
}> = ({ side, share, isWinner, delay, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const grow = spring({ fps, frame: frame - delay, config: { damping: 20, stiffness: 120 } });
  const colour = isWinner ? theme.accent : theme.text;

  return (
    <div style={{ opacity: Math.min(1, grow * 2) }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 24 }}>
        <span style={{ fontSize: side.name.length > 16 ? 40 : 48, fontWeight: 800, color: theme.text }}>
          {side.name}
        </span>
        <span style={{ fontSize: 64, fontWeight: 900, color: colour, whiteSpace: "nowrap" }}>
          {side.value}
        </span>
      </div>
      {share !== null && (
        <div style={{ marginTop: 10, height: 16, borderRadius: 8, background: "rgba(255,255,255,0.12)" }}>
          <div
            style={{
              height: "100%",
              borderRadius: 8,
              width: `${Math.max(4, share * 100 * grow)}%`,
              background: colour,
              opacity: isWinner ? 1 : 0.6,
            }}
          />
        </div>
      )}
    </div>
  );
};

// Two things compared: names on the left, values on the right, bars sized by value.
export const VersusGraphic: React.FC<{ data: VersusGraphicData; theme: Theme }> = ({ data, theme }) => {
  const frame = useCurrentFrame();
  const a = parseNumber(data.left.value);
  const b = parseNumber(data.right.value);
  const max = a && b ? Math.max(a.num, b.num) : 0;
  const shareA = a && b && max > 0 ? a.num / max : null;
  const shareB = a && b && max > 0 ? b.num / max : null;
  const leftWins = a && b ? a.num >= b.num : false;
  const rightWins = a && b ? b.num > a.num : false;

  const vsOpacity = interpolate(frame, [STAGGER, STAGGER + 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <div style={{ fontFamily: FONT_FAMILY, display: "flex", flexDirection: "column", gap: 14 }}>
      <Row side={data.left} share={shareA} isWinner={leftWins} delay={0} theme={theme} />
      <div style={{ textAlign: "center", fontSize: 34, fontWeight: 900, color: theme.accent, opacity: vsOpacity, letterSpacing: 4 }}>
        VS
      </div>
      <Row side={data.right} share={shareB} isWinner={rightWins} delay={STAGGER * 2} theme={theme} />
    </div>
  );
};
