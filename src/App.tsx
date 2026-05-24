import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
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

type LoadState = "loading" | "ready" | "error" | "missing-config";
type Workflow = "command" | "audit" | "allocation" | "roster" | "briefings";
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

const WORKFLOWS: Array<{ id: Workflow; label: string; question: string }> = [
  { id: "command", label: "Command Center", question: "Where did we have opportunities to prevent runs?" },
  { id: "audit", label: "Game Audit", question: "What happened pitch by pitch?" },
  { id: "allocation", label: "Pitcher Allocation", question: "How should we deploy the staff?" },
  { id: "roster", label: "Roster Construction", question: "What staff gaps should we solve?" },
  { id: "briefings", label: "Briefings", question: "Who receives postgame intelligence?" },
];

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
    title: "Current pitch window",
    detail: `${selected.snapshot.pitcher_name} at pitch ${pitchCount(selected)} in the ${halfInningLabel(selected.snapshot.half, selected.snapshot.inning)}.`,
    tone: "neutral",
  };
}

function matrixCellForWindow(window: PitchingAuditWindow): MatrixCell {
  const starter = record(window.starter);
  const candidate = record(window.top_candidate);
  const starterAbove = (num(starter.degradation_score) ?? 2) < 1.15;
  const penAbove = Math.max(num(candidate.net_option_score) ?? 0, num(candidate.direct_matchup_fit) ?? 0) >= 0.45;
  if (starterAbove && penAbove) return "standard";
  if (!starterAbove && penAbove) return "tandem";
  if (starterAbove && !penAbove) return "push";
  return "workload";
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

function GaugeMetric({
  label,
  value,
  detail,
  percent,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail?: string;
  percent?: number;
  tone?: "neutral" | "good" | "warn" | "bad" | "gold";
}) {
  const width = percent == null ? 0 : Math.round(clamp(percent) * 100);
  return (
    <div className={`evidence-gauge evidence-gauge--${tone}`}>
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

function BasesAndOuts({ baseState, outs }: { baseState: string | null | undefined; outs: number | null | undefined }) {
  const bases = baseStateFlags(baseState);
  return (
    <div className="bases-outs">
      <div className="outs">
        {[0, 1, 2].map((index) => (
          <span key={index} className={(outs ?? 0) > index ? "filled" : ""} />
        ))}
      </div>
      <div className="bases">
        <i className={bases.second ? "filled second" : "second"} />
        <i className={bases.third ? "filled third" : "third"} />
        <i className={bases.first ? "filled first" : "first"} />
      </div>
    </div>
  );
}

function PitchPlot({ entries, selectedIndex }: { entries: PitchingReplayEntry[]; selectedIndex: number }) {
  const plotted = entries.slice(0, selectedIndex + 1).slice(-80);
  return (
    <div className="strike-zone-card">
      <div className="plate-zone">
        <div className="zone-box" />
        {plotted.map((entry, index) => {
          const px = typeof entry.snapshot.px === "number" ? entry.snapshot.px : 0;
          const pz = typeof entry.snapshot.pz === "number" ? entry.snapshot.pz : 2.5;
          const left = Math.max(7, Math.min(93, 50 + px * 18));
          const top = Math.max(7, Math.min(93, 84 - pz * 19));
          const selected = index === plotted.length - 1;
          return (
            <span
              key={`${entry.snapshot.pitch_id}-${index}`}
              className={selected ? "pitch-dot selected" : "pitch-dot"}
              style={{ left: `${left}%`, top: `${top}%` }}
            >
              {selected ? pitchCount(entry) : ""}
            </span>
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

function Header({
  team,
  workflow,
  loadState,
  onRefresh,
  onTeamChange,
  onWorkflowChange,
}: {
  team: Team;
  workflow: Workflow;
  loadState: LoadState;
  onRefresh: () => void;
  onTeamChange: (team: Team) => void;
  onWorkflowChange: (workflow: Workflow) => void;
}) {
  return (
    <header className="app-header">
      <div className="brand-panel">
        <p className="eyebrow">Baseball brAIn · Professional Operational Intelligence</p>
        <h1>Baseball brAIn</h1>
        <p>Pitcher Intelligence — every pitch, every pitcher, every situation.</p>
      </div>
      <div className="controls-panel">
        <div className="status-pill">
          <i className={loadState === "ready" ? "ready" : "pending"} />
          {loadState === "ready" ? "Data ready" : loadState === "loading" ? "Loading" : "Needs attention"}
        </div>
        <label>
          MLB club
          <select
            value={team.abbr}
            onChange={(event) => {
              const next = MLB_TEAMS.find((item) => item.abbr === event.target.value);
              if (next) onTeamChange(next);
            }}
          >
            {MLB_TEAMS.map((item) => (
              <option key={item.abbr} value={item.abbr}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      <nav className="workflow-nav" aria-label="Primary workflows">
        {WORKFLOWS.map((item) => (
          <button key={item.id} type="button" className={workflow === item.id ? "active" : ""} onClick={() => onWorkflowChange(item.id)}>
            <strong>{item.label}</strong>
            <span>{item.question}</span>
          </button>
        ))}
      </nav>
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

function usePreventableRunsOpportunities({ season, team, gameId, limit }: { season: string; team: string; gameId?: string | null; limit: number }) {
  const [payload, setPayload] = useState<PreventableRunsOpportunitiesPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPreventableRunsOpportunities({ season, team, gameId, limit });
      setPayload(data);
    } catch (caught) {
      setPayload(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [season, team, gameId, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  return { payload, error, loading, reload: load };
}

type CalibratedGameOpportunity = {
  row: PreventableRunsOpportunityRow;
  windowCount: number;
  pitcherCount: number;
  cell: MatrixCell;
};

type SeasonAuditGameOpportunity = {
  row: PitchingAuditWindow;
  windowCount: number;
  pitcherCount: number;
  cell: MatrixCell;
};

function reviewPointLabel(row: PreventableRunsOpportunityRow): string {
  const details = [halfInningLabel(row.half, row.inning), outsLabel(row.outs), baseStateLabel(row.baseState)];
  if (row.pitchCount != null) details.push(`pitch ${row.pitchCount}`);
  return details.join(" · ");
}

function reviewReasonLabels(row: PreventableRunsOpportunityRow): string[] {
  const reasons: string[] = [];
  const baseFlags = baseStateFlags(row.baseState);
  const runners = Number(baseFlags.first) + Number(baseFlags.second) + Number(baseFlags.third);
  if (runners >= 2) reasons.push("Runners in scoring position");
  else if (runners === 1) reasons.push("Traffic on base");
  if ((row.leverageIndex ?? 0) >= 1.5) reasons.push("Important game state");
  if ((row.degradationScore ?? row.productionDegradation ?? row.normalizedDegradation ?? 0) >= 1) reasons.push("Starter was slipping");
  if ((row.decayVelocity ?? 0) > 0 || (row.decayAcceleration ?? 0) > 0) reasons.push("Stuff trending down");
  for (const feature of row.topFeatures ?? []) {
    const label = categoryContributorLabel(feature.feature);
    if (reasons.length >= 3) break;
    if (!reasons.includes(label)) reasons.push(label);
  }
  return reasons.slice(0, 3);
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

function allocationCellForOpportunity(row: PreventableRunsOpportunityRow): MatrixCell {
  const degradation = row.degradationScore ?? row.productionDegradation ?? row.normalizedDegradation ?? 0;
  const scoringRisk = row.projectedDamageProbability ?? row.calibratedPreventableSignal ?? 0;
  const statusPressure = statusRank(row.status) >= statusRank("PULL NOW");
  const starterFading = statusPressure || degradation >= 1.15 || scoringRisk >= 0.3;
  const runEdge = row.projectedPreventableRuns ?? row.decisionDelta ?? 0;
  const reliefEvidence =
    runEdge > 0.05 ||
    (row.topFeatures ?? []).some((feature) => featureCategory(feature.feature) === "Relief Alternative");

  if (starterFading && reliefEvidence) return "tandem";
  if (starterFading && !reliefEvidence) return "workload";
  if (!starterFading && reliefEvidence) return "standard";
  return "push";
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
  const bucketCopy = matrixBucketCopy(opportunity.cell);
  const preventableText =
    row.projectedPreventableRuns != null
      ? `${fmtRuns(row.projectedPreventableRuns)} run exposure`
      : row.decisionDelta != null
        ? `${fmtRuns(row.decisionDelta)} decision edge`
        : "Run impact still calibrating";

  return (
    <button type="button" className="calibrated-row" onClick={() => row.gameId && onOpenGameAudit(row.gameId)}>
      <div>
        <strong>{row.team || "Team"} vs {row.opponent || "Opponent"}</strong>
        <span>{formatDateText(row.gameDate)} · {windowCount} flagged situation{windowCount === 1 ? "" : "s"} · {pitcherCount} pitcher{pitcherCount === 1 ? "" : "s"}</span>
      </div>
      <div>
        <strong>{row.pitcherName}</strong>
        <span>Review point: {reviewPointLabel(row)}</span>
      </div>
      <div>
        <strong>{reviewLevel}</strong>
        <span>{bucketCopy.title} · {fmtPct(row.projectedDamageProbability)} chance of scoring damage</span>
      </div>
      <div>
        <strong>{preventableText}</strong>
        <span>Priority {priority}/100 from comparable MLB situations</span>
      </div>
      <div className="driver-list">
        {reviewReasons.length === 0 ? (
          <span className="driver-chip">Open pitch audit</span>
        ) : (
          reviewReasons.map((reason) => (
            <span key={reason} className="driver-chip">{reason}</span>
          ))
        )}
      </div>
    </button>
  );
}

function calibratedGameKey(row: PreventableRunsOpportunityRow): string {
  return row.gameId || [row.gameDate ?? "date", row.team ?? "team", row.opponent ?? "opponent"].join("|");
}

function calibratedPriorityValue(row: PreventableRunsOpportunityRow): number {
  return row.calibratedPreventableSignal ?? row.projectedDamageProbability ?? row.projectedPreventableRuns ?? 0;
}

function groupCalibratedOpportunitiesByGame(rows: PreventableRunsOpportunityRow[]): CalibratedGameOpportunity[] {
  const grouped = new Map<string, { best: PreventableRunsOpportunityRow; windows: PreventableRunsOpportunityRow[] }>();
  for (const row of rows) {
    const key = calibratedGameKey(row);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, { best: row, windows: [row] });
      continue;
    }
    existing.windows.push(row);
    if (calibratedPriorityValue(row) > calibratedPriorityValue(existing.best)) {
      existing.best = row;
    }
  }
  return Array.from(grouped.values())
    .map((group) => ({
      row: group.best,
      windowCount: group.windows.length,
      pitcherCount: new Set(group.windows.map((row) => row.pitcherId || row.pitcherName).filter(Boolean)).size,
      cell: allocationCellForOpportunity(group.best),
    }))
    .sort((a, b) => calibratedPriorityValue(b.row) - calibratedPriorityValue(a.row));
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
      cell: matrixCellForWindow(group.best),
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
  const grouped = new Map<MatrixCell, Set<string>>([
    ["standard", new Set<string>()],
    ["tandem", new Set<string>()],
    ["push", new Set<string>()],
    ["workload", new Set<string>()],
  ]);
  for (const window of uniqueAuditWindows(windows)) {
    grouped.get(matrixCellForWindow(window))?.add(auditGameKey(window));
  }
  return {
    standard: grouped.get("standard")?.size ?? 0,
    tandem: grouped.get("tandem")?.size ?? 0,
    push: grouped.get("push")?.size ?? 0,
    workload: grouped.get("workload")?.size ?? 0,
  };
}

function SeasonAuditOpportunityRow({
  opportunity,
  onOpenGameAudit,
}: {
  opportunity: SeasonAuditGameOpportunity;
  onOpenGameAudit: (gameId: string) => void;
}) {
  const { row, windowCount, pitcherCount } = opportunity;
  const teams = auditTeams(row);
  const reasons = auditWindowReasonLabels(row);
  const priority = Math.min(100, Math.round(auditPriorityValue(row)));
  const bucketCopy = matrixBucketCopy(opportunity.cell);
  const reviewLevel = priority >= 90 ? "Immediate staff review" : priority >= 70 ? "High-priority review" : "Staff review";
  const gameId = String(row.game_id ?? row.game_pk ?? "");

  return (
    <button type="button" className="calibrated-row" onClick={() => gameId && onOpenGameAudit(gameId)}>
      <div>
        <strong>{teams.matchup}</strong>
        <span>{formatDateText(auditGameDate(row))} · {windowCount} flagged situation{windowCount === 1 ? "" : "s"} · {pitcherCount} pitcher{pitcherCount === 1 ? "" : "s"}</span>
      </div>
      <div>
        <strong>{auditPitcherName(row)}</strong>
        <span>Review point: {auditReviewPointLabel(row)}</span>
      </div>
      <div>
        <strong>{reviewLevel}</strong>
        <span>{bucketCopy.title} · {auditStatus(row)}</span>
      </div>
      <div>
        <strong>{auditRunExposureLabel(row)}</strong>
        <span>Priority {priority}/100 from the season audit inventory</span>
      </div>
      <div className="driver-list">
        {reasons.length === 0 ? (
          <span className="driver-chip">Open pitch audit</span>
        ) : (
          reasons.map((reason) => (
            <span key={reason} className="driver-chip">{reason}</span>
          ))
        )}
      </div>
    </button>
  );
}

function CommandCenter({
  team,
  payload,
  preventableRuns,
  preventableRunsError,
  preventableRunsLoading,
  profiles,
  auditSummary,
  onOpenAudit,
  onOpenGameAudit,
}: {
  team: Team;
  payload: RunSavingBoardPayload;
  preventableRuns: PreventableRunsOpportunitiesPayload | null;
  preventableRunsError: string | null;
  preventableRunsLoading: boolean;
  profiles: PitcherProfile[];
  auditSummary: PitchingAuditSummaryPayload | null;
  onOpenAudit: () => void;
  onOpenGameAudit: (gameId: string) => void;
}) {
  const seasonRuns = sum(profiles.map((profile) => profile.projectedRunsSaved));
  const boardRuns = sum(payload.decisions.map((decision) => decision.projectedRunsSaved));
  const calibratedSummary = preventableRuns?.summary ?? null;
  const calibratedRows = preventableRuns?.rows ?? [];
  const calibratedRuns =
    calibratedSummary?.totalProjectedPreventableRuns ?? sum(calibratedRows.map((row) => row.projectedPreventableRuns));
  const displayedRuns = calibratedSummary || calibratedRows.length > 0 ? calibratedRuns : seasonRuns || boardRuns;
  const windows = auditWindows(auditSummary);
  const deploymentBuckets: MatrixCell[] = ["tandem", "push", "workload", "standard"];
  const [allocationFilter, setAllocationFilter] = useState<MatrixCell | "all">("all");
  const allCalibratedGames = groupCalibratedOpportunitiesByGame(calibratedRows);
  const allSeasonAuditGames = groupSeasonAuditWindowsByBucketGame(windows);
  const bucketSourceGames = allSeasonAuditGames.length > 0 ? allSeasonAuditGames : allCalibratedGames;
  const auditMatrix =
    allSeasonAuditGames.length > 0
      ? auditBucketGameCounts(windows)
      : bucketSourceGames.reduce(
          (counts, opportunity) => {
            counts[opportunity.cell] += 1;
            return counts;
          },
          { standard: 0, tandem: 0, push: 0, workload: 0 },
        );
  const filteredSeasonAuditGames =
    allocationFilter === "all" ? allSeasonAuditGames : groupSeasonAuditWindowsByBucketGame(windows, allocationFilter);
  const filteredCalibratedGames =
    allocationFilter === "all" ? allCalibratedGames : allCalibratedGames.filter((opportunity) => opportunity.cell === allocationFilter);
  const selectedBucketCopy = allocationFilter === "all" ? null : matrixBucketCopy(allocationFilter);
  const visibleSeasonAuditGames = filteredSeasonAuditGames.length > 0 || allSeasonAuditGames.length > 0 ? filteredSeasonAuditGames : [];
  const visibleCalibratedGames = visibleSeasonAuditGames.length > 0 ? [] : filteredCalibratedGames;
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
      ? "These counts are from the season audit inventory. If one bucket dominates, it means the current model is classifying this club's reviewed cases into one primary staff-allocation question."
      : "These counts are calculated from the season audit inventory. Buckets are overlapping: one game can contain windows in more than one staff-allocation bucket.";
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

  return (
    <section className="workflow">
      <div className="page-lead">
        <div>
          <p className="eyebrow">{team.name}</p>
          <h2>Run prevention opportunity, distilled.</h2>
          <p>
            Start here. This page summarizes where the model found defensible chances to reduce runs, then routes each case into a game audit or allocation review.
          </p>
        </div>
        <TeamLogo abbr={team.abbr} />
      </div>

      <div className="kpi-row">
        <KPI label="Preventable Run Exposure" value={fmtRuns(displayedRuns)} detail="Season-to-date estimate of where better staff deployment may have reduced scoring." tone="gold" />
        <KPI label="Games to Review" value={String(bucketSourceGames.length || windows.length)} detail="Unique games with at least one staff-allocation review window." tone="bad" />
        <KPI label="Tandem Opportunities" value={String(auditMatrix.tandem)} detail="Unique games with at least one tandem review window; buckets can overlap." tone="bad" />
        <KPI label="Pitchers in Review" value={String(coveredPitcherCount)} detail={coveredPitcherDetail} />
      </div>

      <article className="panel calibrated-panel">
        <div className="panel-title horizontal">
          <div>
            <p className="eyebrow">Run Prevention Review Queue</p>
            <h3>{selectedBucketCopy ? selectedBucketCopy.title : "Start with these games."}</h3>
            <p>
              {selectedBucketCopy
                ? `${selectedBucketCopy.detail} The rows below are filtered to this allocation bucket.`
                : "One row per game. Each row identifies the point where the club had the clearest opportunity to reconsider pitcher usage, then opens the pitch-level audit."}
            </p>
          </div>
          <SourceTag
            label={bucketSourceGames.length > 0 ? "Evidence ready" : preventableRunsLoading ? "Loading evidence" : "Evidence unavailable"}
            source={bucketSourceGames.length > 0 ? "model" : "unavailable"}
          />
        </div>
        {bucketSourceGames.length === 0 && preventableRunsLoading ? (
          <EmptyState title="Loading review queue" detail="Retrieving the current staff-deployment opportunity set." />
        ) : bucketSourceGames.length === 0 && preventableRunsError ? (
          <EmptyState title="Review queue unavailable" detail={preventableRunsError} />
        ) : visibleGameCount === 0 ? (
          <EmptyState title="No games returned" detail="The evidence source is reachable, but no game-level review rows matched this club and season." />
        ) : (
          <>
            <div className="deployment-summary decision-filter-summary">
              <div>
                <p className="eyebrow">Decision Type</p>
                <h4>Choose the staff-allocation question to review.</h4>
                <p>{allocationMapDetail}</p>
              </div>
              <div className="deployment-bucket-grid">
                <button
                  type="button"
                  className={allocationFilter === "all" ? "deployment-bucket active" : "deployment-bucket"}
                  onClick={() => setAllocationFilter("all")}
                >
                  <strong>{bucketSourceGames.length}</strong>
                  <span>All review games</span>
                  <p>Unique games currently surfaced in the season staff-allocation audit.</p>
                </button>
                {deploymentBuckets.map((bucket) => {
                  const copy = matrixBucketCopy(bucket);
                  return (
                    <button
                      key={bucket}
                      type="button"
                      className={[
                        "deployment-bucket",
                        bucket === "tandem" ? "target" : "",
                        allocationFilter === bucket ? "active" : "",
                      ].filter(Boolean).join(" ")}
                      onClick={() => setAllocationFilter(bucket)}
                    >
                      <strong>{auditMatrix[bucket]}</strong>
                      <span>{copy.title}</span>
                      <p>{copy.detail} A game may also appear in another bucket.</p>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="calibrated-metrics">
              <KPI
                label={selectedBucketCopy ? "Games in This Bucket" : "Reviewed Situations"}
                value={String(selectedBucketCopy ? visibleGameCount : visibleWindowCount)}
                detail={selectedBucketCopy ? "Visible game rows after applying the decision-type filter." : "Pitch-level situations screened for staff-deployment opportunity."}
              />
              <KPI
                label={visibleAvgLeverage == null ? "Avg Scoring Risk" : "Avg Leverage in View"}
                value={visibleAvgLeverage == null ? fmtPct(calibratedSummary?.avgProjectedDamageProbability) : visibleAvgLeverage.toFixed(2)}
                detail={visibleAvgLeverage == null ? "Average risk that a flagged situation led to additional scoring." : "Average leverage index across the visible game-review rows."}
                tone="bad"
              />
              <KPI
                label="Actual Damage Rate"
                value={fmtPct(calibratedSummary?.damageRate)}
                detail={`${calibratedSummary?.missedHookDamageCount ?? 0} flagged situations were followed by scoring damage.`}
              />
            </div>
            <div className="calibrated-list">
              {visibleSeasonAuditGames.length > 0
                ? visibleSeasonAuditGames.map((opportunity) => (
                    <SeasonAuditOpportunityRow
                      key={auditGameKey(opportunity.row)}
                      opportunity={opportunity}
                      onOpenGameAudit={onOpenGameAudit}
                    />
                  ))
                : visibleCalibratedGames.map((opportunity) => (
                    <CalibratedOpportunityRow
                      key={calibratedGameKey(opportunity.row)}
                      opportunity={opportunity}
                      onOpenGameAudit={onOpenGameAudit}
                    />
                  ))}
            </div>
          </>
        )}
      </article>
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
}: {
  team: Team;
  games: EnterpriseGameSummary[];
  selectedGameId: string | null;
  onGameChange: (id: string) => void;
  replay: PitchingReplayResponse | null;
  recap: PitchingGameRecap | null;
  preventableRows: PreventableRunsOpportunityRow[];
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
  const pullBestCandidate = pullEntry?.top_candidates?.find((candidate) => candidate.available) ?? pullEntry?.top_candidates?.[0] ?? null;
  const pullDecisionDelta = pullEntry?.recommendation.decision_delta ?? selected?.recommendation.decision_delta ?? null;
  const hasWatchSignal = statusRank(displayStatus) >= statusRank("WATCH");
  const bestCandidate = selected?.top_candidates?.find((candidate) => candidate.available) ?? selected?.top_candidates?.[0] ?? null;
  const selectedState = selected ? replayState(selected) : null;
  const selectedIsReliever = isRelieverReplayEntry(selected);
  const selectedOpportunity = opportunityForPitch(selected, preventableRows, selectedGameId);
  const selectedPreventableRuns = preventableRunsForPitch(selected, selectedOpportunity);
  const eventLabel = selected && replay ? entryEventLabel(selected, previous, displayStatus, previousStatus, replay) : null;
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

  return (
    <section className="workflow">
      <div className="page-lead compact">
        <div>
          <p className="eyebrow">Game Audit</p>
          <h2>Observed decision, model window, and pitch-level evidence.</h2>
          <p>Use this page when a club asks, “Show me exactly where we should have acted and what happened after.”</p>
        </div>
        <label className="game-select">
          Game
          <select value={selectedGameId ?? ""} onChange={(event) => onGameChange(event.target.value)}>
            {games.map((game) => (
              <option key={game.game_id} value={game.game_id}>
                {gameLabel(game)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!selectedGameId || !replay || !selected ? (
        <EmptyState title="No replay loaded" detail="Select a completed game with finalized pitch-level replay detail." />
      ) : (
        <>
          <article className="panel replay-panel">
            <div className={`signal-banner signal-${signalClass(displayStatus)}`}>
              <strong>{selectedIsReliever ? `RSS ${displayStatus}` : displayStatus}</strong>
            </div>
            {eventLabel ? (
              <div className={`event-callout event-callout--${eventLabel.tone}`}>
                <strong>{eventLabel.title}</strong>
                <span>{eventLabel.detail}</span>
              </div>
            ) : null}

            <div className="replay-layout">
              <aside className="situation-card">
                <TeamLogo abbr={team.abbr} />
                <h3>{selected.snapshot.pitcher_name}</h3>
                <BasesAndOuts baseState={selected.snapshot.base_state} outs={selected.snapshot.outs} />
                <div className="situation-list">
                  <span>Situation <strong>{halfInningLabel(selected.snapshot.half, selected.snapshot.inning)}</strong></span>
                  <span>Bases <strong>{baseStateLabel(selected.snapshot.base_state)}</strong></span>
                  <span>Outs <strong>{outsLabel(selected.snapshot.outs)}</strong></span>
                  <span>Pitch count <strong>{pitchCount(selected)}</strong></span>
                  <span>{selectedIsReliever ? "Batters faced" : "Times through order"} <strong>{selectedIsReliever ? selectedState?.batters_faced_in_game ?? "—" : selectedState?.times_through_order}</strong></span>
                  <span>Score <strong>{scoreForEntry(selected, replay)}</strong></span>
                </div>
              </aside>

              <PitchPlot entries={entries} selectedIndex={selectedIndex} />

              <aside className="model-synthesis-card">
                <p className="eyebrow">Decision Read</p>
                <div className="decision-score-row">
                  <div className="degradation-ring" style={{ "--ring": `${Math.round(clamp(degradationPressure) * 100)}%` } as CSSProperties}>
                    <strong>{fmtNumber(selectedState?.enhanced_degradation_score ?? selectedState?.degradation_score, 2)}</strong>
                    <span>degradation</span>
                  </div>
                  <div>
                    <span>Preventable Runs</span>
                    <strong>{selectedIsReliever ? "Reliever RSS" : fmtRuns(selectedPreventableRuns)}</strong>
                    <em>{selectedIsReliever ? `RSS ${fmtNumber(selectedState?.rss_score, 2)}` : selectedOpportunity ? "Calibrated opportunity model" : "Not attached to this pitch window"}</em>
                  </div>
                </div>
                <div className="decision-gauge-grid">
                  <GaugeMetric label="Stuff pressure" value={fmtPct(stuffPressure)} percent={stuffPressure} tone="bad" />
                  <GaugeMetric label="Command pressure" value={fmtPct(commandPressure)} percent={commandPressure} tone="warn" />
                  <GaugeMetric label="Decay pressure" value={fmtPct(decayPressure)} percent={decayPressure} tone="gold" />
                  <GaugeMetric label="Leverage" value={fmtNumber(selected.snapshot.leverage_index, 2)} percent={scaledPercent(selected.snapshot.leverage_index, 3)} tone="gold" />
                </div>
                <div className="decision-delta">
                  <strong>{hasWatchSignal ? "Relief decision delta" : "Relief context unlocks at WATCH"}</strong>
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
                <div className="source-row">
                  <SourceTag label="Official pitch facts" source="official" />
                  <SourceTag label="Model degradation" source="model" />
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
              <p className="eyebrow">Supporting Model Detail</p>
              <h3>Why the signal moved.</h3>
              <p>The headline read above is built from these tracked inputs. Missing values are shown as unavailable rather than estimated.</p>
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
                <GaugeMetric label="Swinging-strike rate" value={fmtRate(selectedState?.whiff_rate_15)} detail={`Opponent-adjusted change ${fmtSigned(selectedState?.opponent_adjusted_whiff_drop, 2)}`} percent={selectedState?.whiff_rate_15 ?? undefined} tone="gold" />
                <GaugeMetric label="Pitch mix drift" value={fmtNumber(selectedState?.pitch_mix_drift_10, 2)} detail="How far recent pitch selection has moved from expected mix." percent={scaledPercent(selectedState?.pitch_mix_drift_10, 1)} tone="warn" />
              </section>
              <section>
                <h4>Command and Contact</h4>
                <GaugeMetric label="Strike rate" value={fmtRate(selectedState?.strike_rate_10)} detail="Last 10 pitches." percent={selectedState?.strike_rate_10 ?? undefined} tone="good" />
                <GaugeMetric label="Called-strike rate" value={fmtRate(selectedState?.called_strike_rate_15)} detail="Called strikes over the recent command window." percent={selectedState?.called_strike_rate_15 ?? undefined} tone="good" />
                <GaugeMetric label="Chase rate proxy" value={fmtRate(selectedState?.chase_proxy_rate_15)} detail="Hitters expanding against him." percent={selectedState?.chase_proxy_rate_15 ?? undefined} tone="good" />
                <GaugeMetric label="Hard contact" value={fmtRate(selectedState?.hard_contact_rate_15)} detail="Recent contact-quality pressure." percent={selectedState?.hard_contact_rate_15 ?? undefined} tone="bad" />
                <GaugeMetric label="Zone miss" value={`${fmtNumber(selectedState?.zone_miss_distance_10, 2)} ft`} detail={`5-pitch window ${fmtNumber(selectedState?.zone_miss_distance_5, 2)} ft.`} percent={scaledPercent(selectedState?.zone_miss_distance_10, 0.8)} tone="warn" />
                <GaugeMetric label="Command spread" value={fmtNumber(selectedState?.location_dispersion_10, 2)} detail={`5-pitch spread ${fmtNumber(selectedState?.location_dispersion_5, 2)}.`} percent={scaledPercent(selectedState?.location_dispersion_10, 1.4)} tone="warn" />
              </section>
              <section>
                <h4>Decision Context</h4>
                <GaugeMetric label="Game leverage" value={fmtNumber(selected.snapshot.leverage_index, 2)} detail={selected.snapshot.leverage_index >= 1.5 ? "High-value game state." : "Lower leverage window."} percent={scaledPercent(selected.snapshot.leverage_index, 3)} tone="gold" />
                <GaugeMetric label="Normalized degradation" value={fmtRate(selectedState?.normalized_degradation_score)} detail="Normalized against comparable MLB windows." percent={selectedState?.normalized_degradation_score ?? undefined} tone="bad" />
                <GaugeMetric label="Enhanced degradation" value={fmtNumber(selectedState?.enhanced_degradation_score, 2)} detail="Weighted model read after feature normalization." percent={scaledPercent(selectedState?.enhanced_degradation_score, 3)} tone="bad" />
                <GaugeMetric label="League percentile" value={fmtRate(selectedState?.empirical_degradation_percentile)} detail={`${selectedState?.empirical_degradation_sample_count ?? "—"} comparable windows.`} percent={selectedState?.empirical_degradation_percentile ?? undefined} tone="gold" />
                <GaugeMetric label="Pitcher history percentile" value={fmtRate(selectedState?.pitcher_empirical_degradation_percentile)} detail={`${selectedState?.pitcher_empirical_degradation_sample_count ?? "—"} pitcher windows.`} percent={selectedState?.pitcher_empirical_degradation_percentile ?? undefined} tone="gold" />
                <GaugeMetric label="Decay pressure" value={`${fmtNumber(selectedState?.inning_decay_factor, 2)} inning · ${fmtNumber(selectedState?.tto_decay_factor, 2)} TTO`} detail={`${selectedState?.official_batters_faced_in_game ?? selectedState?.batters_faced_in_game ?? "—"} batters faced.`} percent={scaledPercent((selectedState?.inning_decay_factor ?? 0) + (selectedState?.tto_decay_factor ?? 0), 3)} tone="warn" />
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
            {topComponents.length > 0 ? (
              <div className="component-strip">
                <span>Top model contributors</span>
                {topComponents.map(([key, value]) => (
                  <em key={key}>{categoryContributorLabel(key)} {fmtSigned(value, 2)}</em>
                ))}
              </div>
            ) : null}
          </article>

          {teamRelievers.length > 0 ? (
            <article className="panel rss-panel">
              <div className="panel-title horizontal">
                <div>
                  <p className="eyebrow">Reliever Stress Signal</p>
                  <h3>Bullpen outcomes from the same game.</h3>
                  <p>Relievers are now available as their own pitch-by-pitch RSS replay stream when the finalized artifact includes bullpen entries.</p>
                </div>
                <SourceTag label="Finalized recap RSS" source="model" />
              </div>
              <div className="rss-table">
                {teamRelievers.map((pitcher) => (
                  <div key={pitcher.pitcher_id || pitcher.pitcher_name} className="rss-row">
                    <div>
                      <strong>{pitcher.pitcher_name}</strong>
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
            <p className="eyebrow">Decision Outcome</p>
            <h3>What happened after the model action point.</h3>
            <div className="counterfactual-grid">
              <div>
                <strong>Pull Now summary</strong>
                <p>{actionPointCopy(keyPitcher)}</p>
                <ul className="mini-metric-list">
                  <li>Stuff <b>{pullMetrics.stuff}</b></li>
                  <li>Decay <b>{pullMetrics.decay}</b></li>
                  <li>Degradation <b>{pullMetrics.degradation}</b></li>
                </ul>
              </div>
              <div>
                <strong>Decision delta</strong>
                <p>
                  {pullBestCandidate
                    ? `${pullBestCandidate.player_name} was the best recorded relief alternative at the model action point.${pullDecisionDelta == null ? "" : ` The model estimated a ${fmtSigned(pullDecisionDelta, 2)} run delta versus staying with the starter.`}`
                    : "No relief alternative was attached to the model action point, so the bullpen counterfactual is unavailable for this game."}
                </p>
              </div>
              <div>
                <strong>Actual result</strong>
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
  const [selectedTeamAbbr, setSelectedTeamAbbr] = useState("ATL");
  const [workflow, setWorkflow] = useState<Workflow>("command");
  const [season, setSeason] = useState("2026");
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);
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
    payload: preventableRuns,
    error: preventableRunsError,
    loading: preventableRunsLoading,
    reload: reloadPreventableRuns,
  } = usePreventableRunsOpportunities({ season, team: selectedTeam.abbr, gameId: selectedGameId, limit: 5000 });
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
      try {
        const [gamePayload, profilePayload, auditPayload] = await Promise.all([
          fetchEnterpriseGames({ league: "mlb", team: selectedTeam.abbr, limit: 300 }),
          fetchPitcherProfiles({ league: "mlb", team: selectedTeam.abbr, year: season, limit: 750 }),
          fetchPitchingAuditSummary({ league: "mlb", team: selectedTeam.abbr, year: season, limit: 1000 }),
        ]);
        if (cancelled) return;
        setGames(gamePayload.games);
        setProfilesPayload(profilePayload);
        setAuditSummary(auditPayload);
        setSelectedGameId((current) => {
          if (current && gamePayload.games.some((game) => game.game_id === current)) return current;
          return gamePayload.games[0]?.game_id ?? null;
        });
      } catch {
        if (!cancelled) {
          setGames([]);
          setProfilesPayload(null);
          setAuditSummary(null);
        }
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
    void reloadPreventableRuns();
    void loadRecapSettings();
  }

  return (
    <main className="app-shell">
      <Header
        team={selectedTeam}
        workflow={workflow}
        loadState={loadState}
        onRefresh={refreshAll}
        onTeamChange={(team) => {
          setSelectedTeamAbbr(team.abbr);
          setWorkflow("command");
        }}
        onWorkflowChange={setWorkflow}
      />

      <div className="season-row">
        <span>{selectedTeam.name}</span>
        <label>
          Season
          <select value={season} onChange={(event) => setSeason(event.target.value)}>
            <option value="2026">2026</option>
            <option value="2025">2025</option>
          </select>
        </label>
      </div>

      {loadState === "loading" && <EmptyState title="Loading club intelligence" detail={`Retrieving ${selectedTeam.club} pitching evidence from ${apiBase}.`} />}
      {loadState === "missing-config" && <EmptyState title="API source not configured" detail="Set VITE_BASEBALL_BRAIN_API_BASE in the frontend environment." />}
      {loadState === "error" && <EmptyState title="API source unavailable" detail={error ?? "The Baseball brAIn API did not respond."} />}

      {loadState === "ready" && payload && workflow === "command" && (
        <CommandCenter
          team={selectedTeam}
          payload={payload}
          preventableRuns={preventableRuns}
          preventableRunsError={preventableRunsError}
          preventableRunsLoading={preventableRunsLoading}
          profiles={profiles}
          auditSummary={auditSummary}
          onOpenAudit={() => setWorkflow("audit")}
          onOpenGameAudit={(gameId) => {
            setSelectedGameId(gameId);
            setWorkflow("audit");
          }}
        />
      )}

      {loadState === "ready" && workflow === "audit" && (
        <GameAudit
          team={selectedTeam}
          games={games}
          selectedGameId={selectedGameId}
          onGameChange={setSelectedGameId}
          replay={replay}
          recap={recap}
          preventableRows={preventableRuns?.rows ?? []}
        />
      )}

      {loadState === "ready" && workflow === "allocation" && (
        <PitcherAllocation profiles={profiles} bullpenOptions={bullpenOptions} />
      )}

      {loadState === "ready" && workflow === "roster" && (
        <RosterConstruction team={selectedTeam} profiles={profiles} auditSummary={auditSummary} candidates={tripleA} />
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
    </main>
  );
}
