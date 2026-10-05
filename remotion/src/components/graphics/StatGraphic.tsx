import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY, StatGraphicData, Theme, formatNumber, parseNumber } from "./types";

const COUNT_FRAMES = 24;

// One big number that counts up from zero, with a label underneath.
export const StatGraphic: React.FC<{ data: StatGraphicData; theme: Theme }> = ({ data, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const parsed = parseNumber(data.value);
  let shown = data.value;
  if (parsed) {
    // Ease-out so the count slows down as it lands on the real value.
    const t = interpolate(frame, [0, COUNT_FRAMES], [0, 1], { extrapolateRight: "clamp" });
    const eased = 1 - Math.pow(1 - t, 3);
    shown = parsed.prefix + formatNumber(parsed.num * eased, parsed.decimals, parsed.grouped) + parsed.suffix;
  }

  const land = spring({ fps, frame: frame - COUNT_FRAMES, config: { damping: 10, stiffness: 260 } });
  const pop = interpolate(land, [0, 0.5, 1], [1, 1.12, 1]);
  const fontSize = shown.length > 9 ? 110 : 150;

  return (
    <div style={{ textAlign: "center", fontFamily: FONT_FAMILY }}>
      <div
        style={{
          fontSize,
          fontWeight: 900,
          color: theme.accent,
          letterSpacing: -4,
          lineHeight: 1,
          transform: `scale(${pop})`,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {shown}
      </div>
      <div
        style={{
          marginTop: 18,
          fontSize: data.label.length > 28 ? 40 : 48,
          fontWeight: 700,
          color: theme.text,
          lineHeight: 1.15,
        }}
      >
        {data.label}
      </div>
    </div>
  );
};
