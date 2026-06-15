// MLB primary-color palette ported from infra/modal/app.py.
// Used to tint UI accents in the Mobian-themed audit workflow.

const MLB_TEAM_PRIMARY: Record<string, string> = {
  ARI: "#A71930", AZ: "#A71930", ARIZ: "#A71930",
  ATL: "#CE1141", BAL: "#DF4601", BOS: "#BD3039",
  CHC: "#0E3386", CWS: "#C4CED4", CHW: "#C4CED4", CIN: "#C6011F",
  CLE: "#E50022", COL: "#33006F", DET: "#FA4616", HOU: "#EB6E1F",
  KC: "#004687", KCR: "#004687", KAN: "#004687", KANS: "#004687",
  LAA: "#BA0021", LAD: "#005A9C",
  MIA: "#EF3340", MIL: "#FFC52F", MIN: "#D31145", NYM: "#FF5910",
  NYY: "#003087", ATH: "#EFB21E", OAK: "#EFB21E", PHI: "#E81828",
  PIT: "#FDB827", SD: "#FFC425", SDP: "#FFC425", SF: "#FD5A1E",
  SFG: "#FD5A1E", SEA: "#005C5C", STL: "#C41E3A",
  TB: "#8FBCE6", TBR: "#8FBCE6", TAM: "#8FBCE6", TAMP: "#8FBCE6",
  TEX: "#C0111F", TOR: "#134A8E", WSH: "#AB0003", WAS: "#AB0003",
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
  accent: string;
  label: string;
  dot: string;
  rowBg: string;
};

export function teamAccents(team: string | null | undefined): TeamAccents {
  const primary = teamPrimaryHex(team);
  const [r, g, b] = hexToRgb(primary);
  const luminance = relativeLuminance(primary);
  const rowAlpha = luminance >= 0.1 ? 0.1 : 0.25;
  // Display-safe accent: a team primary too dark to read on the dark canvas
  // (NYY/TOR/CHC navy, COL purple, SEA teal, KC blue) falls back to white so
  // the logo wordmark + accents stay legible instead of rendering dark or wrong.
  const accent = luminance >= 0.12 ? primary : "#ffffff";
  return {
    primary,
    accent,
    label: accent,
    dot: accent,
    rowBg: `rgba(${r}, ${g}, ${b}, ${rowAlpha.toFixed(2)})`,
  };
}

// True when the team's primary is too dark to read on the dark canvas — used
// to render the (dark) MLB logo image as a legible white silhouette.
export function teamLogoIsDark(team: string | null | undefined): boolean {
  return teamAccents(team).accent === "#ffffff";
}
