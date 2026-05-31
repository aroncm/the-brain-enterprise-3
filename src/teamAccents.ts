// MLB primary-color palette ported from infra/modal/app.py.
// Used to tint UI accents in the Mobian-themed audit workflow.

const MLB_TEAM_PRIMARY: Record<string, string> = {
  ARI: "#A71930", AZ: "#A71930", ARIZ: "#A71930",
  ATL: "#13274F", BAL: "#DF4601", BOS: "#BD3039",
  CHC: "#0E3386", CWS: "#27251F", CHW: "#27251F", CIN: "#C6011F",
  CLE: "#0C2340", COL: "#33006F", DET: "#0C2340", HOU: "#002D62",
  KC: "#004687", KCR: "#004687", KAN: "#004687", KANS: "#004687",
  LAA: "#BA0021", LAD: "#005A9C",
  MIA: "#EF3340", MIL: "#12284B", MIN: "#002B5C", NYM: "#002D72",
  NYY: "#0C2340", ATH: "#003831", OAK: "#003831", PHI: "#E81828",
  PIT: "#27251F", SD: "#2F241D", SDP: "#2F241D", SF: "#FD5A1E",
  SFG: "#FD5A1E", SEA: "#0C2C56", STL: "#C41E3A",
  TB: "#092C5C", TBR: "#092C5C", TAM: "#092C5C", TAMP: "#092C5C",
  TEX: "#003278", TOR: "#134A8E", WSH: "#14225A", WAS: "#14225A",
};

const FALLBACK_ACCENT = "#2ec4a0";

export function teamPrimaryHex(team: string | null | undefined): string {
  const key = (team ?? "").toUpperCase().replace(/[^A-Z]/g, "");
  if (!key) return FALLBACK_ACCENT;
  for (let length = key.length; length >= 2; length--) {
    const candidate = key.slice(0, length);
    if (candidate in MLB_TEAM_PRIMARY) return MLB_TEAM_PRIMARY[candidate];
  }
  return FALLBACK_ACCENT;
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  if (value.length !== 6) return [46, 196, 160];
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  const channel = (c: number) => {
    const srgb = c / 255;
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export type TeamAccents = {
  primary: string;
  label: string;
  dot: string;
  rowBg: string;
};

export function teamAccents(team: string | null | undefined): TeamAccents {
  const primary = teamPrimaryHex(team);
  const [r, g, b] = hexToRgb(primary);
  const luminance = relativeLuminance(primary);
  const rowAlpha = luminance >= 0.1 ? 0.1 : 0.25;
  const label = luminance >= 0.12 ? primary : "#ffffff";
  return {
    primary,
    label,
    dot: primary,
    rowBg: `rgba(${r}, ${g}, ${b}, ${rowAlpha.toFixed(2)})`,
  };
}
