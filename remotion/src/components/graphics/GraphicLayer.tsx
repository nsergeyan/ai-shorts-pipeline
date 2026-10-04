import React from "react";
import { Sequence, useVideoConfig } from "remotion";
import { Panel } from "./Panel";
import { StatGraphic } from "./StatGraphic";
import { VersusGraphic } from "./VersusGraphic";
import { ListGraphic } from "./ListGraphic";
import { QuoteGraphic } from "./QuoteGraphic";
import { GraphicData, Theme } from "./types";

const GraphicBody: React.FC<{ data: GraphicData; theme: Theme }> = ({ data, theme }) => {
  switch (data.type) {
    case "stat":
      return <StatGraphic data={data} theme={theme} />;
    case "versus":
      return <VersusGraphic data={data} theme={theme} />;
    case "list":
      return <ListGraphic data={data} theme={theme} />;
    case "quote":
      return <QuoteGraphic data={data} theme={theme} />;
    default:
      return null;
  }
};

// Places each narration graphic on the timeline at its own start/end time.
export const GraphicLayer: React.FC<{ graphics: GraphicData[]; theme: Theme }> = ({ graphics, theme }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {graphics.map((g, i) => {
        const from = Math.round(g.start * fps);
        const durationInFrames = Math.max(1, Math.round((g.end - g.start) * fps));
        return (
          <Sequence key={`graphic-${i}`} from={from} durationInFrames={durationInFrames} layout="none">
            <Panel theme={theme} durationInFrames={durationInFrames}>
              <GraphicBody data={g} theme={theme} />
            </Panel>
          </Sequence>
        );
      })}
    </>
  );
};
