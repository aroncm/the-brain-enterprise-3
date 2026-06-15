import type {
  EnterpriseGamesPayload,
  PitcherProfilesPayload,
  PitchingAuditSummaryPayload,
  PitchingGameRecap,
  PitchingRecapEmailResponse,
  PitchingRecapSettings,
  PitchingReplayResponse,
  PreventableRunsFeatureContribution,
  PreventableRunsOpportunitiesPayload,
  PreventableRunsOpportunityRow,
  PreventableRunsPitcherSummary,
  PreventableRunsTeamSummary,
  RunSavingBoardPayload,
} from "./types";

const DEFAULT_API_BASE = "https://aroncm--abs-challenge-api-tuned-fastapi-app-tuned.modal.run";
const viteEnv = import.meta.env ?? {};
const API_BASE = (viteEnv.VITE_BASEBALL_BRAIN_API_BASE ?? DEFAULT_API_BASE).replace(/\/+$/, "");

export function getConfiguredApiBase(): string {
  return API_BASE;
}

export class ApiConfigurationError extends Error {
  constructor() {
    super("Baseball brAIn API base is not configured.");
    this.name = "ApiConfigurationError";
  }
}

const TRANSIENT_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);
// Bounded, jittered retry. A brief slow spell — a cold or saturated Modal
// container warming up — is still ridden out, but capped at 3 attempts with
// randomized delays. The old config (6 retries, ~30s of fixed delays) meant a
// single slow spell let every open tab retry in lockstep up to 6×, piling load
// onto an already-struggling backend and turning a blip into an outage.
const RETRY_BASE_DELAYS_MS = [1000, 3000, 6000];
// Cap on honoring a server-sent Retry-After so a bad header can't stall the UI.
const MAX_RETRY_AFTER_MS = 15000;
// Abort a single stalled GET attempt (a connection held open by a cold start)
// so we retry instead of hanging. Not applied to writes (a recap-email send can
// legitimately run longer).
const ATTEMPT_TIMEOUT_MS = 20000;

// Shared circuit breaker: if GETs keep failing transiently with no success in
// between, stop *retrying* for a short cooldown so a slow spell can't snowball
// into a retry storm that keeps the backend saturated. Requests still go through
// (a single attempt) — only the amplifying retries are suppressed, and a single
// success immediately re-arms normal retrying.
const CIRCUIT_FAILURE_THRESHOLD = 8;
const CIRCUIT_COOLDOWN_MS = 5000;
let circuitFailureCount = 0;
let circuitOpenUntil = 0;

function circuitIsOpen(): boolean {
  return Date.now() < circuitOpenUntil;
}

function noteTransientFailure(): void {
  circuitFailureCount += 1;
  if (circuitFailureCount >= CIRCUIT_FAILURE_THRESHOLD) {
    circuitOpenUntil = Date.now() + CIRCUIT_COOLDOWN_MS;
    circuitFailureCount = 0;
  }
}

function noteSuccess(): void {
  circuitFailureCount = 0;
  circuitOpenUntil = 0;
}

// Randomized backoff at 50–100% of the base delay — spreading concurrent clients
// out of lockstep is the key anti-amplification lever (no thundering herd all
// re-hitting the backend on the same tick).
function backoffWithJitter(attempt: number): number {
  const base =
    RETRY_BASE_DELAYS_MS[attempt] ?? RETRY_BASE_DELAYS_MS[RETRY_BASE_DELAYS_MS.length - 1];
  return Math.round(base * (0.5 + Math.random() * 0.5));
}

// Honor a server's Retry-After (delta-seconds or HTTP-date) so the backend can
// control its own backpressure; otherwise fall back to jittered backoff.
function retryDelayMs(response: Response, attempt: number): number {
  const header = response.headers.get("Retry-After");
  if (header) {
    const seconds = Number(header);
    if (Number.isFinite(seconds)) {
      return Math.min(Math.max(seconds, 0) * 1000, MAX_RETRY_AFTER_MS);
    }
    const dateMs = Date.parse(header);
    if (Number.isFinite(dateMs)) {
      return Math.min(Math.max(dateMs - Date.now(), 0), MAX_RETRY_AFTER_MS);
    }
  }
  return backoffWithJitter(attempt);
}

async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!API_BASE) {
    throw new ApiConfigurationError();
  }

  const method = (init.method ?? "GET").toUpperCase();
  const isIdempotent = method === "GET" || method === "HEAD";
  let attempt = 0;
  let lastError: Error | null = null;

  while (true) {
    const controller = isIdempotent ? new AbortController() : null;
    const timeoutId = controller ? setTimeout(() => controller.abort(), ATTEMPT_TIMEOUT_MS) : null;
    let response: Response;
    try {
      response = await fetch(`${API_BASE}${path}`, {
        ...init,
        signal: init.signal ?? controller?.signal,
        headers: {
          Accept: "application/json",
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...(init.headers ?? {}),
        },
      });
    } catch (caught) {
      if (timeoutId) clearTimeout(timeoutId);
      lastError = caught instanceof Error ? caught : new Error(String(caught));
      if (isIdempotent) {
        noteTransientFailure();
        if (!circuitIsOpen() && attempt < RETRY_BASE_DELAYS_MS.length) {
          await new Promise((resolve) => setTimeout(resolve, backoffWithJitter(attempt)));
          attempt += 1;
          continue;
        }
      }
      throw lastError;
    }
    if (timeoutId) clearTimeout(timeoutId);

    if (!response.ok) {
      if (isIdempotent && TRANSIENT_STATUS_CODES.has(response.status)) {
        noteTransientFailure();
        if (!circuitIsOpen() && attempt < RETRY_BASE_DELAYS_MS.length) {
          await new Promise((resolve) => setTimeout(resolve, retryDelayMs(response, attempt)));
          attempt += 1;
          continue;
        }
      }
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (typeof payload?.detail === "string") {
          detail = payload.detail;
        }
      } catch {
        // Keep the HTTP status as the useful fallback.
      }
      throw new Error(detail);
    }

    if (isIdempotent) noteSuccess();
    return response.json() as Promise<T>;
  }
}

export type RunSavingBoardQuery = {
  league?: "mlb" | "triple_a";
  team?: string;
  date?: string;
  limit?: number;
};

export function fetchRunSavingBoard(query: RunSavingBoardQuery = {}): Promise<RunSavingBoardPayload> {
  const params = new URLSearchParams();
  params.set("league", query.league ?? "mlb");
  if (query.team) params.set("team", query.team);
  if (query.date) params.set("date", query.date);
  if (query.limit != null) params.set("limit", String(Math.min(query.limit, 50)));
  return fetchJson<RunSavingBoardPayload>(`/v1/enterprise/run-saving/board?${params.toString()}`);
}

type ApiRecord = Record<string, unknown>;

function asRecord(value: unknown): ApiRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as ApiRecord) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function pick(source: ApiRecord, ...keys: string[]): unknown {
  for (const key of keys) {
    if (source[key] !== undefined) return source[key];
  }
  return undefined;
}

function numberOrNull(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function stringOrNull(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function booleanOrNull(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value === 1 ? true : value === 0 ? false : null;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true" || normalized === "1") return true;
    if (normalized === "false" || normalized === "0") return false;
  }
  return null;
}

function mapFeatureContribution(value: unknown): PreventableRunsFeatureContribution {
  const item = asRecord(value);
  return {
    feature: stringOrNull(pick(item, "feature")) ?? "unknown",
    value: numberOrNull(pick(item, "value")),
    weight: numberOrNull(pick(item, "weight")),
    contribution: numberOrNull(pick(item, "contribution")),
  };
}

function mapTeamSummary(value: unknown): PreventableRunsTeamSummary {
  const item = asRecord(value);
  return {
    team: stringOrNull(pick(item, "team")) ?? "",
    windowCount: numberOrNull(pick(item, "windowCount", "window_count")) ?? 0,
    totalProjectedPreventableRuns: numberOrNull(pick(item, "totalProjectedPreventableRuns", "total_projected_preventable_runs")) ?? 0,
    avgProjectedPreventableRuns: numberOrNull(pick(item, "avgProjectedPreventableRuns", "avg_projected_preventable_runs")) ?? 0,
    avgProjectedDamageProbability: numberOrNull(pick(item, "avgProjectedDamageProbability", "avg_projected_damage_probability")) ?? 0,
    actualPreventableRunsProxy: numberOrNull(pick(item, "actualPreventableRunsProxy", "actual_preventable_runs_proxy")),
    damageRate: numberOrNull(pick(item, "damageRate", "damage_rate")),
    missedHookDamageCount: numberOrNull(pick(item, "missedHookDamageCount", "missed_hook_damage_count")) ?? 0,
  };
}

function mapPitcherSummary(value: unknown): PreventableRunsPitcherSummary {
  const item = asRecord(value);
  return {
    team: stringOrNull(pick(item, "team")) ?? "",
    pitcherId: stringOrNull(pick(item, "pitcherId", "pitcher_id")),
    pitcherName: stringOrNull(pick(item, "pitcherName", "pitcher_name")) ?? "Pitcher",
    windowCount: numberOrNull(pick(item, "windowCount", "window_count")) ?? 0,
    totalProjectedPreventableRuns: numberOrNull(pick(item, "totalProjectedPreventableRuns", "total_projected_preventable_runs")) ?? 0,
    avgProjectedPreventableRuns: numberOrNull(pick(item, "avgProjectedPreventableRuns", "avg_projected_preventable_runs")) ?? 0,
    avgProjectedDamageProbability: numberOrNull(pick(item, "avgProjectedDamageProbability", "avg_projected_damage_probability")) ?? 0,
    actualPreventableRunsProxy: numberOrNull(pick(item, "actualPreventableRunsProxy", "actual_preventable_runs_proxy")),
    damageRate: numberOrNull(pick(item, "damageRate", "damage_rate")),
  };
}

function mapOpportunityRow(value: unknown): PreventableRunsOpportunityRow {
  const item = asRecord(value);
  const productionDegradation = numberOrNull(pick(item, "productionDegradation", "production_degradation"));
  const normalizedDegradation = numberOrNull(pick(item, "normalizedDegradation", "normalized_degradation"));
  return {
    raw: item,
    gameId:
      stringOrNull(
        pick(item, "gameId", "game_id", "gamePk", "game_pk", "gamePK", "game_pk_id", "mlbGamePk", "mlb_game_pk"),
      ) ?? "",
    gameDate: stringOrNull(pick(item, "gameDate", "game_date", "gameDateEt", "game_date_et", "date")),
    team:
      stringOrNull(
        pick(item, "team", "fieldingTeam", "fielding_team", "decisionTeam", "decision_team", "club", "club_abbr"),
      ) ?? "",
    opponent:
      stringOrNull(pick(item, "opponent", "battingTeam", "batting_team", "opponentTeam", "opponent_team")) ?? "",
    pitcherId: stringOrNull(pick(item, "pitcherId", "pitcher_id", "pitcher", "mlbPitcherId", "mlb_pitcher_id")),
    pitcherName: stringOrNull(pick(item, "pitcherName", "pitcher_name")) ?? "Pitcher",
    pitchId: stringOrNull(pick(item, "pitchId", "pitch_id")),
    inning: numberOrNull(pick(item, "inning", "inning_number")),
    half: stringOrNull(pick(item, "half", "inningHalf", "inning_half", "topBottom", "top_bottom")),
    outs: numberOrNull(pick(item, "outs", "out_count", "outs_when_up")),
    baseState: stringOrNull(pick(item, "baseState", "base_state", "base_state_code", "bases")),
    pitchCount: numberOrNull(pick(item, "pitchCount", "pitch_count", "pitchNumber", "pitch_number", "pitch_count_in_game")),
    currentHomeScore: numberOrNull(pick(item, "currentHomeScore", "current_home_score")),
    currentAwayScore: numberOrNull(pick(item, "currentAwayScore", "current_away_score")),
    finalHomeScore: numberOrNull(pick(item, "finalHomeScore", "final_home_score")),
    finalAwayScore: numberOrNull(pick(item, "finalAwayScore", "final_away_score")),
    status: stringOrNull(pick(item, "status", "recommendationStatus", "recommendation_status", "signal", "modelStatus", "model_status")),
    damageRunsNext6Outs: numberOrNull(pick(item, "damageRunsNext6Outs", "damage_runs_next_6_outs")),
    projectedDamageProbability: numberOrNull(pick(item, "projectedDamageProbability", "projected_damage_probability")),
    projectedRunsThroughNextPocket: numberOrNull(pick(item, "projectedRunsThroughNextPocket", "projected_runs_through_next_pocket")),
    projectedPreventableRuns: numberOrNull(pick(item, "projectedPreventableRuns", "projected_preventable_runs")),
    actualRunsThroughNextPocket: numberOrNull(pick(item, "actualRunsThroughNextPocket", "actual_runs_through_next_pocket")),
    actualPreventableRunsProxy: numberOrNull(pick(item, "actualPreventableRunsProxy", "actual_preventable_runs_proxy")),
    actualChangeWithinNextPocket: booleanOrNull(pick(item, "actualChangeWithinNextPocket", "actual_change_within_next_pocket")),
    actualChangeInning: stringOrNull(pick(item, "actualChangeInning", "actual_change_inning")),
    actualChangePitchCount: numberOrNull(pick(item, "actualChangePitchCount", "actual_change_pitch_count")),
    actualReplacementPitcher: stringOrNull(pick(item, "actualReplacementPitcher", "actual_replacement_pitcher")),
    actualReplacementPitcherId: stringOrNull(pick(item, "actualReplacementPitcherId", "actual_replacement_pitcher_id")),
    actualReplacementFirstPitchCount: numberOrNull(pick(item, "actualReplacementFirstPitchCount", "actual_replacement_first_pitch_count")),
    actualChangeAfterPitches: numberOrNull(pick(item, "actualChangeAfterPitches", "actual_change_after_pitches")),
    actualChangeAfterBatters: numberOrNull(pick(item, "actualChangeAfterBatters", "actual_change_after_batters")),
    runsAfterModelWindow: numberOrNull(pick(item, "runsAfterModelWindow", "runs_after_model_window")),
    runsAfterModelWindowSource: stringOrNull(pick(item, "runsAfterModelWindowSource", "runs_after_model_window_source")),
    damageFlag: numberOrNull(pick(item, "damageFlag", "damage_flag")),
    missedHookDamageFlag: numberOrNull(pick(item, "missedHookDamageFlag", "missed_hook_damage_flag")),
    productionDegradation,
    normalizedDegradation,
    recommendedRelieverId: stringOrNull(pick(item, "recommendedRelieverId", "recommended_reliever_id")),
    recommendedRelieverName: stringOrNull(pick(item, "recommendedRelieverName", "recommended_reliever_name")),
    starterValueNextWindow: numberOrNull(pick(item, "starterValueNextWindow", "starter_value_next_3_hitters")),
    bestRelieverValueNextWindow: numberOrNull(pick(item, "bestRelieverValueNextWindow", "best_reliever_value_next_3_hitters")),
    decisionDelta: numberOrNull(pick(item, "decisionDelta", "decision_delta")),
    allocationBucket: stringOrNull(pick(item, "allocationBucket", "allocation_bucket")),
    peakWindow: booleanOrNull(pick(item, "peakWindow", "peak_window")),
    windowCount: numberOrNull(pick(item, "windowCount", "window_count")),
    calibratedPreventableSignal: numberOrNull(pick(item, "calibratedPreventableSignal", "calibrated_preventable_signal")),
    calibrationBucket: stringOrNull(pick(item, "calibrationBucket", "calibration_bucket")),
    calibrationSampleCount: numberOrNull(pick(item, "calibrationSampleCount", "calibration_sample_count")),
    calibrationMeanDamage: numberOrNull(pick(item, "calibrationMeanDamage", "calibration_mean_damage")),
    calibrationConfidence: numberOrNull(pick(item, "calibrationConfidence", "calibration_confidence")),
    leverageIndex: numberOrNull(pick(item, "leverageIndex", "leverage_index")),
    degradationScore: numberOrNull(pick(item, "degradationScore", "degradation_score")) ?? productionDegradation ?? normalizedDegradation,
    decayVelocity: numberOrNull(pick(item, "decayVelocity", "decay_velocity")),
    decayAcceleration: numberOrNull(pick(item, "decayAcceleration", "decay_acceleration")),
    topFeatures: asArray(pick(item, "topFeatures", "top_features", "topFeatureContributions", "top_feature_contributions")).map(mapFeatureContribution),
  };
}

function normalizePreventableRunsPayload(value: unknown): PreventableRunsOpportunitiesPayload {
  const payload = asRecord(value);
  const rows = asArray(pick(payload, "rows")).map(mapOpportunityRow);
  const summaryValue = pick(payload, "summary");
  const summary = summaryValue && typeof summaryValue === "object" ? mapTeamSummary(summaryValue) : null;
  return {
    status: stringOrNull(pick(payload, "status")) ?? "unavailable",
    generatedAt: stringOrNull(pick(payload, "generatedAt", "generated_at")),
    season: numberOrNull(pick(payload, "season")),
    team: stringOrNull(pick(payload, "team")),
    rowCount: numberOrNull(pick(payload, "rowCount", "row_count")) ?? rows.length,
    sourceRows: numberOrNull(pick(payload, "sourceRows", "source_rows")),
    source: stringOrNull(pick(payload, "source")),
    summary,
    teamSummaries: asArray(pick(payload, "teamSummaries", "team_summaries")).map(mapTeamSummary),
    pitcherSummaries: asArray(pick(payload, "pitcherSummaries", "pitcher_summaries")).map(mapPitcherSummary),
    rows,
  };
}

export function fetchPreventableRunsOpportunities(
  query: { season?: number | string; team?: string; gameId?: string | null; limit?: number; scope?: "top" | "game_matrix" | "all_games" } = {},
): Promise<PreventableRunsOpportunitiesPayload> {
  const params = new URLSearchParams();
  if (query.season) params.set("season", String(query.season));
  if (query.team) params.set("team", query.team);
  if (query.gameId) params.set("game_id", query.gameId);
  if (query.limit != null) params.set("limit", String(query.limit));
  if (query.scope) params.set("scope", query.scope);
  return fetchJson<unknown>(`/v1/pitching/preventable-runs/opportunities?${params.toString()}`).then(normalizePreventableRunsPayload);
}

export function fetchEnterpriseGames(query: RunSavingBoardQuery = {}): Promise<EnterpriseGamesPayload> {
  const params = new URLSearchParams();
  params.set("league", query.league ?? "mlb");
  if (query.team) params.set("team", query.team);
  if (query.date) params.set("date", query.date);
  if (query.limit != null) params.set("limit", String(query.limit));
  return fetchJson<EnterpriseGamesPayload>(`/v1/enterprise/run-saving/games?${params.toString()}`);
}

export function fetchPitcherProfiles(query: RunSavingBoardQuery & { year?: string } = {}): Promise<PitcherProfilesPayload> {
  const params = new URLSearchParams();
  params.set("league", query.league ?? "mlb");
  if (query.team) params.set("team", query.team);
  if (query.year) params.set("year", query.year);
  if (query.limit != null) params.set("limit", String(query.limit));
  return fetchJson<PitcherProfilesPayload>(`/v1/enterprise/run-saving/pitcher-profiles?${params.toString()}`);
}

export function fetchPitchingAuditSummary(
  query: RunSavingBoardQuery & {
    year?: string;
    leverage_band?: "ROUTINE" | "ELEVATED" | "HIGH";
    status?: "STAY" | "WATCH" | "PREP" | "PULL_NOW";
    actual_outcome?: "changed" | "stayed";
  } = {},
): Promise<PitchingAuditSummaryPayload> {
  const params = new URLSearchParams();
  params.set("league", query.league ?? "mlb");
  params.set("limit", String(query.limit ?? 500));
  if (query.team) params.set("team", query.team);
  if (query.year) params.set("year", query.year);
  if (query.leverage_band) params.set("leverage_band", query.leverage_band);
  if (query.status) params.set("status", query.status);
  if (query.actual_outcome) params.set("actual_outcome", query.actual_outcome);
  return fetchJson<PitchingAuditSummaryPayload>(`/v1/pitching/audit/summary?${params.toString()}`);
}

export function fetchPitchingReplay(gameId: string, league: "mlb" | "triple_a" = "mlb"): Promise<PitchingReplayResponse> {
  return fetchJson<PitchingReplayResponse>(`/v1/pitching/replay/${encodeURIComponent(gameId)}?league=${league}`);
}

export function fetchPitchingRecap(gameId: string, league: "mlb" | "triple_a" = "mlb"): Promise<PitchingGameRecap> {
  return fetchJson<PitchingGameRecap>(`/v1/pitching/recap/${encodeURIComponent(gameId)}?league=${league}`);
}

// Phase JJ.3b — Game Briefings share links resolve a grant to a single
// game's locked replay view (no login).
export interface PitchingReplayShareGrant {
  grant_id: string;
  game_id: string;
  team: string;
  date?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  matchup?: string | null;
  state: string;
}

export function fetchReplayShareGrant(grantId: string): Promise<PitchingReplayShareGrant> {
  return fetchJson<PitchingReplayShareGrant>(`/v1/pitching/share/grant/${encodeURIComponent(grantId)}`);
}

export function fetchPitchingRecapSettings(league: "mlb" | "triple_a" = "mlb"): Promise<PitchingRecapSettings> {
  return fetchJson<PitchingRecapSettings>(`/v1/pitching/recap-settings?league=${league}`);
}

export function savePitchingRecapSettings(
  patch: Partial<PitchingRecapSettings>,
  league: "mlb" | "triple_a" = "mlb",
): Promise<PitchingRecapSettings> {
  return fetchJson<PitchingRecapSettings>(`/v1/pitching/recap-settings?league=${league}`, {
    method: "POST",
    body: JSON.stringify(patch),
  });
}

export function sendPitchingRecapEmail(
  params: { game_id: string; team: string; recipient?: string; send?: boolean },
  league: "mlb" | "triple_a" = "mlb",
): Promise<PitchingRecapEmailResponse> {
  return fetchJson<PitchingRecapEmailResponse>(`/v1/pitching/recap-email?league=${league}`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ---------- Public-share Replay (Phase D) ----------

export type ShareGrantPublic = {
  grant_id: string;
  game_id: string;
  team: string | null;
  date: string | null;
  home_team: string | null;
  away_team: string | null;
  matchup: string | null;
  recipient_hint: string | null;
  expires_at: string | null;
  state: string | null;
  access_url: string | null;
};

export type ShareReplayBundle = {
  grant: ShareGrantPublic;
  replay: PitchingReplayResponse;
  recap: PitchingGameRecap;
};

export function fetchShareReplayBundle(grantId: string): Promise<ShareReplayBundle> {
  return fetchJson<ShareReplayBundle>(
    `/v1/pitching/share/grant/${encodeURIComponent(grantId)}/replay`,
  );
}

// ---------- Admin API (Phase B) ----------

import { supabase } from "./lib/supabase";

export type AdminUserRecord = {
  user_id: string;
  email: string;
  role: "admin" | "viewer";
  full_name: string | null;
  team_abbrs: string[];
  created_at: string | null;
};

async function authedHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Sign in required");
  return { Authorization: `Bearer ${token}` };
}

export async function listAdminUsers(): Promise<AdminUserRecord[]> {
  const headers = await authedHeaders();
  const payload = await fetchJson<{ users: AdminUserRecord[] }>("/v1/admin/users", { headers });
  return payload.users ?? [];
}

export async function inviteAdminUser(input: {
  email: string;
  role: "admin" | "viewer";
  team_abbrs: string[];
  full_name?: string | null;
}): Promise<AdminUserRecord> {
  const headers = await authedHeaders();
  const payload = await fetchJson<{ user: AdminUserRecord }>("/v1/admin/users/invite", {
    method: "POST",
    headers,
    body: JSON.stringify(input),
  });
  return payload.user;
}

export async function updateAdminUser(
  userId: string,
  patch: { role?: "admin" | "viewer"; team_abbrs?: string[]; full_name?: string | null },
): Promise<void> {
  const headers = await authedHeaders();
  await fetchJson<{ ok: boolean }>(`/v1/admin/users/${encodeURIComponent(userId)}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(patch),
  });
}

export async function deleteAdminUser(userId: string): Promise<void> {
  const headers = await authedHeaders();
  await fetchJson<{ ok: boolean }>(`/v1/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    headers,
  });
}

export async function setAdminUserPassword(userId: string, password: string): Promise<void> {
  const headers = await authedHeaders();
  await fetchJson<{ ok: boolean }>(
    `/v1/admin/users/${encodeURIComponent(userId)}/set-password`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ password }),
    },
  );
}

export type TeamRecipientRecord = {
  id: string;
  team_abbr: string;
  email: string;
  name: string | null;
  briefings_enabled: boolean;
};

export async function listTeamRecipients(teamAbbr: string): Promise<TeamRecipientRecord[]> {
  const { data, error } = await supabase
    .from("team_recipients")
    .select("id, team_abbr, email, name, briefings_enabled")
    .eq("team_abbr", teamAbbr.toUpperCase())
    .order("email");
  if (error) throw error;
  return (data ?? []).map((row) => ({
    id: String(row.id),
    team_abbr: String(row.team_abbr).toUpperCase(),
    email: String(row.email),
    name: row.name ?? null,
    briefings_enabled: Boolean(row.briefings_enabled),
  }));
}

export async function addTeamRecipient(
  teamAbbr: string,
  email: string,
  name?: string | null,
): Promise<TeamRecipientRecord> {
  const { data, error } = await supabase
    .from("team_recipients")
    .insert({ team_abbr: teamAbbr.toUpperCase(), email, name: name ?? null })
    .select("id, team_abbr, email, name, briefings_enabled")
    .single();
  if (error) throw error;
  return {
    id: String(data.id),
    team_abbr: String(data.team_abbr).toUpperCase(),
    email: String(data.email),
    name: data.name ?? null,
    briefings_enabled: Boolean(data.briefings_enabled),
  };
}

export async function updateTeamRecipient(
  recipientId: string,
  patch: { briefings_enabled?: boolean; name?: string | null },
): Promise<void> {
  const { error } = await supabase.from("team_recipients").update(patch).eq("id", recipientId);
  if (error) throw error;
}

export async function deleteTeamRecipient(recipientId: string): Promise<void> {
  const { error } = await supabase.from("team_recipients").delete().eq("id", recipientId);
  if (error) throw error;
}
