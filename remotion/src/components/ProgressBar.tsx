import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";

// For 16:9 content in 1080x1920 (objectFit: contain):
// video height = 1080 * (1080/1920) = 607.5px, centered → bottom edge at (1920+607.5)/2 = 1263.75px ≈ 66%
const VIDEO_BOTTOM_PCT = 66;
const BAR_HEIGHT = 6;

export const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const progress = Math.min(frame / durationInFrames, 1);

  return (
    <div
      style={{
        position: "absolute",
        top: `${VIDEO_BOTTOM_PCT}%`,
        left: 0,
        width: "100%",
        height: BAR_HEIGHT,
        backgroundColor: "rgba(255,255,255,0.18)",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${progress * 100}%`,
          backgroundColor: "#FFE000",
          borderRadius: "0 3px 3px 0",
        }}
      />
    </div>
  );
};
