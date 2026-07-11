import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
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

export interface SfxEvent {
  time: number;
  file: string;
  volume?: number;
}

export interface ShortVideoProps {
  clips: ClipProps[];
  audioPath: string;
  musicPath?: string;
  musicVolume?: number;
  wordsData?: WordEntry[];
  sfxEvents?: SfxEvent[];
  totalDurationSec: number;
}

const WHIP_FRAMES = 4;
const WHIP_DISTANCE = 80;
const WHIP_BLUR = 8;

const ClipRenderer: React.FC<{
  clip: ClipProps;
  isFirst: boolean;
  isLast: boolean;
  clipFrames: number;
  clipIndex: number;
}> = ({ clip, isFirst, isLast, clipFrames, clipIndex }) => {
  const frame = useCurrentFrame();

  const opacity = isFirst
    ? interpolate(frame, [0, 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;

  // Even clips exit left, odd clips exit right — alternating whip direction
  const enterStartX = !isFirst ? ((clipIndex - 1) % 2 === 0 ? WHIP_DISTANCE : -WHIP_DISTANCE) : 0;
  const exitEndX = !isLast ? (clipIndex % 2 === 0 ? -WHIP_DISTANCE : WHIP_DISTANCE) : 0;

  let translateX = 0;
  let motionBlur = 0;

  if (!isFirst && frame <= WHIP_FRAMES) {
    translateX = interpolate(frame, [0, WHIP_FRAMES], [enterStartX, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    motionBlur = interpolate(frame, [0, WHIP_FRAMES], [WHIP_BLUR, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  if (!isLast && frame >= clipFrames - WHIP_FRAMES) {
    const elapsed = frame - (clipFrames - WHIP_FRAMES);
    translateX = interpolate(elapsed, [0, WHIP_FRAMES], [0, exitEndX], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    motionBlur = interpolate(elapsed, [0, WHIP_FRAMES], [0, WHIP_BLUR], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  return (
    <AbsoluteFill
      style={{
        opacity,
        transform: `translateX(${translateX}px)`,
        filter: motionBlur > 0.1 ? `blur(${motionBlur}px)` : undefined,
      }}
    >
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

const ChromaticGlitch: React.FC<{ glitchFrames: number[] }> = ({ glitchFrames }) => {
  const frame = useCurrentFrame();

  let intensity = 0;
  for (const gf of glitchFrames) {
    const dist = Math.abs(frame - gf);
    if (dist <= 3) {
      intensity = Math.max(
        intensity,
        interpolate(dist, [0, 3], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      );
    }
  }

  if (intensity < 0.01) return null;

  const offset = intensity * 18;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden" }}>
      <div style={{
        position: "absolute", inset: 0,
        background: `rgba(255, 30, 30, ${intensity * 0.18})`,
        transform: `translateX(-${offset}px)`,
        mixBlendMode: "screen",
      }} />
      <div style={{
        position: "absolute", inset: 0,
        background: `rgba(30, 30, 255, ${intensity * 0.18})`,
        transform: `translateX(${offset}px)`,
        mixBlendMode: "screen",
      }} />
      <div style={{
        position: "absolute",
        left: 0, right: 0,
        top: `${25 + (frame % 9) * 6}%`,
        height: 2,
        background: `rgba(255, 255, 255, ${intensity * 0.5})`,
      }} />
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
  sfxEvents = [],
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
        <ClipRenderer
          clip={clip}
          isFirst={i === 0}
          isLast={i === clips.length - 1}
          clipFrames={clipFrames}
          clipIndex={i}
        />
      </Sequence>
    );
  });

  // Every 3rd cut (starting at index 1) gets a flash — evenly spread, ~1 in 3
  const flashFrames = cutFrames.filter((_, i) => i % 3 === 1);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <div style={{ width: "100%", height: "100%" }}>
        {clipSequences}
        <Vignette />
      </div>

      <ChromaticGlitch glitchFrames={flashFrames} />
      <FlashCut flashFrames={flashFrames} />

      {audioPath && <Audio src={audioPath} />}
      {musicPath && <Audio src={musicPath} volume={musicVolume} />}
      {sfxEvents.map((event, i) => (
        <Sequence key={`sfx-${i}`} from={Math.round(event.time * fps)} durationInFrames={fps * 5}>
          <Audio src={event.file} volume={event.volume ?? 0.35} />
        </Sequence>
      ))}
      {wordsData.length > 0 && <WordHighlight wordsData={wordsData} />}
      <ProgressBar />
    </AbsoluteFill>
  );
};
