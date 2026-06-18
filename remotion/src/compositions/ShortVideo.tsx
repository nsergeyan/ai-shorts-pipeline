import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { WordHighlight } from "../components/WordHighlight";
import { ProgressBar } from "../components/ProgressBar";

export interface ClipProps {
  path: string;
  duration: number;
}

export interface WordEntry {
  word: string;
  start: number;
  end: number;
}

export interface ShortVideoProps {
  clips: ClipProps[];
  audioPath: string;
  musicPath?: string;
  musicVolume?: number;
  wordsData?: WordEntry[];
  punchTimes?: number[];
  totalDurationSec: number;
}

// Hard cut — clip just appears. First clip fades in from black.
const ClipRenderer: React.FC<{ clip: ClipProps; isFirst: boolean }> = ({ clip, isFirst }) => {
  const frame = useCurrentFrame();

  const opacity = isFirst
    ? interpolate(frame, [0, 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;

  return (
    <AbsoluteFill style={{ opacity }}>
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <OffthreadVideo
          src={clip.path}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            filter: "blur(28px) brightness(0.45)",
            transform: "scale(1.1)",
          }}
          muted
        />
      </AbsoluteFill>
      <AbsoluteFill>
        <OffthreadVideo
          src={clip.path}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
          muted
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Brief white flash on selected cuts — subtle, ±2 frames around the cut point
const FlashCut: React.FC<{ flashFrames: number[] }> = ({ flashFrames }) => {
  const frame = useCurrentFrame();

  let opacity = 0;
  for (const cf of flashFrames) {
    const dist = Math.abs(frame - cf);
    if (dist <= 2) {
      opacity = Math.max(
        opacity,
        interpolate(dist, [0, 2], [0.5, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      );
    }
  }

  if (opacity < 0.01) return null;
  return (
    <AbsoluteFill
      style={{ backgroundColor: `rgba(255,255,255,${opacity})`, pointerEvents: "none" }}
    />
  );
};

const Vignette: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: "radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.5) 100%)",
      pointerEvents: "none",
    }}
  />
);

export const ShortVideo: React.FC<ShortVideoProps> = ({
  clips,
  audioPath,
  musicPath,
  musicVolume = 0.07,
  wordsData = [],
  punchTimes = [],
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Build clip sequences (hard cuts — no overlap)
  let accumulated = 0;
  const cutFrames: number[] = []; // frame where each clip ends (= start of next)

  const clipSequences = clips.map((clip, i) => {
    const clipFrames = Math.round(clip.duration * fps);
    const from = accumulated;
    accumulated += clipFrames;
    if (i < clips.length - 1) cutFrames.push(accumulated);

    return (
      <Sequence key={i} from={from} durationInFrames={clipFrames}>
        <ClipRenderer clip={clip} isFirst={i === 0} />
      </Sequence>
    );
  });

  // Every 3rd cut (starting at index 1) gets a flash — evenly spread, ~1 in 3
  const flashFrames = cutFrames.filter((_, i) => i % 3 === 1);

  // Zoom punch: quick scale in, spring back — applied to video content only
  let zoomScale = 1;
  for (const pt of punchTimes) {
    const punchFrame = Math.round(pt * fps);
    const elapsed = frame - punchFrame;
    if (elapsed < 0 || elapsed > 90) continue;

    let extra = 0;
    if (elapsed < 6) {
      extra = interpolate(elapsed, [0, 6], [0, 0.06], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    } else {
      const springBack = spring({
        fps,
        frame: elapsed - 6,
        config: { damping: 14, stiffness: 80, mass: 1 },
      });
      extra = interpolate(springBack, [0, 1], [0.06, 0]);
    }
    zoomScale = Math.max(zoomScale, 1 + extra);
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <div
        style={{
          width: "100%",
          height: "100%",
          transform: `scale(${zoomScale})`,
          transformOrigin: "center center",
        }}
      >
        {clipSequences}
        <Vignette />
      </div>

      <FlashCut flashFrames={flashFrames} />

      {audioPath && <Audio src={audioPath} />}
      {musicPath && <Audio src={musicPath} volume={musicVolume} />}
      {wordsData.length > 0 && <WordHighlight wordsData={wordsData} />}
      <ProgressBar />
    </AbsoluteFill>
  );
};
