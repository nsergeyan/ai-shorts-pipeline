import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { loadFont, fontFamily } from "@remotion/google-fonts/LuckiestGuy";

loadFont();

export interface HookLine {
  text: string;
  color: string;
}

export interface ThumbnailProps {
  framePath: string;
  hookLines: HookLine[];
}

const CANVAS_WIDTH = 1080;
const BASE_FONT_SIZE = 130;
const CHAR_WIDTH_RATIO = 0.62; // rough width/height ratio for this font, bold + wide

const fitFontSize = (lines: HookLine[]) => {
  const longest = Math.max(...lines.map((l) => l.text.length), 1);
  const maxWidth = CANVAS_WIDTH * 0.88;
  const estimatedWidth = longest * BASE_FONT_SIZE * CHAR_WIDTH_RATIO;
  if (estimatedWidth <= maxWidth) return BASE_FONT_SIZE;
  return Math.floor(maxWidth / (longest * CHAR_WIDTH_RATIO));
};

export const Thumbnail: React.FC<ThumbnailProps> = ({ framePath, hookLines }) => {
  const fontSize = fitFontSize(hookLines);
  const strokeWidth = Math.round(fontSize * 0.05);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* Full-bleed cover crop, biased toward the top so faces stay in frame */}
      <Img
        src={framePath}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "50% 22%",
          filter: "contrast(1.18) saturate(1.35) brightness(1.03)",
        }}
      />
      {/* Lower-middle text block — sits over the chest, not the face */}
      <div
        style={{
          position: "absolute",
          top: "58%",
          left: 0,
          right: 0,
          transform: "translateY(-50%)",
          textAlign: "center",
          padding: "0 5%",
        }}
      >
        <div
          style={{
            display: "inline-block",
            transform: "rotate(-3deg)",
          }}
        >
          {hookLines.map((line, i) => (
            <div
              key={i}
              style={{
                fontSize,
                fontFamily,
                color: line.color,
                WebkitTextStroke: `${strokeWidth}px #000`,
                paintOrder: "stroke fill",
                textShadow: "0 8px 20px rgba(0,0,0,0.8)",
                lineHeight: 1.15,
              }}
            >
              {line.text}
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
