import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  useVideoConfig,
  interpolate,
  useCurrentFrame,
  spring,
} from "remotion";

interface CTAOverlayProps {
  ctaPath: string;
  ctaDurationSec: number;
}

export const CTAOverlay: React.FC<CTAOverlayProps> = ({
  ctaPath,
  ctaDurationSec,
}) => {
  const { fps, height, width } = useVideoConfig();
  const frame = useCurrentFrame();
  const totalFrames = Math.round(ctaDurationSec * fps);

  // Slide up from bottom on entry
  const slideProgress = spring({
    fps,
    frame,
    config: { damping: 18, stiffness: 180, mass: 0.8 },
  });
  const translateY = interpolate(slideProgress, [0, 1], [height * 0.3, 0]);

  // Fade out near end
  const fadeOut = interpolate(
    frame,
    [totalFrames - 15, totalFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const ctaHeight = height * 0.45;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          bottom: 120,
          left: "50%",
          transform: `translateX(-50%) translateY(${translateY}px)`,
          opacity: fadeOut,
          height: ctaHeight,
          width: width,
          display: "flex",
          justifyContent: "center",
          alignItems: "flex-end",
        }}
      >
        <OffthreadVideo
          src={ctaPath}
          style={{
            height: ctaHeight,
            width: "auto",
          }}
          muted
        />
      </div>
    </AbsoluteFill>
  );
};
