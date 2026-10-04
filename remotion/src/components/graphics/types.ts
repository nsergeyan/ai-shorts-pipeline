export interface Theme {
  accent: string;
  panel: string;
  text: string;
}

export const DEFAULT_THEME: Theme = {
  accent: "#FFE000",
  panel: "rgba(10, 10, 14, 0.82)",
  text: "#FFFFFF",
};

export const FONT_FAMILY = '"Helvetica Neue", Helvetica, Arial, sans-serif';

interface GraphicBase {
  start: number; // seconds, absolute in the video
  end: number;
}

export interface StatGraphicData extends GraphicBase {
  type: "stat";
  value: string;
  label: string;
}

export interface VersusSide {
  name: string;
  value: string;
}

export interface VersusGraphicData extends GraphicBase {
  type: "versus";
  left: VersusSide;
  right: VersusSide;
}

export interface ListGraphicData extends GraphicBase {
  type: "list";
  items: string[];
}

export interface QuoteGraphicData extends GraphicBase {
  type: "quote";
  text: string;
  author?: string;
}

export type GraphicData =
  | StatGraphicData
  | VersusGraphicData
  | ListGraphicData
  | QuoteGraphicData;

// Split "$1,250.5M" into prefix "$", number 1250.5, suffix "M" so the number
// part can count up while the rest stays put. Returns null for non-numbers.
export const parseNumber = (
  value: string
): { prefix: string; num: number; decimals: number; suffix: string } | null => {
  const m = value.match(/^([^\d]*?)(\d[\d,]*(?:\.\d+)?)(.*)$/);
  if (!m) return null;
  const digits = m[2].replace(/,/g, "");
  const num = parseFloat(digits);
  if (Number.isNaN(num)) return null;
  const decimals = digits.includes(".") ? digits.split(".")[1].length : 0;
  return { prefix: m[1], num, decimals, suffix: m[3] };
};

export const formatNumber = (n: number, decimals: number): string =>
  n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
