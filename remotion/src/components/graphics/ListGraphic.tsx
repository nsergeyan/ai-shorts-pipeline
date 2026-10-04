import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_FAMILY, ListGraphicData, Theme } from "./types";

const STAGGER = 8;

// Two to four short items popping in one after another.
export const ListGraphic: React.FC<{ data: ListGraphicData; theme: Theme }> = ({ data, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const items = data.items.slice(0, 4);
  const fontSize = items.some((t) => t.length > 26) ? 40 : 48;

  return (
    <div style={{ fontFamily: FONT_FAMILY, display: "flex", flexDirection: "column", gap: 18 }}>
      {items.map((item, i) => {
        const p = spring({ fps, frame: frame - i * STAGGER, config: { damping: 18, stiffness: 220 } });
        return (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 22,
              opacity: p,
              transform: `translateX(${interpolate(p, [0, 1], [-40, 0])}px)`,
            }}
          >
            <span
              style={{
                flexShrink: 0,
                width: 62,
                height: 62,
                borderRadius: 31,
                background: theme.accent,
                color: "#000",
                fontSize: 38,
                fontWeight: 900,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {i + 1}
            </span>
            <span style={{ fontSize, fontWeight: 800, color: theme.text, lineHeight: 1.15 }}>{item}</span>
          </div>
        );
      })}
    </div>
  );
};
