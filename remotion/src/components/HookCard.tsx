import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const FADE_OUT_START = 42;
const FADE_OUT_END = 58;

export const HookCard: React.FC<{ hookText: string }> = ({ hookText }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (frame >= FADE_OUT_END) return null;

  const enterProgress = spring({
    fps,
    frame,
    config: { damping: 22, stiffness: 160, mass: 0.7 },
  });

  const opacity = interpolate(frame, [FADE_OUT_START, FADE_OUT_END], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const translateY = interpolate(enterProgress, [0, 1], [50, 0]);
  const scale = interpolate(enterProgress, [0, 1], [0.88, 1]);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        backgroundColor: "rgba(0,0,0,0.72)",
        opacity,
      }}
    >
      <div
        style={{
          transform: `translateY(${translateY}px) scale(${scale})`,
          textAlign: "center",
          padding: "0 8%",
        }}
      >
        <div
          style={{
            fontSize: 92,
            fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
            fontWeight: 900,
            color: "#FFE000",
            textShadow:
              "3px 3px 0 #000, -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 5px 5px 0 #000",
            letterSpacing: -2,
            lineHeight: 1.1,
          }}
        >
          {hookText}
        </div>
      </div>
    </AbsoluteFill>
  );
};
