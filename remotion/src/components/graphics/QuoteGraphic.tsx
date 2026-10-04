import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { FONT_FAMILY, QuoteGraphicData, Theme } from "./types";

const FRAMES_PER_WORD = 2;

// A quote revealed word by word, with the speaker underneath.
export const QuoteGraphic: React.FC<{ data: QuoteGraphicData; theme: Theme }> = ({ data, theme }) => {
  const frame = useCurrentFrame();
  const words = data.text.split(/\s+/);
  const fontSize = data.text.length > 90 ? 38 : data.text.length > 50 ? 46 : 56;
  const authorOpacity = interpolate(
    frame,
    [words.length * FRAMES_PER_WORD, words.length * FRAMES_PER_WORD + 8],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <div style={{ fontFamily: FONT_FAMILY, position: "relative", paddingLeft: 70 }}>
      <span
        style={{
          position: "absolute",
          left: -6,
          top: -40,
          fontSize: 170,
          fontWeight: 900,
          color: theme.accent,
          lineHeight: 1,
        }}
      >
        “
      </span>
      <div style={{ fontSize, fontWeight: 700, fontStyle: "italic", color: theme.text, lineHeight: 1.2 }}>
        {words.map((w, i) => (
          <span
            key={i}
            style={{
              opacity: interpolate(frame, [i * FRAMES_PER_WORD, i * FRAMES_PER_WORD + 4], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            {w}{" "}
          </span>
        ))}
      </div>
      {data.author && (
        <div style={{ marginTop: 16, fontSize: 36, fontWeight: 800, color: theme.accent, opacity: authorOpacity }}>
          - {data.author}
        </div>
      )}
    </div>
  );
};
