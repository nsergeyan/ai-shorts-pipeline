import React from "react";
import { AbsoluteFill } from "remotion";
import { WordHighlight } from "../components/WordHighlight";

const MOCK_WORDS = [
  { word: "Toni", start: 0.3, end: 0.6 },
  { word: "Kroos", start: 0.6, end: 1.0 },
  { word: "had", start: 1.0, end: 1.2 },
  { word: "a", start: 1.2, end: 1.35 },
  { word: "locker", start: 1.35, end: 1.7 },
  { word: "room", start: 1.7, end: 2.0 },
  { word: "obsession", start: 2.0, end: 2.6 },
  { word: "that", start: 2.6, end: 2.8 },
  { word: "completely", start: 2.8, end: 3.3 },
  { word: "confused", start: 3.3, end: 3.8 },
  { word: "his", start: 3.8, end: 4.0 },
  { word: "Real", start: 4.0, end: 4.3 },
  { word: "Madrid", start: 4.3, end: 4.8 },
  { word: "teammates", start: 4.8, end: 5.4 },
  { word: "while", start: 5.4, end: 5.7 },
  { word: "most", start: 5.7, end: 5.95 },
  { word: "football", start: 5.95, end: 6.4 },
  { word: "superstars", start: 6.4, end: 7.1 },
  { word: "wear", start: 7.1, end: 7.3 },
  { word: "brand", start: 7.3, end: 7.6 },
  { word: "new", start: 7.6, end: 7.8 },
  { word: "boots", start: 7.8, end: 8.2 },
  { word: "every", start: 8.2, end: 8.5 },
  { word: "month", start: 8.5, end: 8.9 },
];

export const SubtitlePreview: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#111" }}>
      {/* Simulated video zone in the middle */}
      <div
        style={{
          position: "absolute",
          top: "34%",
          left: 0,
          right: 0,
          height: "32%",
          backgroundColor: "#1a3a5c",
        }}
      />
      <WordHighlight wordsData={MOCK_WORDS} />
    </AbsoluteFill>
  );
};
