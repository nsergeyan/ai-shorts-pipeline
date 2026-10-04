import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Theme } from "./types";

// Lower zone: below the video strip in framed mode (strip ends at ~66%, the
// progress bar sits there), above the platform's own bottom UI.
const TOP_PCT = 69;
const EXIT_FRAMES = 6;

// Shared card every graphic sits in: springs up on entry, fades on exit.
export const Panel: React.FC<{
  theme: Theme;
  durationInFrames: number;
  children: React.ReactNode;
}> = ({ theme, durationInFrames, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ fps, frame, config: { damping: 16, stiffness: 180, mass: 0.6 } });
  const exit = interpolate(
    frame,
    [durationInFrames - EXIT_FRAMES, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <div
      style={{
        position: "absolute",
        top: `${TOP_PCT}%`,
        left: "6%",
        right: "6%",
        padding: "36px 44px",
        borderRadius: 32,
        background: theme.panel,
        borderTop: `6px solid ${theme.accent}`,
        boxShadow: "0 18px 50px rgba(0,0,0,0.55)",
        opacity: Math.min(enter, exit),
        transform: `translateY(${interpolate(enter, [0, 1], [60, 0])}px) scale(${interpolate(enter, [0, 1], [0.92, 1])})`,
      }}
    >
      {children}
    </div>
  );
};
