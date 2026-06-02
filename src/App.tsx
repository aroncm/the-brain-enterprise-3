import { type CSSProperties, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowDownWideNarrow as SortDescending,
  BarChart3 as PresentationChart,
  Calendar as CalendarBlank,
  Files,
  Grid2X2 as SquaresFour,
  LineChart as ChartLineUp,
  List as ListDashes,
  Plus,
  RefreshCw as ArrowsClockwise,
  Search as MagnifyingGlass,
  TrendingDown as TrendDown,
  type LucideIcon as Icon,
  Users,
  UsersRound as UsersThree,
} from "lucide-react";
import {
  ApiConfigurationError,
  fetchEnterpriseGames,
  fetchPitcherProfiles,
  fetchPitchingAuditSummary,
  fetchPitchingRecap,
  fetchPitchingRecapSettings,
  fetchPitchingReplay,
  fetchPreventableRunsOpportunities,
  fetchRunSavingBoard,
  getConfiguredApiBase,
  sendPitchingRecapEmail,
  savePitchingRecapSettings,
} from "./api";
import type {
  BullpenOption,
  EnterpriseGameSummary,
  PitcherProfile,
  PitcherProfilesPayload,
  PitchingAuditSummaryPayload,
  PitchingAuditWindow,
  PitchingGameRecap,
  PitchingRecapEmailResponse,
  PitchingRecapPitcher,
  PitchingRecapSettings,
  PitchingReplayEntry,
  PitchingReplayResponse,
  PreventableRunsOpportunityRow,
  PreventableRunsOpportunitiesPayload,
  RunSavingBoardPayload,
  TripleAConversionCandidate,
} from "./types";
import { teamAccents } from "./teamAccents";

type LoadState = "loading" | "ready" | "error" | "missing-config";
type Workflow = "audit" | "briefings";
type Team = { abbr: string; name: string; club: string; division: string };
type MatrixCell = "standard" | "tandem" | "push" | "workload";

const UNAVAILABLE = "Unavailable";
const LOADING_VALUE = "Awaiting data";

const MLB_TEAM_IDS: Record<string, number> = {
  ARI: 109,
  AZ: 109,
  ATL: 144,
  BAL: 110,
  BOS: 111,
  CHC: 112,
  CWS: 145,
  CIN: 113,
  CLE: 114,
  COL: 115,
  DET: 116,
  HOU: 117,
  KC: 118,
  LAA: 108,
  LAD: 119,
  MIA: 146,
  MIL: 158,
  MIN: 142,
  NYM: 121,
  NYY: 147,
  OAK: 133,
  PHI: 143,
  PIT: 134,
  SD: 135,
  SEA: 136,
  SF: 137,
  STL: 138,
  TB: 139,
  TEX: 140,
  TOR: 141,
  WSH: 120,
};

const MLB_TEAMS: Team[] = [
  { abbr: "AZ", name: "Arizona Diamondbacks", club: "Diamondbacks", division: "NL West" },
  { abbr: "ATL", name: "Atlanta Braves", club: "Braves", division: "NL East" },
  { abbr: "BAL", name: "Baltimore Orioles", club: "Orioles", division: "AL East" },
  { abbr: "BOS", name: "Boston Red Sox", club: "Red Sox", division: "AL East" },
  { abbr: "CHC", name: "Chicago Cubs", club: "Cubs", division: "NL Central" },
  { abbr: "CWS", name: "Chicago White Sox", club: "White Sox", division: "AL Central" },
  { abbr: "CIN", name: "Cincinnati Reds", club: "Reds", division: "NL Central" },
  { abbr: "CLE", name: "Cleveland Guardians", club: "Guardians", division: "AL Central" },
  { abbr: "COL", name: "Colorado Rockies", club: "Rockies", division: "NL West" },
  { abbr: "DET", name: "Detroit Tigers", club: "Tigers", division: "AL Central" },
  { abbr: "HOU", name: "Houston Astros", club: "Astros", division: "AL West" },
  { abbr: "KC", name: "Kansas City Royals", club: "Royals", division: "AL Central" },
  { abbr: "LAA", name: "Los Angeles Angels", club: "Angels", division: "AL West" },
  { abbr: "LAD", name: "Los Angeles Dodgers", club: "Dodgers", division: "NL West" },
  { abbr: "MIA", name: "Miami Marlins", club: "Marlins", division: "NL East" },
  { abbr: "MIL", name: "Milwaukee Brewers", club: "Brewers", division: "NL Central" },
  { abbr: "MIN", name: "Minnesota Twins", club: "Twins", division: "AL Central" },
  { abbr: "NYM", name: "New York Mets", club: "Mets", division: "NL East" },
  { abbr: "NYY", name: "New York Yankees", club: "Yankees", division: "AL East" },
  { abbr: "OAK", name: "Athletics", club: "Athletics", division: "AL West" },
  { abbr: "PHI", name: "Philadelphia Phillies", club: "Phillies", division: "NL East" },
  { abbr: "PIT", name: "Pittsburgh Pirates", club: "Pirates", division: "NL Central" },
  { abbr: "SD", name: "San Diego Padres", club: "Padres", division: "NL West" },
  { abbr: "SEA", name: "Seattle Mariners", club: "Mariners", division: "AL West" },
  { abbr: "SF", name: "San Francisco Giants", club: "Giants", division: "NL West" },
  { abbr: "STL", name: "St. Louis Cardinals", club: "Cardinals", division: "NL Central" },
  { abbr: "TB", name: "Tampa Bay Rays", club: "Rays", division: "AL East" },
  { abbr: "TEX", name: "Texas Rangers", club: "Rangers", division: "AL West" },
  { abbr: "TOR", name: "Toronto Blue Jays", club: "Blue Jays", division: "AL East" },
  { abbr: "WSH", name: "Washington Nationals", club: "Nationals", division: "NL East" },
];

const WORKFLOWS: Array<{ id: Workflow; label: string }> = [
  { id: "audit", label: "Game Replays" },
  { id: "briefings", label: "Game Briefings" },
];

function appSearchParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

function initialWorkflowFromSearch(): Workflow {
  const workflowParam = appSearchParams().get("workflow");
  return WORKFLOWS.some((item) => item.id === workflowParam) ? (workflowParam as Workflow) : "audit";
}

function initialTeamFromSearch(): string {
  const teamParam = appSearchParams().get("team")?.toUpperCase();
  return teamParam && MLB_TEAMS.some((team) => team.abbr === teamParam) ? teamParam : "ATL";
}

function initialGameIdFromSearch(): string | null {
  const params = appSearchParams();
  const gameId = params.get("gameId") ?? params.get("game_id");
  return gameId?.trim() || null;
}

const WORKFLOW_ICONS: Record<Workflow, Icon> = {
  audit: MagnifyingGlass,
  briefings: PresentationChart,
};

const PITCH_TYPE_NAMES: Record<string, string> = {
  FA: "Fastball",
  FF: "Four-Seam Fastball",
  FT: "Two-Seam Fastball",
  SI: "Sinker",
  FC: "Cutter",
  SL: "Slider",
  ST: "Sweeper",
  CU: "Curveball",
  KC: "Knuckle Curve",
  CH: "Changeup",
  FS: "Splitter",
  FO: "Forkball",
  KN: "Knuckleball",
};

function sum(values: Array<number | null | undefined>): number {
  return values.reduce((total, value) => total + (value ?? 0), 0);
}

function avg(values: Array<number | null | undefined>): number | null {
  const numbers = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (numbers.length === 0) return null;
  return numbers.reduce((total, value) => total + value, 0) / numbers.length;
}

function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return value.toFixed(digits);
}

function fmtRuns(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return `${Math.round(value * 100)}%`;
}

function fmtPctPoints(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}pp`;
}

function fmtRate(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return `${Math.round(value * 100)}%`;
}

function fmtSigned(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return UNAVAILABLE;
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function clamp(value: number, min = 0, max = 1): number {
  return Math.max(min, Math.min(max, value));
}

function scaledPercent(value: number | null | undefined, scale = 1): number {
  if (value == null || !Number.isFinite(value) || scale <= 0) return 0;
  return clamp(value / scale);
}

function ordinal(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "unknown";
  const integer = Math.trunc(value);
  const suffix = integer % 100 >= 11 && integer % 100 <= 13 ? "th" : integer % 10 === 1 ? "st" : integer % 10 === 2 ? "nd" : integer % 10 === 3 ? "rd" : "th";
  return `${integer}${suffix}`;
}

function halfInningLabel(half: string | null | undefined, inning: number | null | undefined): string {
  const normalizedHalf = String(half || "").toLowerCase() === "top" ? "top" : String(half || "").toLowerCase() === "bottom" ? "bottom" : "half";
  return `${normalizedHalf} of the ${ordinal(inning)}`;
}

function displayPersonName(name: string | null | undefined): string {
  const clean = String(name || "").trim();
  if (!clean) return "";
  if (!clean.includes(",")) return clean.replace(/\s+/g, " ");
  const parts = clean.split(",").map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) return clean;
  const [last, ...rest] = parts;
  const first = rest.join(" ");
  return [first, last].filter(Boolean).join(" ") || clean;
}

function compactInningLabel(half: string | null | undefined, inning: number | null | undefined): string {
  if (inning == null || !Number.isFinite(inning)) return "—";
  const normalizedHalf = String(half || "").toLowerCase();
  if (normalizedHalf.startsWith("top") || normalizedHalf === "t" || normalizedHalf === "away") return `Top ${inning}`;
  if (normalizedHalf.startsWith("bot") || normalizedHalf === "b" || normalizedHalf === "home") return `Btm ${inning}`;
  return `${inning}`;
}

function batterDisplayName(snapshot: PitchingReplayEntry["snapshot"]): string {
  const raw = String(snapshot.batter_name ?? "").trim();
  const id = String(snapshot.batter_id ?? "").trim();
  if (!raw || /^\d+$/.test(raw) || raw === id) return "—";
  return displayPersonName(raw);
}

function baseStateLabel(baseState: string | null | undefined): string {
  const value = String(baseState || "").trim();
  const labels: Record<string, string> = {
    "000": "Bases empty",
    "100": "Man on first",
    "010": "Man on second",
    "001": "Man on third",
    "110": "Men on first and second",
    "101": "Men on first and third",
    "011": "Men on second and third",
    "111": "Bases loaded",
  };
  return labels[value] ?? "Base state unavailable";
}

function outsLabel(outs: number | null | undefined): string {
  if (outs == null || !Number.isFinite(outs)) return "outs unavailable";
  return `${outs} ${outs === 1 ? "out" : "outs"}`;
}

function normalize(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function featureLabel(value: string | null | undefined): string {
  if (!value) return "Review reason";
  const labels: Record<string, string> = {
    base_traffic: "Runners on base",
    leverage: "Important game state",
    leverage_index: "Important game state",
    leveraged_production_degradation: "Stuff slipping in leverage",
    pitch_count_norm: "Workload building",
    pitch_count_pressure: "Workload building",
    times_through_order_pressure: "Lineup seeing him again",
    tto: "Lineup seeing him again",
    inning_norm: "Later-game exposure",
    inning_pressure: "Later-game exposure",
    degradation_score: "Stuff degradation",
    normalized_degradation: "Stuff degradation",
    decay_velocity: "Decline accelerating",
    decay_acceleration: "Decline accelerating",
    batter_quality: "Dangerous hitters due",
    inning_pitcher_penalty: "History in this inning",
    tto_pitcher_penalty: "History third time through",
    starter_degradation: "Starter was slipping",
    deg_li_threshold: "Degradation mattered in leverage",
    starter_swstr_drop: "Whiffs falling",
    starter_velo_drop: "Velocity down",
    starter_spin_drop: "Spin fading",
    starter_command_slip: "Command slipping",
    starter_zone_miss: "Zone misses widening",
    starter_hard_contact: "Hard contact pressure",
    third_time_through_order: "Lineup seeing him again",
    lefty_cluster_ahead: "Lefty cluster ahead",
    reliever_matchup_edge: "Better relief matchup",
    reliever_contrast_edge: "Relief option changed the look",
    reliever_availability_edge: "Relief option available",
    bullpen_thin_stay: "Bullpen was thin",
    starter_late_inning_stuff: "Starter held late stuff",
  };
  return labels[value] ?? normalize(value);
}

function formatDateText(value: string | null | undefined): string {
  if (!value) return "Date unavailable";
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const REGULAR_SEASON_START_BY_YEAR: Record<string, string> = {
  "2026": "2026-03-25",
  "2025": "2025-03-27",
};

function dateKey(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const match = value.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : null;
}

function isRegularSeasonDate(value: unknown, season: string): boolean {
  const key = dateKey(value);
  if (!key) return true;
  if (!key.startsWith(`${season}-`)) return false;
  const start = REGULAR_SEASON_START_BY_YEAR[season];
  return start ? key >= start : true;
}

function pitchName(value: string | null | undefined): string {
  if (!value) return "Pitch";
  return PITCH_TYPE_NAMES[value.toUpperCase()] ?? normalize(value);
}

function teamLogoUrl(abbr: string): string | null {
  const id = MLB_TEAM_IDS[abbr];
  return id ? `https://www.mlbstatic.com/team-logos/${id}.svg` : null;
}

function pitchCount(entry: PitchingReplayEntry): number {
  const state = replayState(entry);
  return state.official_pitch_count_in_game ?? state.pitch_count_in_game ?? state.replay_pitch_count_in_game ?? 0;
}

function isRelieverReplayEntry(entry: PitchingReplayEntry | null | undefined): boolean {
  if (!entry) return false;
  return entry.entry_type === "reliever_rss" || statusLabel(entry.snapshot.role) === "RELIEVER" || !!entry.snapshot.reliever_state;
}

function replayState(entry: PitchingReplayEntry) {
  return entry.snapshot.reliever_state ?? entry.snapshot.starter_state;
}

function replayStatus(entry: PitchingReplayEntry): string {
  if (isRelieverReplayEntry(entry)) return statusLabel(replayState(entry).rss_status ?? entry.recommendation.status ?? "OK");
  return statusLabel(entry.recommendation.status);
}

function appearanceKey(entry: PitchingReplayEntry): string {
  return `${isRelieverReplayEntry(entry) ? "reliever" : "starter"}:${entry.snapshot.fielding_team}:${entry.snapshot.pitcher_id}:${entry.snapshot.team_appearance_order ?? 1}`;
}

function stuffScore(entry: PitchingReplayEntry): number {
  if (isRelieverReplayEntry(entry)) {
    return Math.max(0, Math.min(100, Math.round((1 - (replayState(entry).rss_score ?? 0)) * 100)));
  }
  return Math.max(20, Math.min(100, Math.round(100 - (replayState(entry).degradation_score ?? 0) * 22)));
}

function velocityDrop(entry: PitchingReplayEntry): number | null {
  const state = replayState(entry);
  if (state.velo_mean_5 == null || state.seasonal_velo_baseline == null) return null;
  return state.velo_mean_5 - state.seasonal_velo_baseline;
}

function scoreForEntry(entry: PitchingReplayEntry, replay: PitchingReplayResponse): string {
  return `${replay.game.away_team} ${entry.snapshot.away_score ?? "—"} - ${entry.snapshot.home_score ?? "—"} ${replay.game.home_team}`;
}

const PITCH_CALL_LABELS: Record<string, string> = {
  "ball": "Ball",
  "ball in dirt": "Ball",
  "called strike": "Called Strike",
  "swinging strike": "Whiff",
  "swinging strike blocked": "Whiff",
  "swinging pitchout": "Whiff",
  "missed bunt": "Whiff",
  "foul": "Foul",
  "foul tip": "Foul Tip",
  "foul bunt": "Foul",
  "foul pitchout": "Foul",
  "hit by pitch": "Hit by Pitch",
  "hit into play": "Hit Into Play",
  "hit into play no out": "Hit Into Play",
  "hit into play score": "Hit Into Play",
  "hit into play out(s)": "Hit Into Play",
  "single": "Single",
  "double": "Double",
  "triple": "Triple",
  "home run": "Home Run",
  "field out": "Out",
  "force out": "Force Out",
  "grounded into double play": "Double Play",
  "double play": "Double Play",
  "sac fly": "Sacrifice Fly",
  "sac bunt": "Sacrifice Bunt",
  "strikeout": "Strikeout",
  "walk": "Walk",
  "intent walk": "Intentional Walk",
  "intentional walk": "Intentional Walk",
};

function pitchOutcomeLabel(snapshot: PitchingReplayEntry["snapshot"]): string {
  const raw = (snapshot.pitch_call || "").trim();
  if (!raw) return "";
  const normalized = raw.toLowerCase().replace(/_/g, " ").replace(/\s+/g, " ").trim();
  const lookup = PITCH_CALL_LABELS[normalized];
  if (lookup) return lookup;
  return normalized.split(" ").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function hitClassificationLabel(snapshot: PitchingReplayEntry["snapshot"]): string {
  return (snapshot.hit_classification || "").trim();
}

function batterHandedness(snapshot: PitchingReplayEntry["snapshot"]): "L" | "R" | null {
  const raw = (snapshot.batter_handedness || "").trim().toUpperCase();
  if (raw === "L" || raw === "R") return raw;
  return null;
}

function gameSituationLabel(entry: PitchingReplayEntry): string {
  return `${halfInningLabel(entry.snapshot.half, entry.snapshot.inning)} · ${outsLabel(entry.snapshot.outs)} · ${baseStateLabel(entry.snapshot.base_state)}`;
}

function statusLabel(status: string | null | undefined): string {
  return String(status || "STAY").replace(/_/g, " ").toUpperCase();
}

function statusRank(status: string | null | undefined): number {
  const label = statusLabel(status);
  if (label === "DISTRESS") return 4;
  if (label === "PULL NOW") return 3;
  if (label === "PREP") return 2;
  if (label === "WATCH") return 1;
  return 0;
}

function maxStatus(left: string, right: string): string {
  return statusRank(right) > statusRank(left) ? statusLabel(right) : statusLabel(left);
}

function signalClass(status: string): string {
  return statusLabel(status).toLowerCase().replace(/\s+/g, "_");
}

function monotonicStatuses(entries: PitchingReplayEntry[]): string[] {
  let current = entries.some(isRelieverReplayEntry) ? "OK" : "STAY";
  return entries.map((entry) => {
    current = maxStatus(current, replayStatus(entry));
    return current;
  });
}

function baseStateFlags(baseState: string | null | undefined) {
  const value = String(baseState || "").toUpperCase();
  if (/^[01]{3}$/.test(value)) {
    return { first: value[0] === "1", second: value[1] === "1", third: value[2] === "1" };
  }
  return {
    first: value.includes("1") || value.includes("FIRST") || value.includes("1B"),
    second: value.includes("2") || value.includes("SECOND") || value.includes("2B"),
    third: value.includes("3") || value.includes("THIRD") || value.includes("3B"),
  };
}

function auditWindows(summary: PitchingAuditSummaryPayload | null): PitchingAuditWindow[] {
  if (!summary) return [];
  return [
    ...(summary.missed_hook_windows ?? []),
    ...(summary.delayed_change_windows ?? []),
    ...(summary.high_leverage_holdouts ?? []),
    ...(summary.justified_stay_windows ?? []),
  ];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function looseNumber(source: unknown, keys: string[]): number | null {
  const sourceRecord = record(source);
  for (const key of keys) {
    const value = num(sourceRecord[key]);
    if (value != null) return value;
  }
  return null;
}

function featureCategory(feature: string): "Stuff" | "Command and Contact" | "Decision Context" | "Relief Alternative" {
  const key = feature.toLowerCase();
  if (key.includes("relief") || key.includes("bullpen") || key.includes("candidate") || key.includes("option")) return "Relief Alternative";
  if (key.includes("leverage") || key.includes("inning") || key.includes("tto") || key.includes("base") || key.includes("pitch_count") || key.includes("batter")) return "Decision Context";
  if (key.includes("command") || key.includes("zone") || key.includes("strike") || key.includes("contact") || key.includes("location") || key.includes("chase")) return "Command and Contact";
  return "Stuff";
}

function categoryContributorLabel(feature: string): string {
  return `${featureCategory(feature)}: ${featureLabel(feature)}`;
}

function opportunityForPitch(
  entry: PitchingReplayEntry | null,
  opportunities: PreventableRunsOpportunityRow[],
  selectedGameId: string | null,
): PreventableRunsOpportunityRow | null {
  if (!entry || !selectedGameId) return null;
  const gameRows = opportunities.filter((row) => row.gameId === selectedGameId);
  if (gameRows.length === 0) return null;
  const pitcherRows = gameRows.filter((row) => {
    if (row.pitcherId && String(row.pitcherId) === String(entry.snapshot.pitcher_id)) return true;
    return row.pitcherName === entry.snapshot.pitcher_name;
  });
  const rows = pitcherRows.length ? pitcherRows : gameRows;
  const currentPitch = pitchCount(entry);
  return rows
    .slice()
    .sort((left, right) => {
      const leftDistance = left.pitchCount == null ? Number.POSITIVE_INFINITY : Math.abs(left.pitchCount - currentPitch);
      const rightDistance = right.pitchCount == null ? Number.POSITIVE_INFINITY : Math.abs(right.pitchCount - currentPitch);
      return leftDistance - rightDistance;
    })[0] ?? null;
}

function preventableRunsForPitch(entry: PitchingReplayEntry | null, opportunity: PreventableRunsOpportunityRow | null): number | null {
  if (!entry) return null;
  return (
    opportunity?.projectedPreventableRuns ??
    opportunity?.decisionDelta ??
    looseNumber(entry.recommendation, [
      "projectedPreventableRuns",
      "projected_preventable_runs",
      "preventableRuns",
      "preventable_runs",
      "calibratedPreventableRuns",
      "calibrated_preventable_runs",
      "projectedRunsSaved",
      "projected_runs_saved",
      "estimatedRunsSaved",
      "estimated_runs_saved",
    ])
  );
}

function parseCsvList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function teamCsv(value: string): string[] {
  return parseCsvList(value).map((item) => item.toUpperCase());
}

function csvHasTeam(value: string, team: string): boolean {
  return teamCsv(value).includes(team.toUpperCase());
}

function csvSetTeam(value: string, team: string, enabled: boolean): string {
  const normalizedTeam = team.toUpperCase();
  const current = teamCsv(value);
  const next = current.filter((item) => item !== normalizedTeam);
  if (enabled) next.push(normalizedTeam);
  return Array.from(new Set(next)).join(", ");
}

function actionPointCopy(pitcher: PitchingRecapPitcher | null): string {
  if (!pitcher) return "No starter action point was generated for this game.";
  if (pitcher.first_pull_now_inning != null) {
    return `Pull Now triggered in the ${ordinal(pitcher.first_pull_now_inning)} at pitch ${pitcher.first_pull_now_pitch_count ?? "—"}.`;
  }
  if (pitcher.first_alert_inning != null) {
    return `${statusLabel(pitcher.first_alert_status)} triggered in the ${ordinal(pitcher.first_alert_inning)} at pitch ${pitcher.first_alert_pitch_count ?? "—"}.`;
  }
  return "No model action point was generated for this starter.";
}

function exitAndDamageCopy(pitcher: PitchingRecapPitcher | null): string {
  if (!pitcher) return "Actual exit timing and scoring are unavailable.";
  const exit =
    pitcher.actual_exit_inning == null
      ? "Actual pull timing unavailable"
      : `Starter was pulled in the ${ordinal(pitcher.actual_exit_inning)} at pitch ${pitcher.actual_exit_pitch_count ?? "—"}`;
  const runs =
    pitcher.runs_allowed_after_signal == null
      ? "runs after the model signal unavailable"
      : `${pitcher.runs_allowed_after_signal} run${pitcher.runs_allowed_after_signal === 1 ? "" : "s"} scored after the model signal`;
  const pitchesAfter = looseNumber(pitcher, ["pitches_after_signal", "pitchesAfterSignal"]);
  const battersAfter = looseNumber(pitcher, ["batters_after_signal", "battersAfterSignal"]);
  const hold =
    pitchesAfter != null || battersAfter != null
      ? ` Manager held him ${pitchesAfter != null ? `${pitchesAfter} pitch${pitchesAfter === 1 ? "" : "es"}` : ""}${pitchesAfter != null && battersAfter != null ? " / " : ""}${battersAfter != null ? `${battersAfter} batter${battersAfter === 1 ? "" : "s"}` : ""} after the signal.`
      : "";
  return `${exit}; ${runs}.${hold}`;
}

function pullWindowMetrics(entry: PitchingReplayEntry | null): { stuff: string; decay: string; degradation: string } {
  if (!entry) {
    return { stuff: UNAVAILABLE, decay: UNAVAILABLE, degradation: UNAVAILABLE };
  }
  const state = replayState(entry);
  const decay = (state.inning_decay_factor ?? 0) + (state.tto_decay_factor ?? 0);
  return {
    stuff: `${stuffScore(entry)}/100`,
    decay: fmtNumber(decay, 2),
    degradation: fmtNumber(state.enhanced_degradation_score ?? state.degradation_score, 2),
  };
}

function degradationLevel(score: number | null): string {
  if (score == null) return UNAVAILABLE;
  if (score >= 1.05) return "critical";
  if (score >= 0.82) return "high";
  if (score >= 0.65) return "elevated";
  if (score >= 0.45) return "watch";
  return "stable";
}

function replayRecommendationSummary(entry: PitchingReplayEntry | null): string {
  if (!entry) return "No model explanation is attached to this pitch.";
  const recommendation = record(entry.recommendation);
  const summary = String(recommendation.gm_summary ?? recommendation.decision_summary ?? "").trim();
  if (summary) return summary;
  const driver = String(recommendation.trigger_driver_type ?? "").trim();
  if (driver === "game_context") {
    return "The pitcher's mound condition was not independently extreme, but the game state made the same signs more urgent.";
  }
  if (driver === "pitcher_degradation") {
    return "The signal was driven primarily by pitcher condition before accounting for leverage.";
  }
  if (driver === "relief_alternative") {
    return "The model saw a better available relief path than continuing with the starter.";
  }
  if (driver === "workload_guardrail") {
    return "The starter had signs of stress, but workload and timing guardrails moderated the recommendation.";
  }
  return "The signal combined pitcher condition, game context, and available relief alternatives.";
}

function replayConditionSummary(entry: PitchingReplayEntry | null): string {
  if (!entry) return UNAVAILABLE;
  const recommendation = record(entry.recommendation);
  const state = replayState(entry);
  const score =
    num(recommendation.independent_degradation_score) ??
    num(state.enhanced_degradation_score) ??
    num(state.degradation_score);
  const level = String(recommendation.independent_degradation_level ?? "").trim() || degradationLevel(score);
  return score == null ? UNAVAILABLE : `${fmtNumber(score, 2)} · ${level}`;
}

function replayUrgencySummary(entry: PitchingReplayEntry | null): string {
  if (!entry) return UNAVAILABLE;
  const recommendation = record(entry.recommendation);
  const score = num(recommendation.leveraged_degradation_score);
  const level = String(recommendation.leveraged_degradation_level ?? "").trim();
  const leverage = fmtNumber(entry.snapshot.leverage_index, 2);
  if (score != null || level) {
    return `${score == null ? "Context-adjusted" : fmtNumber(score, 2)} · ${level || degradationLevel(score)} · LI ${leverage}`;
  }
  return `LI ${leverage} · ${statusLabel(entry.recommendation.status)} urgency`;
}

function replaySignalDwellSummary(entries: PitchingReplayEntry[], statuses: string[], selectedIndex: number): string {
  if (entries.length === 0) return UNAVAILABLE;
  const cappedIndex = Math.min(Math.max(selectedIndex, 0), entries.length - 1);
  const currentPitch = pitchCount(entries[cappedIndex]);
  const parts: string[] = [];
  for (const label of ["WATCH", "PREP", "PULL NOW"]) {
    const targetRank = statusRank(label);
    const firstIndex = statuses.findIndex((status, index) => index <= cappedIndex && statusRank(status) >= targetRank);
    if (firstIndex < 0) continue;
    const firstPitch = pitchCount(entries[firstIndex]);
    const pitchesInZone = Math.max(0, currentPitch - firstPitch);
    parts.push(`${label} since pitch ${firstPitch}${pitchesInZone > 0 ? ` (${pitchesInZone} pitches)` : ""}`);
  }
  return parts.length ? parts.join(" · ") : "No action signal reached yet.";
}

function relieverRssLabel(pitcher: PitchingRecapPitcher): string {
  if (pitcher.rss_score == null) return UNAVAILABLE;
  return `${statusLabel(pitcher.rss_label)} ${fmtNumber(pitcher.rss_score, 2)}`;
}

function relieverRssTimingCopy(pitcher: PitchingRecapPitcher): string {
  if (pitcher.first_alert_inning == null) {
    return pitcher.rss_score == null
      ? "No RSS score was returned for this appearance."
      : "RSS was measured for the appearance; pitch-level trigger timing was not reconstructed.";
  }
  return `${statusLabel(pitcher.first_alert_status)} in the ${ordinal(pitcher.first_alert_inning)} at pitch ${pitcher.first_alert_pitch_count ?? "—"}.`;
}

function relieverOutcomeCopy(pitcher: PitchingRecapPitcher): string {
  const runs = pitcher.runs_allowed_total == null ? "runs unavailable" : `${pitcher.runs_allowed_total} R`;
  const innings = pitcher.innings_pitched == null ? "IP unavailable" : `${fmtNumber(pitcher.innings_pitched, 1)} IP`;
  const exit =
    pitcher.actual_exit_inning == null
      ? "exit timing unavailable"
      : `exited in the ${ordinal(pitcher.actual_exit_inning)} at pitch ${pitcher.actual_exit_pitch_count ?? "—"}`;
  const after =
    pitcher.runs_allowed_after_first_alert == null
      ? "Runs after RSS trigger unavailable because pitch-level timing is unavailable."
      : `${pitcher.runs_allowed_after_first_alert} run${pitcher.runs_allowed_after_first_alert === 1 ? "" : "s"} after RSS trigger.`;
  return `${runs} in ${innings}; ${exit}. ${after}`;
}

function relieverRssComponent(pitcher: PitchingRecapPitcher, key: string): number | null {
  return looseNumber(pitcher.bullpen_signal, [key]);
}

function relieverRssComponents(pitcher: PitchingRecapPitcher): Array<{ label: string; value: number | null }> {
  return [
    { label: "Stuff", value: relieverRssComponent(pitcher, "rss_stuff") },
    { label: "Command", value: relieverRssComponent(pitcher, "rss_command") },
    { label: "Outcome", value: relieverRssComponent(pitcher, "rss_outcome") },
    { label: "Handoff", value: relieverRssComponent(pitcher, "rss_handoff_risk") },
    { label: "Usage", value: relieverRssComponent(pitcher, "rss_usage_fatigue") },
  ];
}

function entryEventLabel(
  selected: PitchingReplayEntry,
  previous: PitchingReplayEntry | null,
  displayStatus: string,
  previousStatus: string,
  replay: PitchingReplayResponse,
): { title: string; detail: string; tone: "neutral" | "gold" | "bad" } {
  const scoreChanged =
    previous != null &&
    (selected.snapshot.home_score !== previous.snapshot.home_score || selected.snapshot.away_score !== previous.snapshot.away_score);
  const signalAdvanced = previous != null && statusRank(displayStatus) > statusRank(previousStatus);
  if (scoreChanged) {
    return {
      title: "Score changed",
      detail: `The game moved to ${scoreForEntry(selected, replay)} after this sequence.`,
      tone: "bad",
    };
  }
  if (signalAdvanced) {
    return {
      title: `Signal advanced to ${displayStatus}`,
      detail: `The model moved up because the combined mound evidence and game context crossed the ${displayStatus.toLowerCase()} threshold.`,
      tone: statusRank(displayStatus) >= statusRank("PULL NOW") ? "bad" : "gold",
    };
  }
  return {
    title: "",
    detail: `${displayPersonName(selected.snapshot.pitcher_name)} at pitch ${pitchCount(selected)} in the ${halfInningLabel(selected.snapshot.half, selected.snapshot.inning)}.`,
    tone: "neutral",
  };
}

function explicitMatrixCell(value: unknown): MatrixCell | null {
  const clean = String(value ?? "")
    .toLowerCase()
    .replace(/[\s_-]+/g, " ")
    .trim();
  if (!clean) return null;
  if (
    clean.includes("tandem") ||
    clean.includes("earlier hook") ||
    clean.includes("early hook") ||
    clean.includes("change earlier") ||
    clean.includes("relief path")
  ) {
    return "tandem";
  }
  if (clean.includes("push") || clean.includes("do not overreact") || clean.includes("hold starter")) return "push";
  if (clean.includes("workload")) return "workload";
  if (clean.includes("standard")) return "standard";
  return null;
}

function matrixCellForWindow(window: PitchingAuditWindow): MatrixCell {
  const recommendation = record(window.recommendation);
  const explicit =
    explicitMatrixCell(window.primary_bucket) ??
    explicitMatrixCell(window.decision_bucket) ??
    explicitMatrixCell(window.allocation_bucket) ??
    explicitMatrixCell(window.deployment_bucket) ??
    explicitMatrixCell(window.matrix_cell) ??
    explicitMatrixCell(window.bucket) ??
    explicitMatrixCell(window.review_bucket) ??
    explicitMatrixCell(recommendation.primary_bucket) ??
    explicitMatrixCell(recommendation.decision_bucket) ??
    explicitMatrixCell(recommendation.allocation_bucket);
  if (explicit) return explicit;

  const starter = record(window.starter);
  const candidate = record(window.top_candidate);
  const starterAbove = (num(starter.degradation_score) ?? 2) < 1.15;
  const penAbove = Math.max(num(candidate.net_option_score) ?? 0, num(candidate.direct_matchup_fit) ?? 0) >= 0.45;
  if (starterAbove && penAbove) return "standard";
  if (!starterAbove && penAbove) return "tandem";
  if (starterAbove && !penAbove) return "push";
  return "workload";
}

const PRIMARY_MATRIX_CELL_ORDER: MatrixCell[] = ["workload", "push", "tandem", "standard"];

function primaryMatrixCellForGame(windows: PitchingAuditWindow[]): MatrixCell {
  const cells = new Set(windows.map(matrixCellForWindow));
  for (const cell of PRIMARY_MATRIX_CELL_ORDER) {
    if (cells.has(cell)) return cell;
  }
  return "standard";
}

function gameLabel(game: EnterpriseGameSummary | null): string {
  if (!game) return "Select game";
  return `${game.away_team} @ ${game.home_team} · ${game.date}`;
}

function selectedTeamPitchers(recap: PitchingGameRecap | null, team: Team) {
  return recap?.starters.filter((pitcher) => pitcher.team === team.abbr) ?? [];
}

function pitcherRoleLabel(pitcher: PitchingRecapPitcher): string {
  return String(pitcher.role || "Starter").toLowerCase() === "reliever" ? "Reliever" : "Starter";
}

function teamPitcherRecapCopy(pitcher: PitchingRecapPitcher | null): string {
  if (!pitcher) return "No pitcher-specific recap has been generated for this club yet.";
  const firstAction =
    pitcher.first_pull_now_inning != null
      ? `Pull Now in the ${ordinal(pitcher.first_pull_now_inning)} at pitch ${pitcher.first_pull_now_pitch_count ?? "—"}`
      : pitcher.first_alert_inning != null
        ? `${statusLabel(pitcher.first_alert_status)} in the ${ordinal(pitcher.first_alert_inning)} at pitch ${pitcher.first_alert_pitch_count ?? "—"}`
        : "No clear action point";
  const result =
    pitcher.runs_allowed_after_signal == null
      ? "post-signal scoring unavailable"
      : `${pitcher.runs_allowed_after_signal} run${pitcher.runs_allowed_after_signal === 1 ? "" : "s"} after the signal`;
  const exit =
    pitcher.actual_exit_inning == null
      ? "exit timing unavailable"
      : `exited in the ${ordinal(pitcher.actual_exit_inning)} at pitch ${pitcher.actual_exit_pitch_count ?? "—"}`;
  return `${firstAction}; ${exit}; ${result}.`;
}

function recapOpponent(recap: PitchingGameRecap | null, team: Team): string {
  if (!recap) return "Opponent";
  if (recap.home_team === team.abbr) return recap.away_team;
  if (recap.away_team === team.abbr) return recap.home_team;
  return recap.away_team === team.abbr ? recap.home_team : recap.away_team;
}

function recapScoreLine(recap: PitchingGameRecap | null): string {
  if (!recap) return "Final score unavailable";
  const awayScore = recap.final_away_score == null ? "—" : String(recap.final_away_score);
  const homeScore = recap.final_home_score == null ? "—" : String(recap.final_home_score);
  return `${recap.away_team} ${awayScore}, ${recap.home_team} ${homeScore}`;
}

function buildBriefingPlainText(response: PitchingRecapEmailResponse, team: Team): string {
  if (response.text) return response.text;
  const recap = response.recap;
  const pitchers = selectedTeamPitchers(recap, team);
  const starters = pitchers.filter((pitcher) => pitcherRoleLabel(pitcher) !== "Reliever");
  const relievers = pitchers.filter((pitcher) => pitcherRoleLabel(pitcher) === "Reliever");
  const keyPitcher = starters.find((pitcher) => pitcher.first_pull_now_inning != null || pitcher.first_alert_inning != null) ?? starters[0] ?? pitchers[0] ?? null;
  const lines = [
    response.subject ?? `brAIn — ${team.abbr} Recap`,
    formatDateText(recap.date),
    recapScoreLine(recap),
    "",
    "Mound Signal",
    actionPointCopy(keyPitcher),
    exitAndDamageCopy(keyPitcher),
    "",
    "Pitchers",
    ...pitchers.map(
      (pitcher) =>
        `${pitcher.pitcher_name} (${pitcherRoleLabel(pitcher)}): ${fmtNumber(pitcher.innings_pitched, 1)} IP, ${pitcher.pitch_count ?? "—"} pitches, ${pitcher.runs_allowed_total ?? "—"} R`,
    ),
  ];
  if (relievers.length > 0) {
    lines.push("", "Bullpen RSS");
    lines.push(...relievers.map((pitcher) => `${pitcher.pitcher_name}: ${relieverRssLabel(pitcher)} — ${relieverOutcomeCopy(pitcher)}`));
  }
  return lines.join("\n");
}

function TeamLogo({ abbr }: { abbr: string }) {
  const src = teamLogoUrl(abbr);
  return <span className="team-logo">{src ? <img src={src} alt={`${abbr} logo`} /> : abbr}</span>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function KPI({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail: string; tone?: "neutral" | "good" | "bad" | "gold" }) {
  return (
    <article className={`kpi kpi--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function SourceTag({ label, source }: { label: string; source: "official" | "model" | "rule" | "unavailable" }) {
  return <span className={`source-tag source-tag--${source}`}>{label}</span>;
}

function factorRole(
  percent: number | null | undefined,
  tone: "neutral" | "good" | "warn" | "bad" | "gold",
): "DRIVER" | "HELD UP" | "WATCH" | null {
  if (percent == null) return null;
  const pct = Math.max(0, Math.min(1, percent));
  if (tone === "bad" && pct >= 0.5) return "DRIVER";
  if (tone === "warn" && pct >= 0.55) return "DRIVER";
  if (tone === "gold" && pct >= 0.6) return "WATCH";
  if (tone === "good" && pct >= 0.5) return "HELD UP";
  return null;
}

function GaugeMetric({
  label,
  value,
  detail,
  percent,
  tone = "neutral",
  role,
}: {
  label: string;
  value: string;
  detail?: string;
  percent?: number;
  tone?: "neutral" | "good" | "warn" | "bad" | "gold";
  role?: "DRIVER" | "HELD UP" | "WATCH" | null;
}) {
  const width = percent == null ? 0 : Math.round(clamp(percent) * 100);
  const roleSlug = role ? role.toLowerCase().replace(" ", "-") : null;
  const roleClass = roleSlug ? `gauge-role-pill gauge-role-pill--${roleSlug}` : null;
  const cardClass = `evidence-gauge evidence-gauge--${tone}${roleSlug ? ` evidence-gauge--role-${roleSlug}` : ""}`;
  return (
    <div className={cardClass}>
      {roleClass ? <span className={roleClass}>{role}</span> : null}
      <div className="evidence-gauge-head">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      {percent != null ? (
        <div className="gauge-track" aria-hidden="true">
          <i style={{ width: `${width}%` }} />
        </div>
      ) : null}
      {detail ? <em>{detail}</em> : null}
    </div>
  );
}

function StuffConditionCard({ body }: { body: string }) {
  if (!body) return null;
  return (
    <div className="stuff-condition-card">
      <span className="stuff-condition-card__label">Pitcher-Only Condition</span>
      <p>{body}</p>
    </div>
  );
}

function TrendSparkline({ label, value, detail, points }: { label: string; value: string; detail?: string; points: Array<number | null | undefined> }) {
  const numbers = points.filter((point): point is number => typeof point === "number" && Number.isFinite(point));
  if (numbers.length < 2) {
    return <GaugeMetric label={label} value={value} detail={detail ?? "Trend unavailable"} />;
  }
  const width = 180;
  const height = 46;
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  const range = Math.max(0.01, max - min);
  const path = numbers
    .map((point, index) => {
      const x = (index / Math.max(1, numbers.length - 1)) * width;
      const y = height - ((point - min) / range) * (height - 8) - 4;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <div className="sparkline-card">
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        {detail ? <em>{detail}</em> : null}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} trend`}>
        <path className="sparkline-baseline" d={`M0 ${height - 4} H${width}`} />
        <path className="sparkline-path" d={path} />
      </svg>
    </div>
  );
}

function MiniCurve({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="small-muted">Trajectory unavailable</span>;
  const width = 220;
  const height = 72;
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(1, values.length - 1)) * width;
      const y = height - ((value - 20) / 80) * height;
      return `${x},${Math.max(5, Math.min(height - 5, y))}`;
    })
    .join(" ");
  return (
    <svg className="mini-curve" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Stuff trajectory">
      <path d={`M0 ${height * 0.5} H${width}`} />
      <polyline points={points} />
    </svg>
  );
}

function OutsDots({ outs }: { outs: number | null | undefined }) {
  return (
    <div className="outs">
      {[0, 1, 2].map((index) => (
        <span key={index} className={(outs ?? 0) > index ? "filled" : ""} />
      ))}
    </div>
  );
}

function BasesDiamond({ baseState }: { baseState: string | null | undefined }) {
  const bases = baseStateFlags(baseState);
  return (
    <div className="bases">
      <i className={bases.second ? "filled second" : "second"} />
      <i className={bases.third ? "filled third" : "third"} />
      <i className={bases.first ? "filled first" : "first"} />
    </div>
  );
}

function formatCount(snapshot: PitchingReplayEntry["snapshot"]): string {
  const b = typeof snapshot.balls === "number" ? snapshot.balls : null;
  const s = typeof snapshot.strikes === "number" ? snapshot.strikes : null;
  return b != null && s != null ? `${b}-${s}` : "—";
}

function PitchPlot({
  entries,
  selectedIndex,
  onSelect,
}: {
  entries: PitchingReplayEntry[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const start = Math.max(0, selectedIndex + 1 - 80);
  const plotted = entries.slice(start, selectedIndex + 1);
  return (
    <div className="strike-zone-card">
      <div className="plate-zone">
        <div className="zone-box" />
        {plotted.map((entry, localIdx) => {
          const entriesIdx = start + localIdx;
          const px = typeof entry.snapshot.px === "number" ? entry.snapshot.px : 0;
          const pz = typeof entry.snapshot.pz === "number" ? entry.snapshot.pz : 2.5;
          const left = Math.max(7, Math.min(93, 50 + px * 18));
          const top = Math.max(7, Math.min(93, 84 - pz * 19));
          const selected = entriesIdx === selectedIndex;
          return (
            <button
              key={`${entry.snapshot.pitch_id}-${entriesIdx}`}
              type="button"
              className={selected ? "pitch-dot selected" : "pitch-dot"}
              style={{ left: `${left}%`, top: `${top}%` }}
              onClick={() => onSelect(entriesIdx)}
              title={`Pitch ${pitchCount(entry)}`}
              aria-label={`Jump to pitch ${pitchCount(entry)}`}
            >
              {selected ? pitchCount(entry) : ""}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SignalTimeline({
  entries,
  statuses,
  selectedIndex,
  onSelect,
}: {
  entries: PitchingReplayEntry[];
  statuses: string[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  if (entries.length === 0) return null;
  return (
    <div className="signal-timeline" aria-label="Pitch-by-pitch signal timeline">
      {entries.map((entry, index) => {
        const status = statuses[index] ?? statusLabel(entry.recommendation.status);
        const selected = index === selectedIndex;
        return (
          <button
            key={`${entry.snapshot.pitch_id}-${index}`}
            type="button"
            className={`timeline-segment timeline-${signalClass(status)}${selected ? " selected" : ""}`}
            title={`Pitch ${pitchCount(entry)} · ${status}`}
            aria-label={`Pitch ${pitchCount(entry)} signal ${status}`}
            onClick={() => onSelect(index)}
          />
        );
      })}
    </div>
  );
}

function TopNav({
  team,
  workflow,
  onRefresh,
  onTeamChange,
  onWorkflowChange,
}: {
  team: Team | null;
  workflow: Workflow;
  loadState: LoadState;
  onRefresh: () => void;
  onTeamChange: (team: Team) => void;
  onWorkflowChange: (workflow: Workflow) => void;
}) {
  const accents = team ? teamAccents(team.abbr) : null;
  const teamColor = accents?.primary ?? "#ffffff";
  return (
    <header className="top-nav">
      <div className="top-nav__brand-group">
        <a className="top-nav__brand" href="/" aria-label="Baseball brAIn">
          <svg className="top-nav__brain-svg" viewBox="0 0 565 115" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Baseball brAIn">
            <text x="20" y="82" fontFamily="'Helvetica Neue',Helvetica,Arial,sans-serif" fontSize="36" fontWeight="300" letterSpacing="6" fill="#FFFFFF">BASEBALL</text>
            <text x="322" y="82" fontFamily="'Helvetica Neue',Helvetica,Arial,sans-serif" fontSize="84" fontWeight="700" letterSpacing="-1" fill="#FFFFFF" fillOpacity="0.7">
              <tspan fillOpacity="0.7">br</tspan>
              <tspan fill={teamColor} fillOpacity="1">AI</tspan>
              <tspan fillOpacity="0.7">n</tspan>
            </text>
            <polygon points="277,17 312,52 277,87 242,52" fill="none" stroke="#FFFFFF" strokeWidth="2.5" strokeLinejoin="miter" />
            <line x1="269" y1="52" x2="285" y2="52" stroke={teamColor} strokeWidth="1.8" strokeLinecap="round" />
            <line x1="277" y1="44" x2="277" y2="60" stroke={teamColor} strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </a>
        {team ? (
          <div className="top-nav__team">
            <span className="top-nav__team-logo"><TeamLogo abbr={team.abbr} /></span>
            <h1 className="top-nav__team-name" style={{ color: teamColor }}>{team.name.toUpperCase()}</h1>
          </div>
        ) : null}
      </div>

      <nav className="top-nav__tabs" aria-label="Primary workflows">
        {WORKFLOWS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`top-nav__tab${workflow === item.id ? " top-nav__tab--active" : ""}`}
            onClick={() => onWorkflowChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="top-nav__actions">
        <label className="top-nav__club-chip">
          <span>{team?.club ?? "Select Club"}</span>
          <Plus size={14} aria-hidden="true" />
          <select
            className="top-nav__club-select"
            value={team?.abbr ?? ""}
            onChange={(event) => {
              const next = MLB_TEAMS.find((item) => item.abbr === event.target.value);
              if (next) onTeamChange(next);
            }}
            aria-label="Select club"
          >
            {!team ? <option value="" disabled>Select Club</option> : null}
            {MLB_TEAMS.map((item) => (
              <option key={item.abbr} value={item.abbr}>{item.name}</option>
            ))}
          </select>
        </label>
        <button type="button" className="top-nav__data-sync" onClick={onRefresh}>
          <ArrowsClockwise size={14} aria-hidden="true" />
          <span>Data Sync</span>
        </button>
        <div className="top-nav__profile" aria-label="Admin profile">A</div>
      </div>
    </header>
  );
}

function useRunSavingBoard({ league, team, limit }: { league: "mlb" | "triple_a"; team?: string; limit?: number }) {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [payload, setPayload] = useState<RunSavingBoardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadState("loading");
    setError(null);
    try {
      const data = await fetchRunSavingBoard({ league, team, limit });
      setPayload(data);
      setLoadState("ready");
    } catch (caught) {
      if (caught instanceof ApiConfigurationError) {
        setLoadState("missing-config");
      } else {
        setError(caught instanceof Error ? caught.message : String(caught));
        setLoadState("error");
      }
    }
  }, [league, team, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  return { loadState, payload, error, reload: load };
}

function usePreventableRunsOpportunities({
  season,
  team,
  gameId,
  limit,
  scope,
}: {
  season: string;
  team: string;
  gameId?: string | null;
  limit: number;
  scope?: "top" | "game_matrix" | "all_games";
}) {
  const [payload, setPayload] = useState<PreventableRunsOpportunitiesPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPreventableRunsOpportunities({ season, team, gameId, limit, scope });
      setPayload(data);
    } catch (caught) {
      setPayload(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [season, team, gameId, limit, scope]);

  useEffect(() => {
    void load();
  }, [load]);

  return { payload, error, loading, reload: load };
}

type RunExposureLabel = "run exposure" | "decision edge" | "impact";

type CalibratedGameGroup = {
  best: PreventableRunsOpportunityRow;
  windows: PreventableRunsOpportunityRow[];
  decisionDelta: number | null;
  runExposure: number | null;
  runExposureLabel: RunExposureLabel;
};

type CalibratedGameOpportunity = {
  row: PreventableRunsOpportunityRow;
  windows: PreventableRunsOpportunityRow[];
  windowCount: number;
  pitcherCount: number;
  cell: MatrixCell;
  decisionDelta: number | null;
  runExposure: number | null;
  runExposureLabel: RunExposureLabel;
};

type SeasonAuditGameOpportunity = {
  row: PitchingAuditWindow;
  windowCount: number;
  pitcherCount: number;
  cell: MatrixCell;
  calibratedRow?: PreventableRunsOpportunityRow | null;
  calibratedRows?: PreventableRunsOpportunityRow[];
  calibratedDecisionDelta?: number | null;
  calibratedRunExposure?: number | null;
  calibratedRunExposureLabel?: RunExposureLabel;
};

function reviewPointLabel(row: PreventableRunsOpportunityRow): string {
  const details = [halfInningLabel(row.half, row.inning), outsLabel(row.outs), baseStateLabel(row.baseState)];
  if (row.pitchCount != null) details.push(`pitch ${row.pitchCount}`);
  return details.join(" · ");
}

function reviewReasonLabels(row: PreventableRunsOpportunityRow): string[] {
  const reasons: string[] = [];
  for (const feature of row.topFeatures ?? []) {
    const label = categoryContributorLabel(feature.feature);
    if (!reasons.includes(label)) reasons.push(label);
  }
  const baseFlags = baseStateFlags(row.baseState);
  const runners = Number(baseFlags.first) + Number(baseFlags.second) + Number(baseFlags.third);
  if (runners >= 2 && !reasons.includes("Runners in scoring position")) reasons.push("Runners in scoring position");
  else if (runners === 1 && !reasons.includes("Traffic on base")) reasons.push("Traffic on base");
  if ((row.leverageIndex ?? 0) >= 1.5 && !reasons.includes("Important game state")) reasons.push("Important game state");
  if ((row.degradationScore ?? row.productionDegradation ?? row.normalizedDegradation ?? 0) >= 1 && !reasons.includes("Starter was slipping")) {
    reasons.push("Starter was slipping");
  }
  if ((row.decayVelocity ?? 0) > 0 || (row.decayAcceleration ?? 0) > 0) reasons.push("Stuff trending down");
  return reasons.slice(0, 4);
}

function driverChipClass(reason: string): string {
  const value = reason.toLowerCase();
  if (value.includes("runner") || value.includes("traffic") || value.includes("base")) return "driver-chip driver-chip--base";
  if (value.includes("leverage") || value.includes("game state") || value.includes("urgency")) return "driver-chip driver-chip--leverage";
  if (
    value.includes("slipping") ||
    value.includes("stuff") ||
    value.includes("velocity") ||
    value.includes("spin") ||
    value.includes("command") ||
    value.includes("whiff") ||
    value.includes("decline")
  ) {
    return "driver-chip driver-chip--stuff";
  }
  if (value.includes("relief") || value.includes("bullpen")) return "driver-chip driver-chip--relief";
  if (value.includes("workload") || value.includes("rest")) return "driver-chip driver-chip--workload";
  return "driver-chip";
}

function DriverChip({ reason }: { reason: string }) {
  const value = reason.toLowerCase();
  const Icon =
    value.includes("runner") || value.includes("traffic") || value.includes("base")
      ? Users
      : value.includes("slipping") || value.includes("stuff") || value.includes("velocity") || value.includes("spin") || value.includes("command") || value.includes("decline")
        ? TrendDown
        : null;

  return (
    <span className={driverChipClass(reason)}>
      {Icon ? <Icon size={12} aria-hidden="true" /> : null}
      {reason}
    </span>
  );
}

function matrixBucketCopy(cell: MatrixCell): { title: string; detail: string } {
  if (cell === "tandem") {
    return {
      title: "Tandem opportunities",
      detail: "The starter was fading and the bullpen path deserved a closer look.",
    };
  }
  if (cell === "push") {
    return {
      title: "Push-the-starter cases",
      detail: "The model saw fewer gains from changing pitchers, usually because the alternative was not clearly better.",
    };
  }
  if (cell === "workload") {
    return {
      title: "Workload-management cases",
      detail: "The run-prevention difference was narrow, so the decision shifts toward rest, availability, and roster planning.",
    };
  }
  return {
    title: "Standard usage cases",
    detail: "The observed decision generally matched the model's staff-allocation read.",
  };
}

function matrixBucketStatLabel(cell: MatrixCell): string {
  if (cell === "tandem") return "Tandem opportunities";
  if (cell === "push") return "Push-the-starter cases";
  if (cell === "workload") return "Workload cases";
  return "Standard usage cases";
}

function matrixBucketShortLabel(cell: MatrixCell): string {
  if (cell === "tandem") return "Tandem";
  if (cell === "push") return "Push starter";
  if (cell === "workload") return "Workload";
  return "Standard";
}

function matrixBucketDefinition(cell: MatrixCell): string {
  if (cell === "tandem") return "Starter is fading and relief path is optimal";
  if (cell === "push") return "Starter is stronger than available alternatives";
  if (cell === "workload") return "Starter and alternatives are both sub-optimal";
  return "Starter rates well and bullpen alternative is also usable";
}

function pitcherInitials(name: string): string {
  const clean = name.trim();
  if (!clean) return "P";
  if (clean.includes(",")) {
    const [last, first] = clean.split(",").map((part) => part.trim()).filter(Boolean);
    return `${first?.[0] ?? ""}${last?.[0] ?? ""}`.toUpperCase() || "P";
  }
  return clean
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "P";
}

function allocationCellForOpportunity(row: PreventableRunsOpportunityRow): MatrixCell {
  const starterDegradation = row.normalizedDegradation;
  const bullpenValue = row.bestRelieverValueNextWindow;
  if (starterDegradation != null && bullpenValue != null) {
    const starterAboveAverage = starterDegradation < 0.45;
    const bullpenAboveAverage = bullpenValue >= 0.65;
    if (starterAboveAverage && bullpenAboveAverage) return "standard";
    if (!starterAboveAverage && bullpenAboveAverage) return "tandem";
    if (starterAboveAverage && !bullpenAboveAverage) return "push";
    return "workload";
  }

  const explicitCell = explicitAllocationCellForOpportunity(row);
  if (explicitCell) return explicitCell;

  return "standard";
}

function opportunityRaw(row: PreventableRunsOpportunityRow | null | undefined): Record<string, unknown> {
  return record(row?.raw ?? row);
}

function explicitAllocationCellForOpportunity(row: PreventableRunsOpportunityRow): MatrixCell | null {
  const extra = opportunityRaw(row);
  return (
    explicitMatrixCell(extra.primary_bucket) ??
    explicitMatrixCell(extra.primaryBucket) ??
    explicitMatrixCell(extra.decision_bucket) ??
    explicitMatrixCell(extra.decisionBucket) ??
    explicitMatrixCell(extra.allocation_bucket) ??
    explicitMatrixCell(extra.allocationBucket) ??
    explicitMatrixCell(extra.deployment_bucket) ??
    explicitMatrixCell(extra.deploymentBucket) ??
    explicitMatrixCell(extra.matrix_cell) ??
    explicitMatrixCell(extra.matrixCell) ??
    explicitMatrixCell(extra.bucket) ??
    explicitMatrixCell(extra.review_bucket) ??
    explicitMatrixCell(extra.reviewBucket) ??
    explicitMatrixCell(extra.decision_type) ??
    explicitMatrixCell(extra.decisionType) ??
    explicitMatrixCell(extra.allocation_cell) ??
    explicitMatrixCell(extra.allocationCell) ??
    explicitMatrixCell(row.allocationBucket) ??
    explicitMatrixCell(extra.allocationBucket) ??
    explicitMatrixCell(extra.allocation_bucket) ??
    explicitMatrixCell(extra.primary_decision_type) ??
    explicitMatrixCell(extra.primaryDecisionType)
  );
}

function opportunityDecisionDelta(row: PreventableRunsOpportunityRow | null | undefined): number | null {
  if (!row) return null;
  const extra = opportunityRaw(row);
  return (
    row.decisionDelta ??
    num(extra.decision_delta) ??
    num(extra.decisionDelta) ??
    num(extra.relief_edge) ??
    num(extra.reliefEdge) ??
    num(extra.staff_allocation_edge) ??
    num(extra.staffAllocationEdge)
  );
}

function primaryExplicitAllocationCellForOpportunityRows(rows: PreventableRunsOpportunityRow[]): MatrixCell | null {
  const cells = new Set(
    rows.map(explicitAllocationCellForOpportunity).filter((cell): cell is MatrixCell => cell != null),
  );
  for (const cell of PRIMARY_MATRIX_CELL_ORDER) {
    if (cells.has(cell)) return cell;
  }
  return null;
}

function primaryAllocationCellForGame(rows: PreventableRunsOpportunityRow[]): MatrixCell {
  const cells = new Set(rows.map(allocationCellForOpportunity));
  for (const cell of PRIMARY_MATRIX_CELL_ORDER) {
    if (cells.has(cell)) return cell;
  }
  return "standard";
}

function CalibratedOpportunityRow({
  opportunity,
  onOpenGameAudit,
}: {
  opportunity: CalibratedGameOpportunity;
  onOpenGameAudit: (gameId: string) => void;
}) {
  const { row, windowCount, pitcherCount } = opportunity;
  const reviewReasons = reviewReasonLabels(row);
  const priority = Math.round((row.calibratedPreventableSignal ?? row.projectedDamageProbability ?? 0) * 100);
  const reviewLevel = priority >= 95 ? "Immediate staff review" : priority >= 85 ? "High-priority review" : "Staff review";
  const bucketShort = matrixBucketShortLabel(opportunity.cell);
  const status = statusLabel(row.status);
  const runExposure = opportunity.runExposure ?? calibratedRunExposureValue(row);
  const runExposureLabel =
    opportunity.runExposureLabel ??
    (row.projectedPreventableRuns != null
      ? "run exposure"
      : row.decisionDelta != null
        ? "decision edge"
        : "impact");
  const preventableText =
    runExposure != null
      ? `${fmtRuns(runExposure)} ${runExposureLabel}`
        : "Run impact still calibrating";

  return (
    <button type="button" className="calibrated-row" onClick={() => row.gameId && onOpenGameAudit(row.gameId)}>
      <div className="review-game-cell">
        <strong>{row.team || "Team"} vs {row.opponent || "Opponent"}</strong>
        <span className="review-date-line"><CalendarBlank size={12} aria-hidden="true" /> {formatDateText(row.gameDate)}</span>
        <span>{windowCount} review window{windowCount === 1 ? "" : "s"} · {pitcherCount} pitcher{pitcherCount === 1 ? "" : "s"}</span>
      </div>
      <div className="review-pitcher-cell">
        <span className="review-pitcher-line">
          <span className="pitcher-avatar">{pitcherInitials(row.pitcherName)}</span>
          <strong>{row.pitcherName}</strong>
        </span>
        <span>Review point: {reviewPointLabel(row)}</span>
      </div>
      <div className="review-decision-cell">
        <span className="review-overline">Staff Review</span>
        <span className="review-decision-stack">
          <span className={`review-status-badge review-status-${signalClass(status)}`}>{status}</span>
          <strong>{bucketShort}</strong>
        </span>
        <span>{reviewLevel} · {fmtPct(row.projectedDamageProbability)} chance of scoring damage</span>
      </div>
      <div className="review-edge-cell">
        <strong>{preventableText}</strong>
        <span>Priority {priority}/100 · Comparable MLB windows</span>
      </div>
      <div className="driver-list">
        {reviewReasons.length === 0 ? (
          <span className="driver-chip">Open pitch audit</span>
        ) : (
          reviewReasons.slice(0, 2).map((reason) => <DriverChip key={reason} reason={reason} />)
        )}
        {reviewReasons.length > 2 && <span className="driver-chip driver-chip--more">+{reviewReasons.length - 2} more</span>}
      </div>
    </button>
  );
}

function calibratedGameKey(row: PreventableRunsOpportunityRow): string {
  const id = calibratedGameId(row);
  if (id) return id;
  const matchKey = calibratedMatchKeys(row)[0];
  if (matchKey) return matchKey;
  return [
    cleanDateToken(row.gameDate) ?? "date",
    cleanTeamToken(row.team) ?? "team",
    cleanTeamToken(row.opponent) ?? "opponent",
    cleanIdToken(row.pitcherId) ?? row.pitcherName ?? "pitcher",
    row.inning ?? "inning",
    row.half ?? "half",
    row.pitchCount ?? "pitch",
  ].join("|");
}

function calibratedPriorityValue(row: PreventableRunsOpportunityRow): number {
  return row.calibratedPreventableSignal ?? row.projectedDamageProbability ?? row.projectedPreventableRuns ?? 0;
}

function calibratedRunExposureValue(row: PreventableRunsOpportunityRow): number | null {
  return row.projectedPreventableRuns ?? null;
}

function calibratedDecisionEdgeValue(row: PreventableRunsOpportunityRow | null | undefined): number | null {
  return opportunityDecisionDelta(row);
}

function commandImpactTextFromValues(
  decisionEdge: number | null,
  runExposure: number | null,
  runExposureLabel: RunExposureLabel,
): { impactText: string; secondaryImpactText: string | null } {
  if (decisionEdge != null) {
    return {
      impactText: `${fmtSigned(decisionEdge, 2)} decision delta`,
      secondaryImpactText: runExposure != null ? `Run exposure ${fmtRuns(runExposure)}` : null,
    };
  }
  if (runExposure != null) {
    return {
      impactText: `${fmtRuns(runExposure)} ${runExposureLabel}`,
      secondaryImpactText: null,
    };
  }
  return {
    impactText: "Impact still calibrating",
    secondaryImpactText: null,
  };
}

function calibratedImpactSortValue(row: PreventableRunsOpportunityRow): number {
  const decisionEdge = calibratedDecisionEdgeValue(row);
  const runExposure = calibratedRunExposureValue(row);
  const primaryImpact = decisionEdge ?? runExposure ?? 0;
  return (primaryImpact == null ? 0 : primaryImpact * 1000) + calibratedPriorityValue(row);
}

function finiteNumbers(values: Array<number | null | undefined>): number[] {
  return values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function sumIfAny(values: Array<number | null | undefined>): number | null {
  const numbers = finiteNumbers(values);
  return numbers.length > 0 ? sum(numbers) : null;
}

function maxIfAny(values: Array<number | null | undefined>): number | null {
  const numbers = finiteNumbers(values);
  return numbers.length > 0 ? Math.max(...numbers) : null;
}

function aggregateCalibratedGameExposure(rows: PreventableRunsOpportunityRow[]): {
  value: number | null;
  label: RunExposureLabel;
} {
  const peak = peakDecisionWindow(rows);
  if (peak?.projectedPreventableRuns != null) return { value: peak.projectedPreventableRuns, label: "run exposure" };

  return { value: null, label: "impact" };
}

function peakDecisionWindowSortValue(row: PreventableRunsOpportunityRow): number {
  return ((opportunityDecisionDelta(row) ?? 0) * 1000) + calibratedPriorityValue(row);
}

function peakDecisionWindow(rows: PreventableRunsOpportunityRow[]): PreventableRunsOpportunityRow | null {
  if (rows.length === 0) return null;
  const actionablePullRows = rows.filter((row) => statusLabel(row.status) === "PULL NOW");
  const candidates = actionablePullRows.length > 0 ? actionablePullRows : rows;
  return candidates.reduce((currentBest, row) =>
    peakDecisionWindowSortValue(row) > peakDecisionWindowSortValue(currentBest) ? row : currentBest,
  );
}

function makeCalibratedGameGroup(rows: PreventableRunsOpportunityRow[]): CalibratedGameGroup | null {
  if (rows.length === 0) return null;
  const best = peakDecisionWindow(rows);
  if (!best) return null;
  const aggregate = aggregateCalibratedGameExposure(rows);
  return {
    best,
    windows: rows,
    decisionDelta: calibratedDecisionEdgeValue(best),
    runExposure: aggregate.value,
    runExposureLabel: aggregate.label,
  };
}

function calibratedGameGroupSortValue(group: CalibratedGameGroup | CalibratedGameOpportunity): number {
  const best = "best" in group ? group.best : group.row;
  const runExposure = group.runExposure;
  const decisionEdge = group.decisionDelta ?? calibratedDecisionEdgeValue(best);
  const primaryImpact = decisionEdge ?? runExposure ?? 0;
  return (primaryImpact == null ? 0 : primaryImpact * 1000) + calibratedPriorityValue(best);
}

function groupCalibratedOpportunitiesByGame(rows: PreventableRunsOpportunityRow[]): CalibratedGameOpportunity[] {
  const grouped = new Map<string, PreventableRunsOpportunityRow[]>();
  for (const row of rows) {
    const key = calibratedGameKey(row);
    const existing = grouped.get(key);
    if (existing) existing.push(row);
    else grouped.set(key, [row]);
  }
  return Array.from(grouped.values())
    .map((windows) => {
      const group = makeCalibratedGameGroup(windows);
      if (!group) return null;
      return {
        row: group.best,
        windows: group.windows,
        windowCount: group.windows.length,
        pitcherCount: new Set(group.windows.map((row) => row.pitcherId || row.pitcherName).filter(Boolean)).size,
        cell: allocationCellForOpportunity(group.best),
        decisionDelta: group.decisionDelta,
        runExposure: group.runExposure,
        runExposureLabel: group.runExposureLabel,
      };
    })
    .filter((opportunity): opportunity is CalibratedGameOpportunity => opportunity != null)
    .sort((a, b) => calibratedGameGroupSortValue(b) - calibratedGameGroupSortValue(a));
}

function auditWindowId(window: PitchingAuditWindow): string {
  return String(
    window.window_id ??
      window.start_pitch_id ??
      window.pitch_id ??
      [
        window.game_id ?? window.game_pk ?? window.matchup ?? "game",
        window.inning ?? "inning",
        window.half ?? "half",
        record(window.starter).pitch_count_in_game ?? "pitch",
        record(window.starter).pitcher_id ?? record(window.starter).pitcher_name ?? "pitcher",
      ].join(":"),
  );
}

function uniqueAuditWindows(windows: PitchingAuditWindow[]): PitchingAuditWindow[] {
  const seen = new Set<string>();
  const unique: PitchingAuditWindow[] = [];
  for (const window of windows) {
    const id = auditWindowId(window);
    if (seen.has(id)) continue;
    seen.add(id);
    unique.push(window);
  }
  return unique;
}

function auditGameKey(window: PitchingAuditWindow): string {
  return String(window.game_id ?? window.game_pk ?? `${window.game_date ?? window.date ?? "date"}:${window.matchup ?? "matchup"}`);
}

function auditGameDate(window: PitchingAuditWindow): string | null {
  const value = window.game_date ?? window.date;
  return typeof value === "string" ? value : null;
}

function auditPitcherName(window: PitchingAuditWindow): string {
  const starter = record(window.starter);
  return String(starter.pitcher_name ?? window.pitcher_name ?? window.pitcher ?? "Pitcher");
}

function auditPitcherId(window: PitchingAuditWindow): string {
  const starter = record(window.starter);
  return String(starter.pitcher_id ?? window.pitcher_id ?? auditPitcherName(window));
}

function auditPitchCount(window: PitchingAuditWindow): number | null {
  return num(record(window.starter).pitch_count_in_game ?? window.pitch_count);
}

function auditStatus(window: PitchingAuditWindow): string {
  return statusLabel(window.first_actionable_status ?? window.status ?? record(window.recommendation).status);
}

function auditPriorityValue(window: PitchingAuditWindow): number {
  const statusScore = statusRank(auditStatus(window)) * 20;
  const decisionDelta = Math.max(0, num(window.decision_delta) ?? 0) * 8;
  const winDelta = Math.max(0, num(window.estimated_win_probability_delta) ?? num(window.directional_wp_opportunity) ?? 0) * 100;
  const leverage = Math.max(0, num(window.leverage_index) ?? 0) * 5;
  const starter = record(window.starter);
  const degradation = Math.max(0, num(starter.degradation_score) ?? num(starter.enhanced_degradation_score) ?? 0) * 10;
  return statusScore + decisionDelta + winDelta + leverage + degradation;
}

function auditTeams(window: PitchingAuditWindow): { team: string; opponent: string; matchup: string } {
  const team = String(window.decision_team ?? window.team ?? "").trim();
  const opponent = String(window.opponent_team ?? window.opponent ?? "").trim();
  const matchup = String(window.matchup ?? (team && opponent ? `${opponent} @ ${team}` : "Game")).trim();
  if (team || opponent) return { team, opponent, matchup };
  const parts = matchup.split("@").map((part) => part.trim());
  if (parts.length === 2) return { opponent: parts[0], team: parts[1], matchup };
  return { team: "Team", opponent: "Opponent", matchup };
}

function teamKey(value: unknown): string {
  const clean = String(value ?? "").toUpperCase().replace(/[^A-Z]/g, "");
  return clean === "ARI" ? "AZ" : clean;
}

function cleanIdToken(value: unknown): string | null {
  const clean = String(value ?? "").trim();
  return clean && clean !== "null" && clean !== "undefined" ? clean : null;
}

function cleanDateToken(value: unknown): string | null {
  const clean = String(value ?? "").trim();
  return clean ? clean.slice(0, 10) : null;
}

function cleanTeamToken(value: unknown): string | null {
  const clean = teamKey(value);
  return clean && clean !== "TEAM" && clean !== "OPPONENT" ? clean : null;
}

function calibratedGameId(row: PreventableRunsOpportunityRow): string | null {
  const extra = record(row);
  return cleanIdToken(
    row.gameId ??
      extra.gameId ??
      extra.game_id ??
      extra.gamePk ??
      extra.game_pk ??
      extra.gamePK ??
      extra.game_pk_id ??
      extra.mlbGamePk ??
      extra.mlb_game_pk,
  );
}

function gameTeamsForId(gameId: string | null | undefined, games: EnterpriseGameSummary[]): { awayTeam: string | null; homeTeam: string | null } {
  const id = cleanIdToken(gameId);
  const game = id ? games.find((candidate) => String(candidate.game_id) === id) : null;
  return {
    awayTeam: game?.away_team ? String(game.away_team) : null,
    homeTeam: game?.home_team ? String(game.home_team) : null,
  };
}

function opponentDisplayLabel(
  selectedTeam: string,
  gameTeams: { awayTeam: string | null; homeTeam: string | null },
  fallbackOpponent: unknown,
): string {
  const selected = cleanTeamToken(selectedTeam);
  const away = cleanTeamToken(gameTeams.awayTeam);
  const home = cleanTeamToken(gameTeams.homeTeam);
  if (selected && away && home) {
    if (selected === away) return `@ ${home}`;
    if (selected === home) return `vs ${away}`;
  }
  const opponent = cleanTeamToken(fallbackOpponent);
  return opponent ? `vs ${opponent}` : "Opponent";
}

function calibratedMatchKeys(row: PreventableRunsOpportunityRow): string[] {
  const extra = record(row);
  const date = cleanDateToken(row.gameDate ?? extra.gameDate ?? extra.game_date ?? extra.gameDateEt ?? extra.game_date_et ?? extra.date);
  const team = cleanTeamToken(
    row.team ??
      extra.team ??
      extra.fieldingTeam ??
      extra.fielding_team ??
      extra.decisionTeam ??
      extra.decision_team ??
      extra.club ??
      extra.club_abbr,
  );
  const opponent = cleanTeamToken(
    row.opponent ?? extra.opponent ?? extra.battingTeam ?? extra.batting_team ?? extra.opponentTeam ?? extra.opponent_team,
  );
  if (!date || !team || !opponent) return [];
  return [`${date}|${team}|${opponent}`, `${date}|${opponent}|${team}`];
}

function auditWindowGameId(window: PitchingAuditWindow): string | null {
  return cleanIdToken(window.game_id ?? window.game_pk);
}

function auditWindowMatchKeys(window: PitchingAuditWindow): string[] {
  const teams = auditTeams(window);
  const date = cleanDateToken(auditGameDate(window));
  const team = cleanTeamToken(teams.team);
  const opponent = cleanTeamToken(teams.opponent);
  if (!date || !team || !opponent) return [];
  return [`${date}|${team}|${opponent}`, `${date}|${opponent}|${team}`];
}

function addCalibratedLookupRow(
  map: Map<string, PreventableRunsOpportunityRow[]>,
  key: string | null,
  row: PreventableRunsOpportunityRow,
) {
  if (!key) return;
  const existing = map.get(key);
  if (existing) existing.push(row);
  else map.set(key, [row]);
}

function buildCalibratedGameLookup(rows: PreventableRunsOpportunityRow[]): {
  byId: Map<string, CalibratedGameGroup>;
  byMatch: Map<string, CalibratedGameGroup>;
} {
  const byIdRows = new Map<string, PreventableRunsOpportunityRow[]>();
  const byMatchRows = new Map<string, PreventableRunsOpportunityRow[]>();
  for (const row of rows) {
    addCalibratedLookupRow(byIdRows, calibratedGameId(row), row);
    for (const key of calibratedMatchKeys(row)) {
      addCalibratedLookupRow(byMatchRows, key, row);
    }
  }

  const byId = new Map<string, CalibratedGameGroup>();
  for (const [key, groupedRows] of byIdRows.entries()) {
    const group = makeCalibratedGameGroup(groupedRows);
    if (group) byId.set(key, group);
  }

  const byMatch = new Map<string, CalibratedGameGroup>();
  for (const [key, groupedRows] of byMatchRows.entries()) {
    const group = makeCalibratedGameGroup(groupedRows);
    if (group) byMatch.set(key, group);
  }

  return { byId, byMatch };
}

function calibratedGroupForAuditWindow(
  window: PitchingAuditWindow,
  lookup: ReturnType<typeof buildCalibratedGameLookup>,
): CalibratedGameGroup | null {
  const id = auditWindowGameId(window);
  if (id) {
    const match = lookup.byId.get(id);
    if (match) return match;
  }
  for (const key of auditWindowMatchKeys(window)) {
    const match = lookup.byMatch.get(key);
    if (match) return match;
  }
  return null;
}

function seasonAuditSortValue(opportunity: SeasonAuditGameOpportunity): number {
  if (opportunity.calibratedDecisionDelta != null) {
    return (
      opportunity.calibratedDecisionDelta * 1000 +
      (opportunity.calibratedRow ? calibratedPriorityValue(opportunity.calibratedRow) : 0)
    );
  }
  if (opportunity.calibratedRunExposure != null) {
    return opportunity.calibratedRunExposure * 100 + (opportunity.calibratedRow ? calibratedPriorityValue(opportunity.calibratedRow) : 0);
  }
  return auditPriorityValue(opportunity.row);
}

function attachCalibratedRowsToSeasonAuditGames(
  opportunities: SeasonAuditGameOpportunity[],
  rows: PreventableRunsOpportunityRow[],
): SeasonAuditGameOpportunity[] {
  const lookup = buildCalibratedGameLookup(rows);
  return opportunities
    .map((opportunity) => {
      const calibratedGroup = calibratedGroupForAuditWindow(opportunity.row, lookup);
      const calibratedExplicitCell = calibratedGroup
        ? primaryExplicitAllocationCellForOpportunityRows(calibratedGroup.windows)
        : null;
      return {
        ...opportunity,
        cell: calibratedExplicitCell ?? opportunity.cell,
        calibratedRow: calibratedGroup?.best ?? null,
        calibratedRows: calibratedGroup?.windows ?? [],
        calibratedDecisionDelta: calibratedGroup?.decisionDelta ?? null,
        calibratedRunExposure: calibratedGroup?.runExposure ?? null,
        calibratedRunExposureLabel: calibratedGroup?.runExposureLabel ?? "impact",
      };
    })
    .sort((a, b) => seasonAuditSortValue(b) - seasonAuditSortValue(a));
}

function compactMatchup(value: unknown): string {
  return String(value ?? "")
    .toUpperCase()
    .replace(/\bARI\b/g, "AZ")
    .replace(/[^A-Z@]/g, "");
}

function gameMatchupAliases(game: EnterpriseGameSummary): string[] {
  const away = teamKey(game.away_team);
  const home = teamKey(game.home_team);
  return [`${away}@${home}`, `${away}VS${home}`, `${away}AT${home}`, compactMatchup(game.matchup)].filter(Boolean);
}

function auditResolvedGameId(window: PitchingAuditWindow, games: EnterpriseGameSummary[]): string {
  const explicit = String(window.game_id ?? window.game_pk ?? "").trim();
  if (explicit && games.some((game) => String(game.game_id) === explicit)) return explicit;

  const auditDate = dateKey(auditGameDate(window));
  const teams = auditTeams(window);
  const auditAliases = [
    compactMatchup(window.matchup),
    `${teamKey(teams.opponent)}@${teamKey(teams.team)}`,
    `${teamKey(teams.opponent)}VS${teamKey(teams.team)}`,
    `${teamKey(teams.team)}VS${teamKey(teams.opponent)}`,
  ].filter(Boolean);

  const matched = games.find((game) => {
    const gameDate = dateKey(game.date);
    if (auditDate && gameDate && auditDate !== gameDate) return false;
    const aliases = gameMatchupAliases(game);
    return auditAliases.some((alias) => aliases.includes(alias));
  });

  return String(matched?.game_id ?? explicit);
}

function auditReviewPointLabel(window: PitchingAuditWindow): string {
  const details = [
    halfInningLabel(typeof window.half === "string" ? window.half : null, num(window.inning)),
    outsLabel(num(window.outs)),
    baseStateLabel(typeof window.base_state === "string" ? window.base_state : null),
  ];
  const pitch = auditPitchCount(window);
  if (pitch != null) details.push(`pitch ${pitch}`);
  return details.join(" · ");
}

function auditWindowReasonLabels(window: PitchingAuditWindow): string[] {
  const reasons: string[] = [];
  const driver = String(window.trigger_driver_type ?? "").trim();
  const driverLabels: Record<string, string> = {
    pitcher_degradation: "Pitcher-driven decline",
    game_context: "Game state raised urgency",
    relief_alternative: "Better relief path available",
    workload_guardrail: "Workload guardrail applied",
    mixed_pitcher_context: "Pitcher decline plus game state",
    mixed: "Combined staff-deployment signal",
  };
  if (driverLabels[driver]) reasons.push(driverLabels[driver]);
  const baseFlags = baseStateFlags(typeof window.base_state === "string" ? window.base_state : null);
  const runners = Number(baseFlags.first) + Number(baseFlags.second) + Number(baseFlags.third);
  if (runners >= 2) reasons.push("Runners in scoring position");
  else if (runners === 1) reasons.push("Traffic on base");
  if ((num(window.leverage_index) ?? 0) >= 1.5) reasons.push("Important game state");
  const starter = record(window.starter);
  if ((num(starter.degradation_score) ?? num(starter.enhanced_degradation_score) ?? 0) >= 1) reasons.push("Starter was slipping");
  const topReasons = Array.isArray(window.top_reasons) ? window.top_reasons : [];
  for (const reason of topReasons) {
    if (reasons.length >= 3) break;
    const label = featureLabel(String(reason).toLowerCase());
    if (!reasons.includes(label)) reasons.push(label);
  }
  return reasons.slice(0, 3);
}

function auditDecisionSummary(window: PitchingAuditWindow): string | null {
  const summary = String(window.decision_summary ?? window.gm_summary ?? "").trim();
  if (!summary) return null;
  const [firstSentence] = summary.split(/(?<=\.)\s+/);
  return firstSentence || summary;
}

function auditRunExposureLabel(window: PitchingAuditWindow): string {
  const projected =
    num(window.projected_runs_saved) ??
    num(window.estimated_runs_saved) ??
    num(window.model_implied_runs_saved) ??
    null;
  if (projected != null) return `${fmtRuns(projected)} run exposure`;
  const delta = num(window.decision_delta);
  if (delta != null) return `${fmtSigned(delta, 2)} decision edge`;
  const wpOpportunity = num(window.estimated_win_probability_delta) ?? num(window.directional_wp_opportunity);
  if (wpOpportunity != null) return `${fmtPctPoints(wpOpportunity)} win-prob opportunity`;
  return "Run impact not estimated";
}

function groupSeasonAuditWindowsByGame(windows: PitchingAuditWindow[]): SeasonAuditGameOpportunity[] {
  const grouped = new Map<string, { best: PitchingAuditWindow; windows: PitchingAuditWindow[] }>();
  for (const window of uniqueAuditWindows(windows)) {
    const key = auditGameKey(window);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, { best: window, windows: [window] });
      continue;
    }
    existing.windows.push(window);
    if (auditPriorityValue(window) > auditPriorityValue(existing.best)) {
      existing.best = window;
    }
  }
  return Array.from(grouped.values())
    .map((group) => ({
      row: group.best,
      windowCount: group.windows.length,
      pitcherCount: new Set(group.windows.map(auditPitcherId).filter(Boolean)).size,
      cell: primaryMatrixCellForGame(group.windows),
    }))
    .sort((a, b) => auditPriorityValue(b.row) - auditPriorityValue(a.row));
}

function groupSeasonAuditWindowsByBucketGame(
  windows: PitchingAuditWindow[],
  bucket: MatrixCell | "all" = "all",
): SeasonAuditGameOpportunity[] {
  const filtered =
    bucket === "all" ? uniqueAuditWindows(windows) : uniqueAuditWindows(windows).filter((window) => matrixCellForWindow(window) === bucket);
  return groupSeasonAuditWindowsByGame(filtered);
}

function auditBucketGameCounts(windows: PitchingAuditWindow[]): Record<MatrixCell, number> {
  const grouped = groupSeasonAuditWindowsByGame(windows).reduce<Record<MatrixCell, number>>(
    (counts, opportunity) => {
      counts[opportunity.cell] += 1;
      return counts;
    },
    { standard: 0, tandem: 0, push: 0, workload: 0 },
  );
  return {
    standard: grouped.standard,
    tandem: grouped.tandem,
    push: grouped.push,
    workload: grouped.workload,
  };
}

function SeasonAuditOpportunityRow({
  opportunity,
  games,
  onOpenGameAudit,
}: {
  opportunity: SeasonAuditGameOpportunity;
  games: EnterpriseGameSummary[];
  onOpenGameAudit: (gameId: string) => void;
}) {
  const { row, windowCount, pitcherCount } = opportunity;
  const teams = auditTeams(row);
  const reasons = auditWindowReasonLabels(row);
  const priority = Math.min(100, Math.round(auditPriorityValue(row)));
  const bucketShort = matrixBucketShortLabel(opportunity.cell);
  const reviewLevel = priority >= 90 ? "Immediate staff review" : priority >= 70 ? "High-priority review" : "Staff review";
  const decisionSummary = auditDecisionSummary(row);
  const gameId = auditResolvedGameId(row, games);
  const status = auditStatus(row);
  const pitcherName = auditPitcherName(row);

  return (
    <button type="button" className="calibrated-row" onClick={() => onOpenGameAudit(gameId)} disabled={!gameId}>
      <div className="review-game-cell">
        <strong>{teams.matchup}</strong>
        <span className="review-date-line"><CalendarBlank size={12} aria-hidden="true" /> {formatDateText(auditGameDate(row))}</span>
        <span>{windowCount} review window{windowCount === 1 ? "" : "s"} · {pitcherCount} pitcher{pitcherCount === 1 ? "" : "s"}</span>
      </div>
      <div className="review-pitcher-cell">
        <span className="review-pitcher-line">
          <span className="pitcher-avatar">{pitcherInitials(pitcherName)}</span>
          <strong>{pitcherName}</strong>
        </span>
        <span>Review point: {auditReviewPointLabel(row)}</span>
      </div>
      <div className="review-decision-cell">
        <span className="review-overline">Staff Review</span>
        <span className="review-decision-stack">
          <span className={`review-status-badge review-status-${signalClass(status)}`}>{status}</span>
          <strong>{bucketShort}</strong>
        </span>
        <span>{decisionSummary ?? reviewLevel}</span>
      </div>
      <div className="review-edge-cell">
        <strong>{auditRunExposureLabel(row)}</strong>
        <span>Priority {priority}/100 · Season Audit</span>
      </div>
      <div className="driver-list">
        {reasons.length === 0 ? (
          <span className="driver-chip">Open pitch audit</span>
        ) : (
          reasons.slice(0, 2).map((reason) => <DriverChip key={reason} reason={reason} />)
        )}
        {reasons.length > 2 && <span className="driver-chip driver-chip--more">+{reasons.length - 2} more</span>}
      </div>
    </button>
  );
}

type CommandReviewRowModel = {
  key: string;
  gameId: string | null;
  matchup: string;
  opponentLabel: string;
  date: string;
  pitcherMeta: string;
  pitcherName: string;
  selectedTeam: string;
  reviewPoint: string;
  status: string;
  bucket: MatrixCell;
  bucketLabel: string;
  decisionText: string;
  impactText: string;
  secondaryImpactText: string | null;
  decisionDelta: number | null;
  runExposure: number | null;
  damageRisk: number | null;
  leverage: number | null;
  priorityText: string;
  reasons: string[];
  pitchCount: number | null;
  inning: number | null;
  half: string | null;
  outs: number | null;
  baseState: string | null;
  homeTeam: string | null;
  awayTeam: string | null;
  currentHomeScore: number | null;
  currentAwayScore: number | null;
  finalHomeScore: number | null;
  finalAwayScore: number | null;
  recommendedRelieverName: string | null;
  actualChangeInning: string | null;
  actualChangePitchCount: number | null;
  actualReplacementPitcher: string | null;
  runsAfterModelWindow: number | null;
  degradationScore: number | null;
  rationaleText: string;
};

function auditRunExposureValue(window: PitchingAuditWindow): number | null {
  return (
    num(window.projected_runs_saved) ??
    num(window.estimated_runs_saved) ??
    num(window.model_implied_runs_saved) ??
    null
  );
}

function auditDecisionDeltaValue(window: PitchingAuditWindow): number | null {
  return num(window.decision_delta);
}

function seasonAuditCommandRow(opportunity: SeasonAuditGameOpportunity, games: EnterpriseGameSummary[], selectedTeam: Team): CommandReviewRowModel {
  const { row, windowCount, pitcherCount } = opportunity;
  const teams = auditTeams(row);
  const priority = Math.min(100, Math.round(auditPriorityValue(row)));
  const decisionSummary = auditDecisionSummary(row);
  const reviewLevel = priority >= 90 ? "Immediate staff review" : priority >= 70 ? "High-priority review" : "Staff review";
  const calibratedRow = opportunity.calibratedRow ?? null;
  const calibratedRunExposure =
    opportunity.calibratedRunExposure ?? (calibratedRow ? calibratedRunExposureValue(calibratedRow) : null);
  const calibratedRunExposureLabel = opportunity.calibratedRunExposureLabel ?? "run exposure";
  const calibratedDecisionEdge = opportunity.calibratedDecisionDelta ?? calibratedDecisionEdgeValue(calibratedRow);
  const auditDecisionDelta = auditDecisionDeltaValue(row);
  const calibratedSignal = calibratedRow?.calibratedPreventableSignal ?? calibratedRow?.projectedDamageProbability ?? null;
  const displayPriority = calibratedSignal == null ? priority : Math.min(100, Math.round(calibratedSignal * 100));
  const calibratedImpact = calibratedRow
    ? commandImpactTextFromValues(calibratedDecisionEdge, calibratedRunExposure, calibratedRunExposureLabel)
    : null;
  const auditImpact = commandImpactTextFromValues(auditDecisionDelta, auditRunExposureValue(row), "run exposure");
  const mergedReasons = [...(calibratedRow ? reviewReasonLabels(calibratedRow) : []), ...auditWindowReasonLabels(row)]
    .filter((reason, index, list) => Boolean(reason) && list.indexOf(reason) === index)
    .slice(0, 3);
  const gameId = auditResolvedGameId(row, games);
  const gameTeams = gameTeamsForId(gameId, games);
  const rawRow = record(row);
  const degradation =
    calibratedRow?.degradationScore ??
    calibratedRow?.productionDegradation ??
    calibratedRow?.normalizedDegradation ??
    num(record(row.starter).degradation_score ?? record(row.starter).enhanced_degradation_score ?? row.degradation_score ?? row.normalized_degradation);
  const rationale =
    mergedReasons[0] ??
    (calibratedRow?.projectedDamageProbability != null
      ? `${fmtPct(calibratedRow.projectedDamageProbability)} scoring damage risk at the peak decision window`
      : decisionSummary ?? "Model rationale unavailable");

  return {
    key: auditGameKey(row),
    gameId,
    matchup: teams.matchup,
    opponentLabel: opponentDisplayLabel(selectedTeam.abbr, gameTeams, teams.opponent),
    date: formatDateText(auditGameDate(row)),
    pitcherMeta: `${windowCount} review window${windowCount === 1 ? "" : "s"} · ${pitcherCount} pitcher${pitcherCount === 1 ? "" : "s"}`,
    pitcherName: displayPersonName(auditPitcherName(row)) || "Pitcher",
    selectedTeam: selectedTeam.abbr,
    reviewPoint: auditReviewPointLabel(row),
    status: auditStatus(row),
    bucket: opportunity.cell,
    bucketLabel: matrixBucketShortLabel(opportunity.cell),
    decisionText:
      decisionSummary ??
      (calibratedRow?.projectedDamageProbability != null
        ? `${reviewLevel} · ${fmtPct(calibratedRow.projectedDamageProbability)} chance of scoring damage`
        : reviewLevel),
    impactText: calibratedImpact?.impactText ?? auditImpact.impactText,
    secondaryImpactText: calibratedImpact?.secondaryImpactText ?? auditImpact.secondaryImpactText,
    decisionDelta: calibratedDecisionEdge ?? auditDecisionDelta,
    runExposure: calibratedRunExposure ?? auditRunExposureValue(row),
    damageRisk: calibratedRow?.projectedDamageProbability ?? num(row.projected_damage_probability) ?? num(row.damage_probability) ?? null,
    leverage: calibratedRow?.leverageIndex ?? num(row.leverage_index),
    priorityText:
      calibratedDecisionEdge != null
        ? `Decision delta ${fmtSigned(calibratedDecisionEdge, 2)} · Priority ${displayPriority}/100`
        : `Priority ${displayPriority}/100 · ${calibratedRow ? "Calibrated game exposure" : "Season Audit"}`,
    reasons: mergedReasons.length > 0 ? mergedReasons : auditWindowReasonLabels(row),
    pitchCount: calibratedRow?.pitchCount ?? auditPitchCount(row),
    inning: calibratedRow?.inning ?? num(row.inning),
    half: calibratedRow?.half ?? (typeof row.half === "string" ? row.half : null),
    outs: calibratedRow?.outs ?? num(row.outs),
    baseState: calibratedRow?.baseState ?? (typeof rawRow.base_state === "string" ? rawRow.base_state : null),
    homeTeam: gameTeams.homeTeam,
    awayTeam: gameTeams.awayTeam,
    currentHomeScore: calibratedRow?.currentHomeScore ?? num(rawRow.currentHomeScore ?? rawRow.current_home_score),
    currentAwayScore: calibratedRow?.currentAwayScore ?? num(rawRow.currentAwayScore ?? rawRow.current_away_score),
    finalHomeScore: calibratedRow?.finalHomeScore ?? num(rawRow.finalHomeScore ?? rawRow.final_home_score),
    finalAwayScore: calibratedRow?.finalAwayScore ?? num(rawRow.finalAwayScore ?? rawRow.final_away_score),
    recommendedRelieverName: displayPersonName(calibratedRow?.recommendedRelieverName) || null,
    actualChangeInning: calibratedRow?.actualChangeInning ?? (typeof rawRow.actualChangeInning === "string" ? rawRow.actualChangeInning : null),
    actualChangePitchCount: calibratedRow?.actualChangePitchCount ?? num(rawRow.actualChangePitchCount ?? rawRow.actual_change_pitch_count),
    actualReplacementPitcher: displayPersonName(calibratedRow?.actualReplacementPitcher ?? (typeof rawRow.actualReplacementPitcher === "string" ? rawRow.actualReplacementPitcher : null)) || null,
    runsAfterModelWindow: calibratedRow?.runsAfterModelWindow ?? num(rawRow.runsAfterModelWindow ?? rawRow.runs_after_model_window),
    degradationScore: degradation,
    rationaleText: rationale,
  };
}

function calibratedCommandRow(opportunity: CalibratedGameOpportunity, games: EnterpriseGameSummary[], selectedTeam: Team): CommandReviewRowModel {
  const { row, windowCount } = opportunity;
  const priority = Math.round((row.calibratedPreventableSignal ?? row.projectedDamageProbability ?? 0) * 100);
  const reviewLevel = priority >= 95 ? "Immediate staff review" : priority >= 85 ? "High-priority review" : "Staff review";
  const runExposure = opportunity.runExposure ?? calibratedRunExposureValue(row);
  const runExposureLabel = opportunity.runExposureLabel ?? "run exposure";
  const decisionDelta = opportunity.decisionDelta ?? calibratedDecisionEdgeValue(row);
  const impact = commandImpactTextFromValues(decisionDelta, runExposure, runExposureLabel);
  const gameTeams = gameTeamsForId(row.gameId, games);
  const reasons = reviewReasonLabels(row);

  return {
    key: calibratedGameKey(row),
    gameId: row.gameId ?? null,
    matchup: `${row.team || "Team"} vs ${row.opponent || "Opponent"}`,
    opponentLabel: opponentDisplayLabel(selectedTeam.abbr, gameTeams, row.opponent),
    date: formatDateText(row.gameDate),
    pitcherMeta: windowCount > 1 ? `Peak decision window · ${windowCount} windows evaluated` : "Peak decision window",
    pitcherName: displayPersonName(row.pitcherName) || "Pitcher",
    selectedTeam: selectedTeam.abbr,
    reviewPoint: reviewPointLabel(row),
    status: statusLabel(row.status),
    bucket: opportunity.cell,
    bucketLabel: matrixBucketShortLabel(opportunity.cell),
    decisionText: `${reviewLevel} · ${fmtPct(row.projectedDamageProbability)} chance of scoring damage`,
    impactText: impact.impactText,
    secondaryImpactText: impact.secondaryImpactText,
    decisionDelta,
    runExposure,
    damageRisk: row.projectedDamageProbability,
    leverage: row.leverageIndex,
    priorityText: `Priority ${priority}/100 · Calibrated game exposure`,
    reasons,
    pitchCount: row.pitchCount,
    inning: row.inning,
    half: row.half,
    outs: row.outs,
    baseState: row.baseState,
    homeTeam: gameTeams.homeTeam,
    awayTeam: gameTeams.awayTeam,
    currentHomeScore: row.currentHomeScore ?? null,
    currentAwayScore: row.currentAwayScore ?? null,
    finalHomeScore: row.finalHomeScore ?? null,
    finalAwayScore: row.finalAwayScore ?? null,
    recommendedRelieverName: displayPersonName(row.recommendedRelieverName) || null,
    actualChangeInning: row.actualChangeInning ?? null,
    actualChangePitchCount: row.actualChangePitchCount ?? null,
    actualReplacementPitcher: displayPersonName(row.actualReplacementPitcher) || null,
    runsAfterModelWindow: row.runsAfterModelWindow ?? null,
    degradationScore: row.degradationScore ?? row.productionDegradation ?? row.normalizedDegradation,
    rationaleText: reasons[0] ?? "Model rationale unavailable",
  };
}

function CommandDriverChip({ reason }: { reason: string }) {
  const value = reason.toLowerCase();
  const Icon =
    value.includes("runner") || value.includes("traffic") || value.includes("base")
      ? Users
      : value.includes("slipping") ||
          value.includes("stuff") ||
          value.includes("velocity") ||
          value.includes("spin") ||
          value.includes("command") ||
          value.includes("decline")
        ? TrendDown
        : null;

  return (
    <span className="cmdx-driver-chip">
      {Icon ? <Icon size={12} aria-hidden="true" /> : null}
      {reason}
    </span>
  );
}

function impactParts(impactText: string): { value: string; label: string } {
  const match = impactText.trim().match(/^([+-]?\d+(?:\.\d+)?)(.*)$/);
  if (!match) {
    return { value: impactText, label: "impact" };
  }
  const [, value, rest] = match;
  return { value, label: rest.trim() || "edge" };
}

function impactLabelText(label: string): string {
  const value = label.toLowerCase();
  if (value.includes("decision delta")) return "Decision Delta";
  if (value.includes("run exposure")) return "Run exposure";
  if (value.includes("decision edge")) return "Decision edge";
  if (value.includes("risk")) return "Scoring risk";
  return "Impact";
}

function commandReviewRowSortValue(row: CommandReviewRowModel): number {
  return ((row.decisionDelta ?? row.runExposure ?? 0) * 1000) + ((row.damageRisk ?? 0) * 100) + (row.leverage ?? 0);
}

function bucketTransitionLabel(bucketLabel: string): string {
  if (bucketLabel.toLowerCase().includes("tandem")) return "Tandem Transition";
  if (bucketLabel.toLowerCase().includes("push")) return "Push Starter";
  if (bucketLabel.toLowerCase().includes("workload")) return "Workload Review";
  return bucketLabel;
}

function commandRowInsight(row: CommandReviewRowModel): string {
  if (row.reasons.length > 0) return row.reasons[0];
  if (row.decisionText) return row.decisionText;
  if (row.damageRisk != null) return `${fmtPct(row.damageRisk)} scoring damage risk at the peak decision window`;
  return "Open Game Replay for pitch-by-pitch context";
}

function commandPitchLabel(row: CommandReviewRowModel): string {
  const pitch = row.pitchCount == null ? "Pitch unavailable" : `Pitch ${row.pitchCount}`;
  return `${pitch} · ${compactInningLabel(row.half, row.inning)}`;
}

function commandRemovalLabel(row: CommandReviewRowModel): string {
  const inning = row.actualChangeInning;
  const pitch = row.actualChangePitchCount == null ? null : `pitch ${row.actualChangePitchCount}`;
  if (!inning && !pitch) return "Removal unavailable";
  return [inning, pitch].filter(Boolean).join(" · ");
}

function commandRunsAfterLabel(row: CommandReviewRowModel): string {
  if (row.runsAfterModelWindow == null) return "Runs unavailable";
  return `${row.runsAfterModelWindow} ${row.runsAfterModelWindow === 1 ? "run" : "runs"} before removal`;
}

function personNameKey(name: string | null | undefined): string {
  return displayPersonName(name).toLowerCase().replace(/[^a-z]/g, "");
}

function commandReliefDetail(row: CommandReviewRowModel): string {
  if (row.decisionDelta == null) return "Model edge unavailable for this relief option.";
  const value = fmtSigned(Math.abs(row.decisionDelta), 2);
  if (row.decisionDelta >= 0) {
    return `Model estimated this option was ${value} runs better than keeping the starter in for the next window.`;
  }
  return `Model estimated this option was ${value} runs worse than keeping the starter in for the next window.`;
}

function CommandScoreLine({ row, final = false }: { row: CommandReviewRowModel; final?: boolean }) {
  const awayScore = final ? row.finalAwayScore : row.currentAwayScore;
  const homeScore = final ? row.finalHomeScore : row.currentHomeScore;
  if (awayScore == null || homeScore == null) {
    return <span>{final ? "Final score unavailable" : "Score unavailable"}</span>;
  }
  const away = row.awayTeam ?? "Away";
  const home = row.homeTeam ?? "Home";
  const selected = teamKey(row.selectedTeam);
  const awaySelected = selected && teamKey(away) === selected;
  const homeSelected = selected && teamKey(home) === selected;
  return (
    <span className="cmdx-score-line">
      {final ? <span>Final </span> : null}
      <b className={awaySelected ? "is-selected-team" : ""}>{away} {awayScore}</b>
      <span> - </span>
      <b className={homeSelected ? "is-selected-team" : ""}>{home} {homeScore}</b>
    </span>
  );
}

function CommandRunsAfter({ row }: { row: CommandReviewRowModel }) {
  if (row.runsAfterModelWindow == null) return <span>Runs unavailable</span>;
  return (
    <span>
      <b className="cmdx-run-highlight">
        {row.runsAfterModelWindow} {row.runsAfterModelWindow === 1 ? "run" : "runs"}
      </b>{" "}
      before removal
    </span>
  );
}

function CommandBasesDiamond({ baseState }: { baseState: string | null | undefined }) {
  const bases = baseStateFlags(baseState);
  return (
    <span className="cmdx-bases-mini" aria-label={baseStateLabel(baseState)}>
      <i className={bases.second ? "filled second" : "second"} />
      <i className={bases.third ? "filled third" : "third"} />
      <i className={bases.first ? "filled first" : "first"} />
    </span>
  );
}

function CommandOutsDots({ outs }: { outs: number | null | undefined }) {
  return (
    <span className="cmdx-outs-mini" aria-label={outsLabel(outs)}>
      {[0, 1, 2].map((index) => (
        <i key={index} className={(outs ?? 0) > index ? "filled" : ""} />
      ))}
    </span>
  );
}

function CommandRowPanel({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "red" | "blue";
}) {
  return (
    <div className={`cmdx-row-panel ${tone ? `cmdx-row-panel--${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <em>{detail}</em> : null}
    </div>
  );
}

function CommandReviewRowCard({
  row,
  onOpenGameAudit,
}: {
  row: CommandReviewRowModel;
  onOpenGameAudit: (gameId: string) => void;
}) {
  const hasGame = Boolean(row.gameId);
  const reliefName = row.recommendedRelieverName ?? "Reliever unavailable";
  const modelRelieverKey = personNameKey(row.recommendedRelieverName);
  const actualRelieverKey = personNameKey(row.actualReplacementPitcher);
  const actualChangeText =
    row.actualReplacementPitcher && modelRelieverKey && actualRelieverKey && modelRelieverKey === actualRelieverKey
      ? `Actual change matched model option: ${row.actualReplacementPitcher}`
      : row.actualReplacementPitcher
        ? `Actual change to ${row.actualReplacementPitcher}`
        : "Actual replacement unavailable";
  const outcomeValue = commandRemovalLabel(row);

  return (
    <button
      type="button"
      className={`cmdx-queue-row cmdx-queue-row--${row.bucket}`}
      onClick={() => row.gameId && onOpenGameAudit(row.gameId)}
      disabled={!hasGame}
    >
      <div className="cmdx-row-top">
        <div className="cmdx-row-meta">
          <strong className="cmdx-row-pitcher-name">{row.pitcherName}</strong>
          <strong className="cmdx-matchup-pill">{row.opponentLabel}</strong>
          <span className="cmdx-row-date">
            <CalendarBlank size={14} aria-hidden="true" />
            {row.date}
          </span>
        </div>
        <span className={`cmdx-category-pill cmdx-category-pill--${row.bucket}`}>{row.bucketLabel}</span>
      </div>
      <div className="cmdx-row-body">
        <div className="cmdx-row-panel cmdx-signal-panel">
          <span>Signal Context</span>
          <div className="cmdx-signal-main">
            <b className={`cmdx-status cmdx-status--${signalClass(row.status)}`}>{row.status}</b>
            <strong>{commandPitchLabel(row)}</strong>
          </div>
          <div className="cmdx-signal-state">
            <CommandBasesDiamond baseState={row.baseState} />
            <CommandOutsDots outs={row.outs} />
            <em><CommandScoreLine row={row} /></em>
          </div>
        </div>
        <CommandRowPanel label="Signal Rationale" value={fmtNumber(row.degradationScore, 2)} detail={row.rationaleText} tone="blue" />
        <CommandRowPanel label="Decision Delta" value={fmtSigned(row.decisionDelta, 2)} tone="red" />
        <CommandRowPanel label="Run Exposure" value={fmtRuns(row.runExposure)} detail="Peak model signal" tone="red" />
        <CommandRowPanel label="Optimal Relief Option" value={reliefName} detail={commandReliefDetail(row)} tone="blue" />
        <CommandRowPanel
          label="Actual Game Outcome"
          value={outcomeValue}
          detail={
            <span className="cmdx-outcome-detail">
              <span>{actualChangeText}</span>
              <CommandRunsAfter row={row} />
              <CommandScoreLine row={row} final />
            </span>
          }
          tone="blue"
        />
      </div>
    </button>
  );
}

/*
 * Legacy row markup retained above this point was replaced by the exact command-board layout.
 * The row still uses the same gameId callback, so existing pitch-level audit deep links remain intact.
 */

function LegacyCommandReviewRowCard({
  row,
  onOpenGameAudit,
}: {
  row: CommandReviewRowModel;
  onOpenGameAudit: (gameId: string) => void;
}) {
  return (
    <button
      type="button"
      className={`audit-review-row audit-review-row--${row.bucket}`}
      onClick={() => row.gameId && onOpenGameAudit(row.gameId)}
      disabled={!row.gameId}
    >
      <div className="audit-row-game">
        <strong>{row.matchup}</strong>
        <span>
          <CalendarBlank size={12} aria-hidden="true" />
          {row.date}
        </span>
        <em>{row.pitcherMeta}</em>
      </div>
      <div className="audit-row-pitcher">
        <span className="audit-pitcher-line">
          <span className="audit-pitcher-avatar">{pitcherInitials(row.pitcherName)}</span>
          <strong>{row.pitcherName}</strong>
        </span>
        <em>{row.reviewPoint}</em>
      </div>
      <div className="audit-row-decision">
        <span>Staff review</span>
        <strong>
          <b className={`audit-status-badge audit-status-${signalClass(row.status)}`}>{row.status}</b>
          {row.bucketLabel}
        </strong>
        <em>{row.decisionText}</em>
      </div>
      <div className="audit-row-impact">
        <strong>{row.impactText}</strong>
        <em>{row.priorityText}</em>
      </div>
      <div className="audit-row-reasons">
        {row.reasons.length === 0 ? (
          <span className="audit-driver-chip">Open pitch audit</span>
        ) : (
          row.reasons.slice(0, 3).map((reason) => <CommandDriverChip key={reason} reason={reason} />)
        )}
      </div>
    </button>
  );
}

function CommandCenter({
  team,
  season,
  payload,
  preventableRuns,
  preventableRunsError,
  preventableRunsLoading,
  profiles,
  auditSummary,
  games,
  onOpenAudit,
  onOpenGameAudit,
  onRefresh,
  onSeasonChange,
}: {
  team: Team;
  season: string;
  payload: RunSavingBoardPayload;
  preventableRuns: PreventableRunsOpportunitiesPayload | null;
  preventableRunsError: string | null;
  preventableRunsLoading: boolean;
  profiles: PitcherProfile[];
  auditSummary: PitchingAuditSummaryPayload | null;
  games: EnterpriseGameSummary[];
  onOpenAudit: () => void;
  onOpenGameAudit: (gameId: string) => void;
  onRefresh: () => void;
  onSeasonChange: (season: string) => void;
}) {
  const seasonRuns = sum(profiles.map((profile) => profile.projectedRunsSaved));
  const boardRuns = sum(payload.decisions.map((decision) => decision.projectedRunsSaved));
  const calibratedSummary = preventableRuns?.summary ?? null;
  const calibratedRows = (preventableRuns?.rows ?? []).filter((row) =>
    isRegularSeasonDate(row.gameDate ?? record(row).game_date ?? record(row).date, season),
  );
  const calibratedRowsHaveRunExposure = calibratedRows.some((row) => typeof row.projectedPreventableRuns === "number");
  const calibratedRuns = calibratedRowsHaveRunExposure
    ? sum(calibratedRows.map((row) => row.projectedPreventableRuns))
    : calibratedSummary?.totalProjectedPreventableRuns ?? 0;
  const displayedRuns = calibratedSummary || calibratedRows.length > 0 ? calibratedRuns : seasonRuns || boardRuns;
  const calibratedDamageFlags = calibratedRows
    .map((row) => row.missedHookDamageFlag ?? row.damageFlag)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const calibratedDamageCount = calibratedDamageFlags.filter((value) => value > 0).length;
  const calibratedDamageRate =
    calibratedDamageFlags.length > 0 ? calibratedDamageCount / calibratedDamageFlags.length : calibratedSummary?.damageRate ?? null;
  const damageWindowCount = calibratedDamageFlags.length > 0 ? calibratedDamageCount : calibratedSummary?.missedHookDamageCount ?? 0;
  const windows = auditWindows(auditSummary).filter((window) => isRegularSeasonDate(auditGameDate(window), season));
  const deploymentBuckets: MatrixCell[] = ["tandem", "push", "workload", "standard"];
  const [allocationFilter, setAllocationFilter] = useState<MatrixCell | "all">("all");
  const allCalibratedGames = groupCalibratedOpportunitiesByGame(calibratedRows);
  const allSeasonAuditGames = attachCalibratedRowsToSeasonAuditGames(groupSeasonAuditWindowsByGame(windows), calibratedRows);
  const useCalibratedQueue = allCalibratedGames.length > 0;
  const bucketSourceGames = useCalibratedQueue ? allCalibratedGames : allSeasonAuditGames;
  const auditMatrix = bucketSourceGames.reduce<Record<MatrixCell, number>>(
    (counts, opportunity) => {
      counts[opportunity.cell] += 1;
      return counts;
    },
    { standard: 0, tandem: 0, push: 0, workload: 0 },
  );
  const dashboardBuckets = deploymentBuckets;
  const filteredSeasonAuditGames = !useCalibratedQueue
    ? allocationFilter === "all"
      ? allSeasonAuditGames
      : allSeasonAuditGames.filter((opportunity) => opportunity.cell === allocationFilter)
    : [];
  const filteredCalibratedGames = useCalibratedQueue
    ? allocationFilter === "all"
      ? allCalibratedGames
      : allCalibratedGames.filter((opportunity) => opportunity.cell === allocationFilter)
    : [];
  const selectedBucketCopy = allocationFilter === "all" ? null : matrixBucketCopy(allocationFilter);
  const visibleSeasonAuditGames = filteredSeasonAuditGames;
  const visibleCalibratedGames = filteredCalibratedGames;
  const visibleGameCount = visibleSeasonAuditGames.length || visibleCalibratedGames.length;
  const visibleWindowCount = visibleSeasonAuditGames.length > 0
    ? sum(visibleSeasonAuditGames.map((opportunity) => opportunity.windowCount))
    : selectedBucketCopy
      ? visibleCalibratedGames.length
      : calibratedSummary?.windowCount ?? preventableRuns?.rowCount ?? visibleCalibratedGames.length;
  const visibleAvgLeverage =
    visibleSeasonAuditGames.length > 0
      ? sum(visibleSeasonAuditGames.map((opportunity) => num(opportunity.row.leverage_index) ?? 0)) / visibleSeasonAuditGames.length
      : null;
  const nonEmptyBucketCount = deploymentBuckets.filter((bucket) => auditMatrix[bucket] > 0).length;
  const allocationMapDetail =
    nonEmptyBucketCount === 1
      ? "These counts are from the regular-season audit inventory. Each unique game is assigned to one primary decision type based on its highest-priority review window."
      : "These counts are from the regular-season audit inventory. Each unique game is assigned to one primary decision type, so the bucket counts add up to the total unique review games.";
  const queuePitcherCount = new Set(
    [
      ...calibratedRows.map((row) => row.pitcherId || row.pitcherName),
      ...uniqueAuditWindows(windows).map(auditPitcherId),
    ].filter((pitcher): pitcher is string => Boolean(pitcher)),
  ).size;
  const coveredPitcherCount = queuePitcherCount || profiles.length;
  const coveredPitcherDetail =
    queuePitcherCount > 0
      ? `${queuePitcherCount} unique pitchers surfaced in the season review queue.`
      : `${profiles.length} pitcher profiles available; no season review queue pitchers were returned.`;
  const queueSummaryWindowCount = visibleWindowCount || calibratedSummary?.missedHookDamageCount || damageWindowCount;
  const reviewRows =
    useCalibratedQueue
      ? visibleCalibratedGames.map((opportunity) => calibratedCommandRow(opportunity, games, team))
      : visibleSeasonAuditGames.map((opportunity) => seasonAuditCommandRow(opportunity, games, team));
  reviewRows.sort((a, b) => commandReviewRowSortValue(b) - commandReviewRowSortValue(a));
  const allReviewRows =
    useCalibratedQueue
      ? allCalibratedGames.map((opportunity) => calibratedCommandRow(opportunity, games, team))
      : allSeasonAuditGames.map((opportunity) => seasonAuditCommandRow(opportunity, games, team));
  allReviewRows.sort((a, b) => commandReviewRowSortValue(b) - commandReviewRowSortValue(a));
  const averageDecisionDelta = avg(allReviewRows.map((row) => row.decisionDelta));
  const totalRunExposure = sumIfAny(allReviewRows.map((row) => row.runExposure));
  const overviewBuckets: Array<{
    key: MatrixCell | "all";
    label: string;
    value: number;
    definition?: string;
    variant: "all" | "tandem" | "standard" | "empty";
  }> = [
    {
      key: "all",
      label: "Total Games Reviewed",
      value: bucketSourceGames.length,
      variant: "all",
    },
    {
      key: "tandem",
      label: "Tandem Mandatory",
      value: auditMatrix.tandem,
      definition: matrixBucketDefinition("tandem"),
      variant: "tandem",
    },
    {
      key: "push",
      label: "Push The Starter",
      value: auditMatrix.push,
      definition: matrixBucketDefinition("push"),
      variant: auditMatrix.push > 0 ? "standard" : "empty",
    },
    {
      key: "workload",
      label: "Workload Management",
      value: auditMatrix.workload,
      definition: matrixBucketDefinition("workload"),
      variant: auditMatrix.workload > 0 ? "standard" : "empty",
    },
    {
      key: "standard",
      label: "Standard Usage",
      value: auditMatrix.standard,
      definition: matrixBucketDefinition("standard"),
      variant: auditMatrix.standard > 0 ? "standard" : "empty",
    },
  ];

  const selectedReviewHeading =
    allocationFilter === "all"
      ? "All Reviews"
      : `${overviewBuckets.find((bucket) => bucket.key === allocationFilter)?.label ?? "Selected"} Review`;

  return (
    <section className="cmdx-command">
      <header className="cmdx-command-header">
        <div className="cmdx-command-title">
          <h1>{team.name}</h1>
          <p>Season Insights</p>
        </div>

        <div className="cmdx-head-strip" aria-label="Current review summary">
          <div>
            <span>Pitchers Reviewed</span>
            <strong>{coveredPitcherCount}</strong>
          </div>
          <div>
            <span>Average Decision Delta</span>
            <strong>{fmtSigned(averageDecisionDelta, 2)}</strong>
          </div>
          <div>
            <span>Total Run Exposure</span>
            <strong>{fmtRuns(totalRunExposure)}</strong>
          </div>
          <label className="cmdx-season-select">
            <span>Season</span>
            <span className="cmdx-season-control">
              <select value={season} onChange={(event) => onSeasonChange(event.target.value)}>
                <option value="2026">2026</option>
                <option value="2025">2025</option>
              </select>
              <CalendarBlank size={15} aria-hidden="true" />
            </span>
          </label>
        </div>
      </header>

      <section className="cmdx-overview" aria-label="Staff allocation overview">
        <div className="cmdx-section-title">
          <SquaresFour size={22} aria-hidden="true" />
          <div>
            <h2>Staff Deployment Review</h2>
          </div>
        </div>

        <div className="cmdx-stat-grid">
          {overviewBuckets.map((bucket) => (
            <button
              key={bucket.key}
              type="button"
              className={[
                "cmdx-stat-card",
                `cmdx-stat-card--${bucket.variant}`,
                `cmdx-stat-card--${bucket.key}`,
                allocationFilter === bucket.key ? "active" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => setAllocationFilter(bucket.key)}
            >
              {bucket.key === "all" ? <Files size={92} aria-hidden="true" /> : null}
              <span>{bucket.label}</span>
              <strong>{bucket.value}</strong>
              {bucket.definition ? <em className="cmdx-stat-tooltip">{bucket.definition}</em> : null}
            </button>
          ))}
        </div>
      </section>

      {bucketSourceGames.length === 0 && preventableRunsLoading ? (
        <EmptyState title="Loading review queue" detail="Retrieving the current staff-deployment opportunity set." />
      ) : bucketSourceGames.length === 0 && preventableRunsError ? (
        <EmptyState title="Review queue unavailable" detail={preventableRunsError} />
      ) : visibleGameCount === 0 ? (
        <EmptyState title="No games returned" detail="The evidence source is reachable, but no game-level review rows matched this club and season." />
      ) : (
        <section className="cmdx-queue">
          <div className="cmdx-queue-title">
            <div>
              <ListDashes size={22} aria-hidden="true" />
              <h2>{selectedReviewHeading}</h2>
            </div>
            <button type="button" className="cmdx-sort-button" onClick={onRefresh}>
              <SortDescending size={16} aria-hidden="true" />
              Sort by Decision Delta
            </button>
          </div>

          <div className="cmdx-row-list">
            {reviewRows.map((row) => (
              <CommandReviewRowCard key={row.key} row={row} onOpenGameAudit={onOpenGameAudit} />
            ))}
          </div>
        </section>
      )}
    </section>
  );
}

function GameAudit({
  team,
  games,
  selectedGameId,
  onGameChange,
  replay,
  recap,
  preventableRows,
  season,
  onSeasonChange,
}: {
  team: Team;
  games: EnterpriseGameSummary[];
  selectedGameId: string | null;
  onGameChange: (id: string) => void;
  replay: PitchingReplayResponse | null;
  recap: PitchingGameRecap | null;
  preventableRows: PreventableRunsOpportunityRow[];
  season: string;
  onSeasonChange: (season: string) => void;
}) {
  const [pitchIndex, setPitchIndex] = useState(0);
  const [appearance, setAppearance] = useState<string | null>(null);
  const [autoplay, setAutoplay] = useState(false);
  const teamReplayEntries = useMemo(
    () =>
      ([...(replay?.entries ?? []), ...(replay?.reliever_entries ?? [])])
        .filter((entry) => entry.snapshot.fielding_team === team.abbr)
        .sort((a, b) => {
          const order = (a.snapshot.team_appearance_order ?? 1) - (b.snapshot.team_appearance_order ?? 1);
          return order || pitchCount(a) - pitchCount(b);
        }),
    [replay, team.abbr],
  );
  const appearances = useMemo(() => {
    const grouped = new Map<string, { key: string; label: string; role: string; count: number; firstPitch: number }>();
    for (const entry of teamReplayEntries) {
      const key = appearanceKey(entry);
      const role = isRelieverReplayEntry(entry) ? "Reliever" : "Starter";
      const existing = grouped.get(key);
      if (existing) {
        existing.count += 1;
        existing.firstPitch = Math.min(existing.firstPitch, pitchCount(entry));
        continue;
      }
      grouped.set(key, {
        key,
        role,
        label: `${entry.snapshot.pitcher_name} · ${role}`,
        count: 1,
        firstPitch: pitchCount(entry),
      });
    }
    return Array.from(grouped.values()).sort((a, b) => {
      const roleOrder = a.role === b.role ? 0 : a.role === "Starter" ? -1 : 1;
      return roleOrder || a.firstPitch - b.firstPitch;
    });
  }, [teamReplayEntries]);
  const selectedAppearanceKey = appearances.some((item) => item.key === appearance) ? appearance : appearances[0]?.key ?? null;
  const entries = useMemo(
    () =>
      teamReplayEntries
        .filter((entry) => appearanceKey(entry) === selectedAppearanceKey)
        .sort((a, b) => pitchCount(a) - pitchCount(b)),
    [selectedAppearanceKey, teamReplayEntries],
  );
  const selectedIndex = Math.min(pitchIndex, Math.max(0, entries.length - 1));
  const displayStatuses = useMemo(() => monotonicStatuses(entries), [entries]);
  const selected = entries[selectedIndex] ?? null;
  const displayStatus = selected ? displayStatuses[selectedIndex] ?? statusLabel(selected.recommendation.status) : "STAY";
  const previous = selectedIndex > 0 ? entries[selectedIndex - 1] ?? null : null;
  const previousStatus = selectedIndex > 0 ? displayStatuses[selectedIndex - 1] ?? "STAY" : "STAY";
  const selectedGame = games.find((game) => game.game_id === selectedGameId) ?? games[0] ?? null;
  const teamPitchers = selectedTeamPitchers(recap, team);
  const teamStarters = teamPitchers.filter((pitcher) => statusLabel(pitcher.role) !== "RELIEVER");
  const teamRelievers = teamPitchers.filter((pitcher) => statusLabel(pitcher.role) === "RELIEVER");
  const keyPitcher = teamStarters.find((pitcher) => pitcher.first_pull_now_inning != null || pitcher.first_alert_inning != null) ?? teamStarters[0] ?? teamPitchers[0] ?? null;
  const pullIndex = displayStatuses.findIndex((status) => statusRank(status) >= statusRank("PULL NOW"));
  const relieverActionIndex = displayStatuses.findIndex((status) => statusRank(status) >= statusRank("WATCH"));
  const actionIndex = selected && isRelieverReplayEntry(selected) ? relieverActionIndex : pullIndex;
  const pullEntry = pullIndex >= 0 ? entries[pullIndex] ?? null : null;
  const pullMetrics = pullWindowMetrics(pullEntry);
  const hasWatchSignal = statusRank(displayStatus) >= statusRank("WATCH");
  const bestCandidate = selected?.top_candidates?.find((candidate) => candidate.available) ?? selected?.top_candidates?.[0] ?? null;
  const selectedState = selected ? replayState(selected) : null;
  const selectedIsReliever = isRelieverReplayEntry(selected);
  const selectedOpportunity = opportunityForPitch(selected, preventableRows, selectedGameId);
  const selectedPreventableRuns = preventableRunsForPitch(selected, selectedOpportunity);
  const eventLabel = selected && replay ? entryEventLabel(selected, previous, displayStatus, previousStatus, replay) : null;
  const pitcherOnlyCondition = replayConditionSummary(selected);
  const signalDwellSummary = replaySignalDwellSummary(entries, displayStatuses, selectedIndex);
  const modelDecisionSummary = replayRecommendationSummary(pullEntry ?? selected);
  const degradationPressure = selectedState?.normalized_degradation_score ?? scaledPercent(selectedState?.enhanced_degradation_score ?? selectedState?.degradation_score, 3);
  const commandPressure = Math.max(
    scaledPercent(selectedState?.zone_miss_distance_10, 0.8),
    scaledPercent(selectedState?.location_dispersion_10, 1.4),
    scaledPercent(selectedState?.ball_rate_10, 1),
  );
  const stuffPressure = Math.max(
    scaledPercent(Math.abs(selected ? velocityDrop(selected) ?? 0 : 0), 4),
    scaledPercent(Math.abs(selectedState?.spin_slope_5 ?? 0), 250),
    scaledPercent(Math.abs(selectedState?.pitch_mix_drift_10 ?? 0), 1),
  );
  const decayPressure = scaledPercent((selectedState?.inning_decay_factor ?? 0) + (selectedState?.tto_decay_factor ?? 0), 3);
  const topComponents = Object.entries(selectedState?.component_contributions ?? {})
    .sort((a, b) => Math.abs(b[1] ?? 0) - Math.abs(a[1] ?? 0))
    .slice(0, 5);
  const velocityTrend = [
    selectedState?.seasonal_velo_baseline,
    selectedState?.velo_mean_15,
    selectedState?.velo_mean_10,
    selectedState?.velo_mean_5,
    selected?.snapshot.release_speed,
  ];
  const spinTrend = [
    selectedState?.seasonal_spin_baseline,
    selectedState?.spin_mean_15,
    selectedState?.spin_mean_10,
    selectedState?.spin_mean_5,
  ];
  const reliefOptions = selected?.top_candidates?.slice(0, 3) ?? [];

  useEffect(() => {
    document.body.classList.add("audit-immersive");
    return () => {
      document.body.classList.remove("audit-immersive");
    };
  }, []);

  useEffect(() => {
    setPitchIndex(0);
    setAutoplay(false);
  }, [selectedGameId]);

  useEffect(() => {
    setPitchIndex(0);
    setAutoplay(false);
  }, [selectedAppearanceKey]);

  useEffect(() => {
    if (!autoplay || entries.length <= 1) return;
    const interval = window.setInterval(() => {
      setPitchIndex((current) => {
        const next = Math.min(entries.length - 1, current + 1);
        if (next === current) window.clearInterval(interval);
        return next;
      });
    }, 850);
    return () => window.clearInterval(interval);
  }, [autoplay, entries.length]);

  useEffect(() => {
    if (selectedIndex >= entries.length - 1) setAutoplay(false);
  }, [entries.length, selectedIndex]);

  const accents = teamAccents(team.abbr);
  const themeStyle = {
    "--team-primary": accents.primary,
    "--team-label": accents.label,
    "--team-dot": accents.dot,
    "--team-row-bg": accents.rowBg,
  } as CSSProperties;
  return (
    <section className="workflow theme-mobian workflow-audit" style={themeStyle}>
      <header className="audit-header">
        <h2 className="audit-header__page">GAME REPLAYS</h2>
        <div className="audit-header__filters">
          <label className="audit-filter">
            <span>Season</span>
            <select value={season} onChange={(event) => onSeasonChange(event.target.value)}>
              <option value="2026">2026</option>
              <option value="2025">2025</option>
            </select>
          </label>
          <label className="audit-filter">
            <span>Game</span>
            <select value={selectedGameId ?? ""} onChange={(event) => onGameChange(event.target.value)}>
              {games.map((game) => (
                <option key={game.game_id} value={game.game_id}>
                  {gameLabel(game)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {!selectedGameId || !replay || !selected ? (
        <EmptyState title="No replay loaded" detail="Select a completed game with finalized pitch-level replay detail." />
      ) : (
        <>
          <article className="panel replay-panel">
            <div className={`signal-banner signal-${signalClass(displayStatus)}`}>
              <strong>{selectedIsReliever ? `RSS ${displayStatus}` : displayStatus}</strong>
              {signalDwellSummary ? (
                <div className="signal-banner__dwell">
                  <span className="signal-banner__dwell-label">Signal Dwell</span>
                  <span className="signal-banner__dwell-value">{signalDwellSummary}</span>
                </div>
              ) : null}
            </div>
            {eventLabel && eventLabel.title ? (
              <div className={`event-callout event-callout--${eventLabel.tone}`}>
                <strong>{eventLabel.title}</strong>
                <span>{eventLabel.detail}</span>
              </div>
            ) : null}

            <div className="replay-layout">
              <aside className="pitch-window-summary" style={{ borderTop: `3px solid ${accents.primary}` }}>
                <p className="pws-heading">Pitch Window Summary</p>

                <section className="pws-section pws-pitcher-section">
                  <p className="pws-eyebrow">Starting Pitcher</p>
                  <h3 className="pws-pitcher">{displayPersonName(selected.snapshot.pitcher_name)}</h3>
                  <div className="pws-stats">
                    <div className="pws-stat">
                      <span>Inning</span>
                      <strong>
                        {selected.snapshot.inning ?? "—"}
                        {(() => {
                          const half = (selected.snapshot.half || "").toLowerCase();
                          if (half.startsWith("t")) return <ArrowUp size={14} aria-label="Top" />;
                          if (half.startsWith("b")) return <ArrowDown size={14} aria-label="Bottom" />;
                          return null;
                        })()}
                      </strong>
                    </div>
                    <div className="pws-stat">
                      <span>Pitches</span>
                      <strong>{pitchCount(selected)}</strong>
                    </div>
                    <div className="pws-stat">
                      <span>{selectedIsReliever ? "Batters" : "TTO"}</span>
                      <strong>{selectedIsReliever ? selectedState?.batters_faced_in_game ?? "—" : selectedState?.times_through_order ?? "—"}</strong>
                    </div>
                  </div>
                </section>

                <section className="pws-section pws-at-bat-section">
                  <p className="pws-eyebrow">At Bat</p>
                  <div className="pws-batter">
                    <span className="pws-batter__name">{batterDisplayName(selected.snapshot)}</span>
                    {batterHandedness(selected.snapshot) ? (
                      <span className="pws-batter__hand">{batterHandedness(selected.snapshot)}H</span>
                    ) : null}
                  </div>
                </section>

                <div className="pws-cob">
                  <div className="pws-cob__cell">
                    <span>Count</span>
                    <strong className="pws-cob__count">{formatCount(selected.snapshot)}</strong>
                  </div>
                  <div className="pws-cob__cell">
                    <span>Outs</span>
                    <OutsDots outs={selected.snapshot.outs} />
                  </div>
                  <div className="pws-cob__cell">
                    <span>Bases</span>
                    <BasesDiamond baseState={selected.snapshot.base_state} />
                  </div>
                </div>

                <section className="pws-section pws-cpw">
                  <p className="pws-eyebrow">Current Pitch Window</p>
                  {(pitchOutcomeLabel(selected.snapshot) || hitClassificationLabel(selected.snapshot)) ? (
                    <div className="pws-cpw__chips">
                      {pitchOutcomeLabel(selected.snapshot) ? (
                        <span className="pws-cpw__outcome">{pitchOutcomeLabel(selected.snapshot)}</span>
                      ) : null}
                      {hitClassificationLabel(selected.snapshot) ? (
                        <span className="pws-cpw__hitclass">{hitClassificationLabel(selected.snapshot)}</span>
                      ) : null}
                    </div>
                  ) : null}
                  {(() => {
                    const raw = String(selected.recommendation?.gm_summary ?? selected.recommendation?.decision_summary ?? "").trim();
                    if (!raw) return null;
                    const firstSentence = raw.split(/\.\s+/)[0].replace(/\.$/, "").trim();
                    return firstSentence ? <p className="pws-cpw__rationale">{`${firstSentence}.`}</p> : null;
                  })()}
                </section>

                <div className="pws-score">
                  {(() => {
                    const ownIsAway = replay.game.away_team === team.abbr;
                    const awayTone = ownIsAway ? "own" : "opp";
                    const homeTone = ownIsAway ? "opp" : "own";
                    return (
                      <>
                        <span className={`pws-score__team pws-score__team--${awayTone}`} style={ownIsAway ? { color: accents.label } : undefined}>{replay.game.away_team}</span>
                        <strong className="pws-score__num">{selected.snapshot.away_score ?? 0}</strong>
                        <span className="pws-score__dash">—</span>
                        <strong className="pws-score__num">{selected.snapshot.home_score ?? 0}</strong>
                        <span className={`pws-score__team pws-score__team--${homeTone}`} style={!ownIsAway ? { color: accents.label } : undefined}>{replay.game.home_team}</span>
                      </>
                    );
                  })()}
                </div>
              </aside>

              <div className="strike-zone-column">
                <PitchPlot entries={entries} selectedIndex={selectedIndex} onSelect={setPitchIndex} />
              </div>

              <aside className="model-synthesis-card">
                <p className="eyebrow signal-summary-eyebrow">Signal Summary</p>
                <div className="decision-score-row">
                  {(() => {
                    const degValue = selectedState?.enhanced_degradation_score ?? selectedState?.degradation_score;
                    const degTier = degValue == null ? "neutral" : degValue >= 2 ? "bad" : degValue >= 1 ? "warn" : "good";
                    const degColor = degTier === "bad" ? "#e05b4b" : degTier === "warn" ? "#f0d050" : degTier === "good" ? "#2ec4a0" : "#7a7a7a";
                    const pct = Math.round(clamp(degradationPressure) * 100);
                    return (
                      <div className="decision-score-col">
                        <span className="decision-score-label">Degradation Score</span>
                        <div
                          className={`degradation-ring degradation-ring--lg degradation-ring--${degTier}`}
                          style={{
                            "--ring": `${pct}%`,
                            "--ring-color": degColor,
                          } as CSSProperties}
                        >
                          <strong>{fmtNumber(degValue, 2)}</strong>
                        </div>
                      </div>
                    );
                  })()}
                  <div className="decision-score-col">
                    <span className="decision-score-label">Preventable Runs</span>
                    <strong className="decision-score-value">{selectedIsReliever ? "Reliever RSS" : fmtRuns(selectedPreventableRuns)}</strong>
                    <em className="decision-score-note">{selectedIsReliever ? `RSS ${fmtNumber(selectedState?.rss_score, 2)}` : selectedOpportunity ? "Calibrated opportunity model" : "Not attached to this pitch window"}</em>
                  </div>
                </div>
                <div className="decision-gauge-grid">
                  <GaugeMetric label="Stuff pressure" value={fmtPct(stuffPressure)} percent={stuffPressure} tone="bad" />
                  <GaugeMetric label="Command pressure" value={fmtPct(commandPressure)} percent={commandPressure} tone="warn" />
                  <GaugeMetric label="Decay pressure" value={fmtPct(decayPressure)} percent={decayPressure} tone="gold" />
                  <GaugeMetric label="Leverage" value={fmtNumber(selected.snapshot.leverage_index, 2)} percent={scaledPercent(selected.snapshot.leverage_index, 3)} tone="gold" />
                </div>
                <div className={`decision-delta decision-delta--${hasWatchSignal ? "active" : "locked"}`}>
                  <strong>{hasWatchSignal ? "Relief Edge" : "Relief Edge unlocks at WATCH"}</strong>
                  {selectedIsReliever ? (
                    <p>
                      This bullpen view tracks the reliever’s own RSS: stuff, command, outcome, handoff, and workload pressure after entering the game.
                    </p>
                  ) : hasWatchSignal ? (
                    <p>
                      {bestCandidate?.player_name || "Best alternative"} changes the next-batter pocket by{" "}
                      <b>{fmtSigned(selected.recommendation.decision_delta, 2)}</b> runs versus staying with the starter.
                    </p>
                  ) : (
                    <p>Before WATCH, the replay stays focused on pitcher evidence. Bullpen alternatives are shown once the first action signal appears.</p>
                  )}
                </div>
              </aside>
            </div>

            {appearances.length > 1 ? (
              <div className="appearance-switcher">
                {appearances.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={item.key === selectedAppearanceKey ? "active" : ""}
                    onClick={() => setAppearance(item.key)}
                  >
                    {item.label}
                    <span>{item.count} pitches</span>
                  </button>
                ))}
              </div>
            ) : null}

            <SignalTimeline entries={entries} statuses={displayStatuses} selectedIndex={selectedIndex} onSelect={setPitchIndex} />
            <div className="pitch-controls">
              <button type="button" onClick={() => setPitchIndex(Math.max(0, pitchIndex - 1))}>Previous</button>
              <input
                type="range"
                min={0}
                max={Math.max(0, entries.length - 1)}
                value={Math.min(pitchIndex, Math.max(0, entries.length - 1))}
                onChange={(event) => setPitchIndex(Number(event.target.value))}
              />
              <button type="button" className={autoplay ? "active" : ""} onClick={() => setAutoplay((current) => !current)}>
                {autoplay ? "Pause" : "Autoplay"}
              </button>
              <button type="button" onClick={() => setPitchIndex(Math.min(entries.length - 1, pitchIndex + 1))}>Next</button>
              <button type="button" disabled={actionIndex < 0} onClick={() => setPitchIndex(actionIndex >= 0 ? actionIndex : pitchIndex)}>
                {selectedIsReliever ? "Jump to RSS Signal" : "Jump to Pull Now"}
              </button>
            </div>
          </article>

          <article className="panel evidence-panel">
            <div className="panel-title">
              <p className="eyebrow model-signal-eyebrow">
                <span className="model-signal-dot" aria-hidden="true" />
                Model Signal Factors
                <span
                  className="model-signal-info"
                  title="Tracked inputs feeding the headline signal. Missing values are shown as unavailable rather than estimated."
                  aria-label="Description"
                >i</span>
              </p>
            </div>
            <div className="evidence-grid">
              <section>
                <h4>Stuff</h4>
                <TrendSparkline
                  label="Fastball velocity"
                  value={`${fmtNumber(selected.snapshot.release_speed ?? selectedState?.velo_mean_5, 1)} mph`}
                  detail={`Baseline ${fmtNumber(selectedState?.seasonal_velo_baseline, 1)} · trend ${fmtSigned(selectedState?.velo_slope_5, 2)} mph`}
                  points={velocityTrend}
                />
                <TrendSparkline
                  label="Fastball spin"
                  value={`${fmtNumber(selectedState?.spin_mean_5, 0)} rpm`}
                  detail={`Baseline ${fmtNumber(selectedState?.seasonal_spin_baseline, 0)} · trend ${fmtSigned(selectedState?.spin_slope_5, 0)} rpm`}
                  points={spinTrend}
                />
                <GaugeMetric label="Swinging-strike rate" value={fmtRate(selectedState?.whiff_rate_15)} detail={`Opponent-adjusted change ${fmtSigned(selectedState?.opponent_adjusted_whiff_drop, 2)}`} percent={selectedState?.whiff_rate_15 ?? undefined} tone="gold" role={factorRole(selectedState?.whiff_rate_15, "gold")} />
                <GaugeMetric label="Pitch mix drift" value={fmtNumber(selectedState?.pitch_mix_drift_10, 2)} detail="How far recent pitch selection has moved from expected mix." percent={scaledPercent(selectedState?.pitch_mix_drift_10, 1)} tone="warn" role={factorRole(scaledPercent(selectedState?.pitch_mix_drift_10, 1), "warn")} />
                <StuffConditionCard body={pitcherOnlyCondition} />
              </section>
              <section>
                <h4>Command and Contact</h4>
                <GaugeMetric label="Strike rate" value={fmtRate(selectedState?.strike_rate_10)} detail="Last 10 pitches." percent={selectedState?.strike_rate_10 ?? undefined} tone="good" role={factorRole(selectedState?.strike_rate_10, "good")} />
                <GaugeMetric label="Called-strike rate" value={fmtRate(selectedState?.called_strike_rate_15)} detail="Called strikes over the recent command window." percent={selectedState?.called_strike_rate_15 ?? undefined} tone="good" role={factorRole(selectedState?.called_strike_rate_15, "good")} />
                <GaugeMetric label="Chase rate proxy" value={fmtRate(selectedState?.chase_proxy_rate_15)} detail="Hitters expanding against him." percent={selectedState?.chase_proxy_rate_15 ?? undefined} tone="good" role={factorRole(selectedState?.chase_proxy_rate_15, "good")} />
                <GaugeMetric label="Hard contact" value={fmtRate(selectedState?.hard_contact_rate_15)} detail="Recent contact-quality pressure." percent={selectedState?.hard_contact_rate_15 ?? undefined} tone="bad" role={factorRole(selectedState?.hard_contact_rate_15, "bad")} />
                <GaugeMetric label="Zone miss" value={`${fmtNumber(selectedState?.zone_miss_distance_10, 2)} ft`} detail={`5-pitch window ${fmtNumber(selectedState?.zone_miss_distance_5, 2)} ft.`} percent={scaledPercent(selectedState?.zone_miss_distance_10, 0.8)} tone="warn" role={factorRole(scaledPercent(selectedState?.zone_miss_distance_10, 0.8), "warn")} />
                <GaugeMetric label="Command spread" value={fmtNumber(selectedState?.location_dispersion_10, 2)} detail={`5-pitch spread ${fmtNumber(selectedState?.location_dispersion_5, 2)}.`} percent={scaledPercent(selectedState?.location_dispersion_10, 1.4)} tone="warn" role={factorRole(scaledPercent(selectedState?.location_dispersion_10, 1.4), "warn")} />
              </section>
              <section>
                <h4>Decision Context</h4>
                <GaugeMetric label="Game leverage" value={fmtNumber(selected.snapshot.leverage_index, 2)} detail={selected.snapshot.leverage_index >= 1.5 ? "High-value game state." : "Lower leverage window."} percent={scaledPercent(selected.snapshot.leverage_index, 3)} tone="gold" role={factorRole(scaledPercent(selected.snapshot.leverage_index, 3), "gold")} />
                <GaugeMetric label="Normalized degradation" value={fmtRate(selectedState?.normalized_degradation_score)} detail="Normalized against comparable MLB windows." percent={selectedState?.normalized_degradation_score ?? undefined} tone="bad" role={factorRole(selectedState?.normalized_degradation_score, "bad")} />
                <GaugeMetric label="Enhanced degradation" value={fmtNumber(selectedState?.enhanced_degradation_score, 2)} detail="Weighted model read after feature normalization." percent={scaledPercent(selectedState?.enhanced_degradation_score, 3)} tone="bad" role={factorRole(scaledPercent(selectedState?.enhanced_degradation_score, 3), "bad")} />
                <GaugeMetric label="League percentile" value={fmtRate(selectedState?.empirical_degradation_percentile)} detail={`${selectedState?.empirical_degradation_sample_count ?? "—"} comparable windows.`} percent={selectedState?.empirical_degradation_percentile ?? undefined} tone="gold" role={factorRole(selectedState?.empirical_degradation_percentile, "gold")} />
                <GaugeMetric label="Pitcher history percentile" value={fmtRate(selectedState?.pitcher_empirical_degradation_percentile)} detail={`${selectedState?.pitcher_empirical_degradation_sample_count ?? "—"} pitcher windows.`} percent={selectedState?.pitcher_empirical_degradation_percentile ?? undefined} tone="gold" role={factorRole(selectedState?.pitcher_empirical_degradation_percentile, "gold")} />
                <GaugeMetric label="Decay pressure" value={`${fmtNumber(selectedState?.inning_decay_factor, 2)} inning · ${fmtNumber(selectedState?.tto_decay_factor, 2)} TTO`} detail={`${selectedState?.official_batters_faced_in_game ?? selectedState?.batters_faced_in_game ?? "—"} batters faced.`} percent={scaledPercent((selectedState?.inning_decay_factor ?? 0) + (selectedState?.tto_decay_factor ?? 0), 3)} tone="warn" role={factorRole(scaledPercent((selectedState?.inning_decay_factor ?? 0) + (selectedState?.tto_decay_factor ?? 0), 3), "warn")} />
              </section>
              {hasWatchSignal ? (
                <section>
                  <h4>Relief Alternatives</h4>
                  {reliefOptions.length === 0 ? (
                    <GaugeMetric label="Bullpen options" value={UNAVAILABLE} detail="No relief alternatives were attached to this pitch window." />
                  ) : (
                    reliefOptions.map((candidate) => (
                      <GaugeMetric
                        key={candidate.player_id}
                        label={candidate.player_name}
                        value={candidate.available ? "Available" : "Not available"}
                        detail={`Net option ${fmtNumber(candidate.net_option_score, 2)} · usage cost ${fmtNumber(candidate.usage_cost, 2)} · matchup ${fmtNumber(candidate.direct_matchup_fit, 2)}`}
                        percent={scaledPercent(candidate.net_option_score, 1)}
                        tone={candidate.available ? "good" : "neutral"}
                      />
                    ))
                  )}
                </section>
              ) : null}
            </div>
          </article>

          {teamRelievers.length > 0 ? (
            <article className="panel rss-panel">
              <div className="panel-title">
                <p className="eyebrow">Reliever Stress Signal</p>
              </div>
              <div className="rss-table">
                {teamRelievers.map((pitcher, index) => (
                  <div key={pitcher.pitcher_id || pitcher.pitcher_name} className="rss-row">
                    <div>
                      <div className="rss-row__name">
                        <strong>{pitcher.pitcher_name}</strong>
                        {index === teamRelievers.length - 1 ? (
                          <span className="rss-finished-pill">Finished Game</span>
                        ) : null}
                      </div>
                      <span>{fmtNumber(pitcher.innings_pitched, 1)} IP · {pitcher.pitch_count ?? "—"} pitches · {pitcher.runs_allowed_total ?? "—"} R</span>
                    </div>
                    <div>
                      <strong>{relieverRssLabel(pitcher)}</strong>
                      <span>{relieverRssTimingCopy(pitcher)}</span>
                      <div className="rss-component-grid">
                        {relieverRssComponents(pitcher).map((component) => (
                          <span key={component.label} className="rss-component">
                            <em>{component.label}</em>
                            <b>{component.value == null ? UNAVAILABLE : fmtNumber(component.value, 2)}</b>
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <strong>Outcome</strong>
                      <span>{relieverOutcomeCopy(pitcher)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          ) : null}

          <article className="panel counterfactual-panel">
            <p className="eyebrow">Actual Outcome Summary</p>
            <div className="counterfactual-grid">
              <div className="outcome-card">
                <strong className="outcome-card__title">Pull Now Summary</strong>
                <p>{actionPointCopy(keyPitcher)}</p>
                <ul className="mini-metric-list">
                  <li>Stuff <b>{pullMetrics.stuff}</b></li>
                  <li>Decay <b>{pullMetrics.decay}</b></li>
                  <li>Degradation <b>{pullMetrics.degradation}</b></li>
                </ul>
              </div>
              <div className="outcome-card">
                <strong className="outcome-card__title">Why It Fired</strong>
                <p>{modelDecisionSummary}</p>
              </div>
              <div className="outcome-card">
                <strong className="outcome-card__title">Actual Result</strong>
                <p>{exitAndDamageCopy(keyPitcher)}</p>
              </div>
            </div>
          </article>

        </>
      )}
    </section>
  );
}

function PitcherAllocation({ profiles, bullpenOptions }: { profiles: PitcherProfile[]; bullpenOptions: BullpenOption[] }) {
  const [mode, setMode] = useState<"starters" | "relievers">("starters");
  const starterProfiles = profiles.slice().sort((a, b) => (b.projectedRunsSaved ?? -Infinity) - (a.projectedRunsSaved ?? -Infinity));
  const relieverProfiles = profiles
    .filter((profile) => profile.appearances >= 8 || (avg(profile.gameLog.map((game) => game.maxPitchCount)) ?? 99) <= 45)
    .sort((a, b) => (b.pitchWindows ?? 0) - (a.pitchWindows ?? 0));

  return (
    <section className="workflow">
      <div className="page-lead compact">
        <div>
          <p className="eyebrow">Pitcher Allocation</p>
          <h2>Who should carry which innings and situations?</h2>
          <p>Starter decay and relief stress are shown together so a club can separate “pull him” from “we need a better alternative.”</p>
        </div>
        <div className="toggle">
          <button type="button" className={mode === "starters" ? "active" : ""} onClick={() => setMode("starters")}>Starters</button>
          <button type="button" className={mode === "relievers" ? "active" : ""} onClick={() => setMode("relievers")}>Relievers</button>
        </div>
      </div>

      {mode === "starters" ? (
        <div className="profile-board">
          {starterProfiles.slice(0, 12).map((profile) => (
            <article key={profile.pitcherId || profile.pitcher} className="profile-card">
              <div>
                <p className="eyebrow">{profile.team}</p>
                <h3>{profile.pitcher}</h3>
                <p>{profile.appearances} appearances · {profile.pitchWindows} model windows</p>
              </div>
              <div className="profile-stats">
                <span>Preventable Runs <strong>{fmtRuns(profile.projectedRunsSaved)}</strong></span>
                <span>Pull Now Games <strong>{profile.pullNowGames}</strong></span>
                <span>Avg Degradation <strong>{fmtNumber(profile.avgDegradation, 2)}</strong></span>
                <span>Max Degradation <strong>{fmtNumber(profile.maxDegradation, 2)}</strong></span>
              </div>
              <MiniCurve values={profile.gameLog.flatMap((game) => game.stuffCurve).slice(-12)} />
              <p className="recommendation-copy">
                {profile.pullNowGames > 2
                  ? "Review repeat late-game exposure and define a firmer hook window."
                  : profile.projectedRunsSaved != null && profile.projectedRunsSaved > 0
                    ? "Audit the specific games driving preventable-run concentration."
                    : "No clear allocation change is indicated from current profile evidence."}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <div className="two-column">
          <article className="panel">
            <div className="panel-title">
              <p className="eyebrow">Current Relief Alternatives</p>
              <h3>Arms attached to active model windows.</h3>
            </div>
            {bullpenOptions.length === 0 ? (
              <EmptyState title="No current alternatives" detail="No active decision window returned a named relief alternative." />
            ) : (
              <div className="compact-list">
                {bullpenOptions.map((option) => (
                  <div key={option.id} className="compact-row">
                    <strong>{option.name}</strong>
                    <span>{option.availability}</span>
                    <span>RSS {fmtNumber(option.rss, 2)}</span>
                    <span>Usage {fmtNumber(option.usageCost, 2)}</span>
                    <span>Net {fmtNumber(option.netOptionScore, 2)}</span>
                  </div>
                ))}
              </div>
            )}
          </article>
          <article className="panel">
            <div className="panel-title">
              <p className="eyebrow">Short-Window Profiles</p>
              <h3>Possible multi-inning relief capacity.</h3>
            </div>
            {relieverProfiles.length === 0 ? (
              <EmptyState title="No short-window profiles" detail="Relief-profile classification will remain unavailable until the role source is explicit." />
            ) : (
              <div className="compact-list">
                {relieverProfiles.slice(0, 10).map((profile) => (
                  <div key={profile.pitcherId || profile.pitcher} className="compact-row">
                    <strong>{profile.pitcher}</strong>
                    <span>{profile.appearances} app</span>
                    <span>{profile.pitchWindows} windows</span>
                    <span>Avg deg {fmtNumber(profile.avgDegradation, 2)}</span>
                    <span>{fmtRuns(profile.projectedRunsSaved)}</span>
                  </div>
                ))}
              </div>
            )}
          </article>
        </div>
      )}
    </section>
  );
}

function RosterConstruction({
  team,
  profiles,
  auditSummary,
  candidates,
}: {
  team: Team;
  profiles: PitcherProfile[];
  auditSummary: PitchingAuditSummaryPayload | null;
  candidates: TripleAConversionCandidate[];
}) {
  const windows = auditWindows(auditSummary);
  const tandem = windows.filter((window) => matrixCellForWindow(window) === "tandem").length;
  const workload = windows.filter((window) => matrixCellForWindow(window) === "workload").length;
  const repeatDecay = profiles.filter((profile) => profile.pullNowGames >= 2).length;
  const teamCandidates = candidates.filter((candidate) => candidate.parentClub.toLowerCase().includes(team.club.toLowerCase()) || candidate.parentClub.toLowerCase().includes(team.abbr.toLowerCase()));
  const visibleCandidates = (teamCandidates.length > 0 ? teamCandidates : candidates).slice(0, 8);

  return (
    <section className="workflow">
      <div className="page-lead">
        <div>
          <p className="eyebrow">Roster Construction</p>
          <h2>Turn repeated allocation stress into roster actions.</h2>
          <p>This view translates the audit into staff-building questions: who needs protection, who needs support, and which internal arms could change the answer.</p>
        </div>
      </div>

      <div className="kpi-row">
        <KPI label="Tandem Need" value={String(tandem)} detail="Starter decay with a better relief alternative." tone="bad" />
        <KPI label="Workload Constraint" value={String(workload)} detail="Starter and relief alternative both below target." tone="gold" />
        <KPI label="Repeat Decay Profiles" value={String(repeatDecay)} detail="Pitchers with multiple Pull Now games." />
        <KPI label="Triple-A Candidates" value={String(visibleCandidates.length)} detail="Potential internal relief conversion pool." />
      </div>

      <div className="roster-actions">
        <article className="panel">
          <p className="eyebrow">Staff-Building Questions</p>
          <h3>What the front office should investigate.</h3>
          <ul className="action-list">
            <li><strong>Protect cliff droppers.</strong><span>Define firmer starter windows for pitchers with repeated Pull Now games.</span></li>
            <li><strong>Add bridge capacity.</strong><span>If tandem and workload cells repeat, the club needs a reliable 2-inning relief answer.</span></li>
            <li><strong>Convert selectively.</strong><span>Use Triple-A short-window quality plus decay risk to identify stretch-run relief candidates.</span></li>
            <li><strong>Do not overclaim.</strong><span>Role and day-of availability remain rule-based unless club-confirmed data is supplied.</span></li>
          </ul>
        </article>

        <article className="panel">
          <p className="eyebrow">Triple-A Conversion Candidates</p>
          <h3>Internal arms worth reviewing.</h3>
          {visibleCandidates.length === 0 ? (
            <EmptyState title="No candidates returned" detail="Triple-A candidates will populate when the API returns conversion data." />
          ) : (
            <div className="candidate-list">
              {visibleCandidates.map((candidate) => (
                <div key={candidate.id} className="candidate-card">
                  <strong>{candidate.pitcher}</strong>
                  <span>{candidate.affiliate} · {candidate.parentClub}</span>
                  <em>{candidate.currentRole} → {candidate.recommendedRole}</em>
                  <div>
                    <span>Conversion {candidate.reliefConversionScore}</span>
                    <span>Mirage risk {fmtPct(candidate.mirageRisk)}</span>
                    <span>{fmtRuns(candidate.projectedRunsSaved)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>
      </div>
    </section>
  );
}

function BriefingPreview({ response, team }: { response: PitchingRecapEmailResponse; team: Team }) {
  if (response.html) {
    return (
      <article className="briefing-preview-card briefing-preview-html-card">
        <div className="briefing-preview-browser-header">
          <span>In-app email preview</span>
          <strong>{response.subject ?? `brAIn — ${team.abbr} Recap`}</strong>
        </div>
        <div className="briefing-html-preview" dangerouslySetInnerHTML={{ __html: response.html }} />
      </article>
    );
  }

  const recap = response.recap;
  const pitchers = selectedTeamPitchers(recap, team);
  const starters = pitchers.filter((pitcher) => pitcherRoleLabel(pitcher) !== "Reliever");
  const relievers = pitchers.filter((pitcher) => pitcherRoleLabel(pitcher) === "Reliever");
  const keyPitcher = starters.find((pitcher) => pitcher.first_pull_now_inning != null || pitcher.first_alert_inning != null) ?? starters[0] ?? pitchers[0] ?? null;
  const pullSignals = pitchers.filter((pitcher) => pitcher.first_pull_now_inning != null).length;
  const insights = pitchers.length + pullSignals + relievers.filter((pitcher) => pitcher.rss_score != null).length;

  return (
    <article className="briefing-preview-card">
      <header className="briefing-email-header">
        <p className="eyebrow">Pitcher Intel</p>
        <h3>{response.subject ?? `brAIn — ${team.abbr} Recap`}</h3>
        <span>{formatDateText(recap.date)}</span>
      </header>

      <div className="briefing-preview-kpis">
        <KPI label="Delivery" value={response.sent ? "Sent" : "Preview"} detail={response.sent_to?.length ? response.sent_to.join(", ") : "Generated in app"} />
        <KPI label="Starters" value={String(starters.length)} detail="Team starter appearances in recap." />
        <KPI label="Relievers" value={String(relievers.length)} detail="Team relief appearances in recap." />
        <KPI label="Pull Signals" value={String(pullSignals)} detail="Model Pull Now triggers." tone={pullSignals > 0 ? "bad" : "neutral"} />
      </div>

      <div className="briefing-preview-title">
        <div>
          <h3>{keyPitcher?.pitcher_name ?? team.name} vs. {recapOpponent(recap, team)}</h3>
          <p>{formatDateText(recap.date)} · {recapScoreLine(recap)}</p>
          {keyPitcher ? (
            <p>
              {fmtNumber(keyPitcher.innings_pitched, 1)} IP · {keyPitcher.pitch_count ?? "—"} pitches · {keyPitcher.runs_allowed_total ?? "—"} R
            </p>
          ) : null}
        </div>
        <button type="button" disabled>
          Open Full Pitch-by-Pitch Replay
        </button>
      </div>

      <div className="briefing-preview-table">
        <div className="briefing-preview-table-head">
          <span>Pitcher</span>
          <span>Line</span>
          <span>Signal</span>
          <span>Role</span>
        </div>
        {pitchers.map((pitcher) => (
          <div key={`${pitcher.pitcher_id}-${pitcher.pitcher_name}`} className="briefing-preview-table-row">
            <strong>{pitcher.pitcher_name}</strong>
            <span>{fmtNumber(pitcher.innings_pitched, 1)} IP · {pitcher.runs_allowed_total ?? "—"} R · {pitcher.pitch_count ?? "—"} pitches</span>
            <span>{pitcherRoleLabel(pitcher) === "Reliever" ? relieverRssLabel(pitcher) : actionPointCopy(pitcher)}</span>
            <span>{pitcherRoleLabel(pitcher)}</span>
          </div>
        ))}
      </div>

      <section className="mound-signal-preview">
        <p className="eyebrow">Mound Signal</p>
        <p>{actionPointCopy(keyPitcher)}</p>
        <p>{exitAndDamageCopy(keyPitcher)}</p>
      </section>

      <div className="briefing-preview-sections">
        <section>
          <p className="eyebrow">Starter Read</p>
          <h4>{keyPitcher?.pitcher_name ?? "Starter"}</h4>
          <p>{teamPitcherRecapCopy(keyPitcher)}</p>
        </section>
        <section>
          <p className="eyebrow">Bullpen</p>
          <h4>{relievers.length} reliever{relievers.length === 1 ? "" : "s"} covered</h4>
          {relievers.length === 0 ? (
            <p>No team relievers were returned in this recap.</p>
          ) : (
            relievers.slice(0, 5).map((pitcher) => (
              <p key={`${pitcher.pitcher_id}-rss`}>
                <strong>{pitcher.pitcher_name}:</strong> {relieverRssLabel(pitcher)} · {relieverOutcomeCopy(pitcher)}
              </p>
            ))
          )}
        </section>
        <section>
          <p className="eyebrow">Insights</p>
          <h4>{insights}</h4>
          <p>Starter action points, reliever RSS reads, and outcome checks included in this briefing preview.</p>
        </section>
      </div>
    </article>
  );
}

function BriefingSettings({
  team,
  settings,
  status,
  onSave,
}: {
  team: Team;
  settings: PitchingRecapSettings | null;
  status: string | null;
  onSave: (patch: Partial<PitchingRecapSettings>) => Promise<void>;
}) {
  const [recapTeamsText, setRecapTeamsText] = useState("");
  const [autoTeamsText, setAutoTeamsText] = useState("");
  const [finalizedTeamsText, setFinalizedTeamsText] = useState("");
  const [recipientsByTeam, setRecipientsByTeam] = useState<Record<string, string>>({});
  const [teamToAdd, setTeamToAdd] = useState(team.abbr);
  const [previewTeam, setPreviewTeam] = useState(team.abbr);
  const [previewDate, setPreviewDate] = useState("");
  const [previewResponse, setPreviewResponse] = useState<PitchingRecapEmailResponse | null>(null);
  const [previewStatus, setPreviewStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);

  const configuredTeams = useMemo(() => {
    const values = new Set<string>();
    [...teamCsv(recapTeamsText), ...teamCsv(autoTeamsText), ...teamCsv(finalizedTeamsText), ...Object.keys(recipientsByTeam)].forEach((abbr) => {
      if (MLB_TEAMS.some((club) => club.abbr === abbr)) values.add(abbr);
    });
    if (values.size === 0) values.add(team.abbr);
    return MLB_TEAMS.map((club) => club.abbr).filter((abbr) => values.has(abbr));
  }, [autoTeamsText, finalizedTeamsText, recapTeamsText, recipientsByTeam, team.abbr]);

  const quickPickTeams = configuredTeams.slice(0, 4);
  const previewTeamObject = MLB_TEAMS.find((club) => club.abbr === previewTeam) ?? team;

  useEffect(() => {
    setRecapTeamsText((settings?.recap_teams ?? []).join(", "));
    setAutoTeamsText((settings?.auto_email_teams ?? []).join(", "));
    setFinalizedTeamsText((settings?.finalized_email_teams ?? []).join(", "));
    const teams = new Set<string>([
      team.abbr,
      ...(settings?.recap_teams ?? []),
      ...(settings?.auto_email_teams ?? []),
      ...(settings?.finalized_email_teams ?? []),
      ...Object.keys(settings?.team_recipients ?? {}),
    ]);
    const nextRecipients: Record<string, string> = {};
    teams.forEach((abbr) => {
      nextRecipients[abbr.toUpperCase()] = (settings?.team_recipients?.[abbr.toUpperCase()] ?? settings?.team_recipients?.[abbr] ?? []).join(", ");
    });
    setRecipientsByTeam(nextRecipients);
    setTeamToAdd(team.abbr);
    setPreviewTeam(team.abbr);
  }, [settings, team.abbr]);

  async function handleSave() {
    setSaving(true);
    try {
      const nextRecipients: Record<string, string[]> = {};
      configuredTeams.forEach((abbr) => {
        nextRecipients[abbr] = parseCsvList(recipientsByTeam[abbr] ?? "");
      });
      await onSave({
        recap_teams: teamCsv(recapTeamsText),
        auto_email_teams: teamCsv(autoTeamsText),
        finalized_email_teams: teamCsv(finalizedTeamsText),
        team_recipients: nextRecipients,
      });
    } catch {
      // Parent state carries the visible error message.
    } finally {
      setSaving(false);
    }
  }

  function addClubToLists() {
    const abbr = teamToAdd.toUpperCase();
    setRecapTeamsText((current) => csvSetTeam(current, abbr, true));
    setAutoTeamsText((current) => csvSetTeam(current, abbr, true));
    setFinalizedTeamsText((current) => csvSetTeam(current, abbr, true));
    setRecipientsByTeam((current) => ({
      ...current,
      [abbr]: current[abbr] ?? (settings?.team_recipients?.[abbr] ?? []).join(", "),
    }));
    setPreviewTeam(abbr);
  }

  async function resolvePreviewGame(targetTeam: string): Promise<EnterpriseGameSummary> {
    const gamePayload = await fetchEnterpriseGames({
      league: "mlb",
      team: targetTeam,
      date: previewDate || undefined,
      limit: previewDate ? 20 : 75,
    });
    const match = gamePayload.games.find((game) => game.home_team === targetTeam || game.away_team === targetTeam) ?? gamePayload.games[0];
    if (!match) {
      throw new Error(previewDate ? `No completed recap game found for ${targetTeam} on ${previewDate}.` : `No completed recap game found for ${targetTeam}.`);
    }
    return match;
  }

  async function handleGenerate(send: boolean) {
    if (!previewTeam) return;
    if (send) setSending(true);
    else setGenerating(true);
    setPreviewStatus(send ? "Sending briefing..." : "Generating briefing preview...");
    try {
      const game = await resolvePreviewGame(previewTeam);
      const response = await sendPitchingRecapEmail({ game_id: game.game_id, team: previewTeam, send }, "mlb");
      setPreviewResponse(response);
      const recipients = response.sent_to?.length ? response.sent_to.join(", ") : response.recipients?.join(", ");
      setPreviewStatus(send ? (response.sent ? `Briefing sent${recipients ? ` to ${recipients}` : ""}.` : "Briefing generated, but no email was sent.") : "Briefing preview generated.");
    } catch (caught) {
      setPreviewStatus(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setGenerating(false);
      setSending(false);
    }
  }

  async function copyPreview(kind: "email" | "text") {
    if (!previewResponse) return;
    const plainText = buildBriefingPlainText(previewResponse, previewTeamObject);
    const text = kind === "email" ? `${previewResponse.subject ?? `brAIn — ${previewTeam} Recap`}\n\n${plainText}` : plainText;
    try {
      if (kind === "email" && previewResponse.html && "ClipboardItem" in window && navigator.clipboard.write) {
        const ClipboardItemCtor = window.ClipboardItem;
        await navigator.clipboard.write([
          new ClipboardItemCtor({
            "text/html": new Blob([previewResponse.html], { type: "text/html" }),
            "text/plain": new Blob([text], { type: "text/plain" }),
          }),
        ]);
        setPreviewStatus("Rich email preview copied to clipboard.");
        return;
      }
      await navigator.clipboard.writeText(text);
      setPreviewStatus(kind === "email" ? "Email copy copied to clipboard." : "Briefing text copied to clipboard.");
    } catch {
      setPreviewStatus("Clipboard copy is unavailable in this browser.");
    }
  }

  function exportPreviewPdf() {
    if (previewResponse?.html) {
      const printWindow = window.open("", "_blank", "noopener,noreferrer");
      if (printWindow) {
        printWindow.document.open();
        printWindow.document.write(previewResponse.html);
        printWindow.document.close();
        printWindow.focus();
        printWindow.print();
        return;
      }
    }
    window.print();
  }

  return (
    <section className="workflow briefing-workflow">
      <article className="panel generate-recap-panel">
        <div className="generate-recap-header">
          <h2>Generate Recap</h2>
          <p>Select a team and date to generate or send a pitcher intel email.</p>
        </div>
        <div className="generate-recap-controls">
          <label>
            Team
            <select value={previewTeam} onChange={(event) => setPreviewTeam(event.target.value)}>
              {configuredTeams.map((abbr) => {
                const club = MLB_TEAMS.find((item) => item.abbr === abbr);
                return (
                  <option key={abbr} value={abbr}>
                    {abbr}{club ? ` · ${club.name}` : ""}
                  </option>
                );
              })}
            </select>
          </label>
          {quickPickTeams.length > 0 ? (
            <div className="quick-picks">
              <span>Quick picks</span>
              {quickPickTeams.map((abbr) => (
                <button key={abbr} type="button" className={previewTeam === abbr ? "active" : ""} onClick={() => setPreviewTeam(abbr)}>
                  {abbr}
                </button>
              ))}
            </div>
          ) : null}
          <label>
            Date
            <input type="date" value={previewDate} onChange={(event) => setPreviewDate(event.target.value)} />
          </label>
          <button type="button" onClick={() => void handleGenerate(false)} disabled={generating || sending}>
            {generating ? "Generating..." : "Generate"}
          </button>
          <button type="button" className="send-button" onClick={() => void handleGenerate(true)} disabled={generating || sending}>
            {sending ? "Sending..." : "Send Email"}
          </button>
          <button type="button" onClick={() => void copyPreview("email")} disabled={!previewResponse}>
            Copy Email
          </button>
          <button type="button" onClick={exportPreviewPdf} disabled={!previewResponse}>
            Export PDF
          </button>
          <button type="button" onClick={() => void copyPreview("text")} disabled={!previewResponse}>
            Copy Text
          </button>
        </div>
        {previewStatus ? <p className="settings-status-message">{previewStatus}</p> : null}
      </article>

      {previewResponse ? (
        <BriefingPreview response={previewResponse} team={previewTeamObject} />
      ) : (
        <article className="panel briefing-empty-preview">
          <div>
            <strong>Select a team and click Generate</strong>
            <p>Enterprise pitcher analysis for front-office staff. Each recap covers starters and relievers with analytical bullets, game box scores, and Mound Signal timing.</p>
          </div>
        </article>
      )}

      <article className="panel delivery-settings-panel">
        <div className="panel-title horizontal">
          <div>
            <p className="eyebrow">Delivery Settings</p>
            <h3>Postgame recap delivery settings.</h3>
            <p>Configure per-team recipients, delivery provider, and auto-send for nightly emails.</p>
          </div>
          <button type="button" onClick={handleSave} disabled={!settings || saving}>
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </div>

        <div className="legacy-settings-form">
          <div className="legacy-settings-row">
            <span>Automatic email delivery</span>
            <strong>{settings?.shared_email_configured ? "Enabled" : "Needs provider"}</strong>
            <em>When enabled, selected teams send after full replay detail is ready.</em>
          </div>
          <div className="legacy-settings-row">
            <span>Email provider</span>
            <strong>{settings?.email_provider ? settings.email_provider.toUpperCase() : UNAVAILABLE}</strong>
            <em>SMTP credentials are managed in the secure backend config.</em>
          </div>
          <div className="legacy-settings-row">
            <span>Add team</span>
            <div className="team-add-inline">
              <select value={teamToAdd} onChange={(event) => setTeamToAdd(event.target.value)}>
                {MLB_TEAMS.map((club) => (
                  <option key={club.abbr} value={club.abbr}>
                    {club.abbr} · {club.name}
                  </option>
                ))}
              </select>
              <button type="button" onClick={addClubToLists}>
                Add to all lists
              </button>
            </div>
            <em>Adds the club to the recap workflow, auto-send checks, finalized replay wait list, and recipient table.</em>
          </div>
          <div className="legacy-settings-row">
            <span>Teams on this page</span>
            <input value={recapTeamsText} onChange={(event) => setRecapTeamsText(event.target.value)} placeholder="ATL, LAD, NYY" />
            <em>These clubs appear in the recap workflow, quick picks, and recipient list.</em>
          </div>
          <div className="legacy-settings-row">
            <span>Automatic email teams</span>
            <input value={autoTeamsText} onChange={(event) => setAutoTeamsText(event.target.value)} placeholder="ATL, LAD, NYY" />
            <em>Only these teams are checked for automatic postgame email delivery.</em>
          </div>
          <div className="legacy-settings-row">
            <span>Finalized replay teams</span>
            <input value={finalizedTeamsText} onChange={(event) => setFinalizedTeamsText(event.target.value)} placeholder="ATL, LAD, NYY" />
            <em>For these teams, recap emails wait for canonical replay detail before anything is sent.</em>
          </div>
          <div className="legacy-settings-row recipient-block-row">
            <span>Recipients by team</span>
            <div className="recipient-team-table">
              {configuredTeams.map((abbr) => (
                <label key={abbr} className="recipient-team-row">
                  <strong>{abbr}</strong>
                  <input
                    value={recipientsByTeam[abbr] ?? ""}
                    onChange={(event) =>
                      setRecipientsByTeam((current) => ({
                        ...current,
                        [abbr]: event.target.value,
                      }))
                    }
                    placeholder="ops@example.com, pitching@example.com"
                  />
                </label>
              ))}
            </div>
            <em>Comma-separated recipients. Newly added teams appear here immediately.</em>
          </div>
        </div>
        {status ? <p className="settings-status-message">{status}</p> : null}
      </article>
    </section>
  );
}

export default function App() {
  const [selectedTeamAbbr, setSelectedTeamAbbr] = useState(initialTeamFromSearch);
  const [workflow, setWorkflow] = useState<Workflow>(initialWorkflowFromSearch);
  const [season, setSeason] = useState("2026");
  const [selectedGameId, setSelectedGameId] = useState<string | null>(initialGameIdFromSearch);
  const [games, setGames] = useState<EnterpriseGameSummary[]>([]);
  const [profilesPayload, setProfilesPayload] = useState<PitcherProfilesPayload | null>(null);
  const [auditSummary, setAuditSummary] = useState<PitchingAuditSummaryPayload | null>(null);
  const [replay, setReplay] = useState<PitchingReplayResponse | null>(null);
  const [recap, setRecap] = useState<PitchingGameRecap | null>(null);
  const [recapSettings, setRecapSettings] = useState<PitchingRecapSettings | null>(null);
  const [recapSettingsStatus, setRecapSettingsStatus] = useState<string | null>(null);

  const selectedTeam = MLB_TEAMS.find((team) => team.abbr === selectedTeamAbbr) ?? MLB_TEAMS[0];
  const { loadState, payload, error, reload } = useRunSavingBoard({ league: "mlb", team: selectedTeam.abbr, limit: 50 });
  const { payload: tripleAPayload, reload: reloadTripleA } = useRunSavingBoard({ league: "triple_a", limit: 50 });
  const {
    payload: dashboardPreventableRuns,
    error: dashboardPreventableRunsError,
    loading: dashboardPreventableRunsLoading,
    reload: reloadDashboardPreventableRuns,
  } = usePreventableRunsOpportunities({
    season,
    team: selectedTeam.abbr,
    limit: 5000,
    scope: "game_matrix",
  });
  const {
    payload: auditPreventableRuns,
    reload: reloadAuditPreventableRuns,
  } = usePreventableRunsOpportunities({
    season,
    team: selectedTeam.abbr,
    gameId: selectedGameId,
    limit: 5000,
    scope: "top",
  });
  const apiBase = getConfiguredApiBase();

  const loadRecapSettings = useCallback(async () => {
    try {
      const settings = await fetchPitchingRecapSettings("mlb");
      setRecapSettings(settings);
      setRecapSettingsStatus(null);
    } catch (caught) {
      setRecapSettings(null);
      setRecapSettingsStatus(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void loadRecapSettings();
  }, [loadRecapSettings]);

  async function handleSaveRecapSettings(patch: Partial<PitchingRecapSettings>) {
    setRecapSettingsStatus("Saving settings...");
    try {
      const settings = await savePitchingRecapSettings(patch, "mlb");
      setRecapSettings(settings);
      setRecapSettingsStatus("Settings saved.");
    } catch (caught) {
      setRecapSettingsStatus(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadClubContext() {
      const [gameResult, profileResult, auditResult] = await Promise.allSettled([
        fetchEnterpriseGames({ league: "mlb", team: selectedTeam.abbr, limit: 300 }),
        fetchPitcherProfiles({ league: "mlb", team: selectedTeam.abbr, year: season, limit: 750 }),
        fetchPitchingAuditSummary({ league: "mlb", team: selectedTeam.abbr, year: season, limit: 1000 }),
      ]);
      if (cancelled) return;
      if (gameResult.status === "fulfilled") {
        const gamePayload = gameResult.value;
        setGames(gamePayload.games);
        setSelectedGameId((current) => {
          if (current && gamePayload.games.some((game) => game.game_id === current)) return current;
          return gamePayload.games[0]?.game_id ?? null;
        });
      } else {
        setGames([]);
      }
      if (profileResult.status === "fulfilled") {
        setProfilesPayload(profileResult.value);
      } else {
        setProfilesPayload(null);
      }
      if (auditResult.status === "fulfilled") {
        setAuditSummary(auditResult.value);
      } else {
        setAuditSummary(null);
      }
    }
    void loadClubContext();
    return () => {
      cancelled = true;
    };
  }, [selectedTeam.abbr, season]);

  useEffect(() => {
    if (!selectedGameId) {
      setReplay(null);
      setRecap(null);
      return;
    }
    let cancelled = false;
    async function loadGameContext() {
      try {
        const [replayPayload, recapPayload] = await Promise.all([
          fetchPitchingReplay(selectedGameId, "mlb"),
          fetchPitchingRecap(selectedGameId, "mlb"),
        ]);
        if (cancelled) return;
        setReplay(replayPayload);
        setRecap(recapPayload);
      } catch {
        if (!cancelled) {
          setReplay(null);
          setRecap(null);
        }
      }
    }
    void loadGameContext();
    return () => {
      cancelled = true;
    };
  }, [selectedGameId]);

  const profiles = profilesPayload?.profiles ?? [];
  const bullpenOptions = payload?.bullpenOptions ?? [];
  const tripleA = tripleAPayload?.tripleAConversionCandidates ?? payload?.tripleAConversionCandidates ?? [];

  function refreshAll() {
    void reload();
    void reloadTripleA();
    void reloadDashboardPreventableRuns();
    void reloadAuditPreventableRuns();
    void loadRecapSettings();
  }

  return (
    <main className="app-shell">
      <TopNav
        team={selectedTeam}
        workflow={workflow}
        loadState={loadState}
        onRefresh={refreshAll}
        onTeamChange={(team) => {
          setSelectedTeamAbbr(team.abbr);
        }}
        onWorkflowChange={setWorkflow}
      />

      <div className="app-main">
        {loadState === "loading" && <EmptyState title="Loading club intelligence" detail={`Retrieving ${selectedTeam.club} pitching evidence from ${apiBase}.`} />}
        {loadState === "missing-config" && <EmptyState title="API source not configured" detail="Set VITE_BASEBALL_BRAIN_API_BASE in the frontend environment." />}
        {loadState === "error" && <EmptyState title="API source unavailable" detail={error ?? "The Baseball brAIn API did not respond."} />}

        {loadState === "ready" && workflow === "audit" && (
          <GameAudit
            team={selectedTeam}
            games={games}
            selectedGameId={selectedGameId}
            onGameChange={setSelectedGameId}
            replay={replay}
            recap={recap}
            preventableRows={auditPreventableRuns?.rows ?? []}
            season={season}
            onSeasonChange={setSeason}
          />
        )}

        {loadState === "ready" && workflow === "briefings" && (
          <BriefingSettings
            team={selectedTeam}
            settings={recapSettings}
            status={recapSettingsStatus}
            onSave={handleSaveRecapSettings}
          />
        )}

      <footer className="app-footer">
        <span>Source: {apiBase || UNAVAILABLE}</span>
        <span>Generated: {payload?.summary.generatedAt ?? LOADING_VALUE}</span>
        <span>Confidential · Baseball brAIn, Inc.</span>
      </footer>
      </div>
    </main>
  );
}
