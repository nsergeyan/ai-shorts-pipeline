import React from "react";
import { Composition } from "remotion";
import { ShortVideo, ShortVideoProps } from "./compositions/ShortVideo";
import { SubtitlePreview } from "./compositions/SubtitlePreview";

const DEFAULT_FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
    <Composition
      id="ShortVideo"
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      component={ShortVideo as any}
      durationInFrames={1800} // placeholder — overridden by calculateMetadata
      fps={DEFAULT_FPS}
      width={1080}
      height={1920}
      defaultProps={
        {
          clips: [],
          audioPath: "",
          musicVolume: 0.07,
          wordsData: [],
          totalDurationSec: 60,
        } as ShortVideoProps
      }
      calculateMetadata={async ({ props }) => {
        const p = props as unknown as ShortVideoProps;
        return {
          durationInFrames: Math.round(p.totalDurationSec * DEFAULT_FPS),
        };
      }}
    />
    <Composition
      id="SubtitlePreview"
      component={SubtitlePreview}
      durationInFrames={270}
      fps={DEFAULT_FPS}
      width={1080}
      height={1920}
    />
    </>
  );
};
