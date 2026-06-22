// Phase R.3 — in-memory session cache for replay + recap payloads.
//
// Replays and recaps are deterministic per game_id within a session — no
// server-side mutation that would require invalidation. Storing them in
// a module-scoped Map means a second visit to the same game within the
// session is a synchronous cache hit, and the Phase R.4 background
// pre-fetch lands in the same place so the on-demand fetch becomes a
// no-op when the user actually picks the most-recent game.
//
// Refresh on a hard reload clears the cache (no persistence by design —
// the user picked the in-memory option for simplicity and freshness).

import type {
  EnterpriseGameSummary,
  PitcherProfilesPayload,
  PitchingAuditSummaryPayload,
  PitchingGameRecap,
  PitchingReplayResponse,
  PreventableRunsOpportunitiesPayload,
  RunSavingBoardPayload,
} from "./types";

const replayCache = new Map<string, PitchingReplayResponse>();
const recapCache = new Map<string, PitchingGameRecap>();

// Per-team (keyed by `${team}:${season}`) club context — the games catalog +
// pitcher profiles + audit summary loaded on every team switch. These are
// stable enough within a session that re-selecting a team should render
// instantly from cache while a background revalidation refreshes it
// (stale-while-revalidate). Same module-scoped, cleared-on-reload lifetime as
// the replay/recap caches above.
export interface ClubContextPayload {
  games: EnterpriseGameSummary[];
  profiles: PitcherProfilesPayload | null;
  auditSummary: PitchingAuditSummaryPayload | null;
}

const clubContextCache = new Map<string, ClubContextPayload>();

export function getCachedClubContext(key: string): ClubContextPayload | undefined {
  return clubContextCache.get(key);
}

export function setCachedClubContext(key: string, payload: ClubContextPayload): void {
  clubContextCache.set(key, payload);
}

// Dashboard / Run Saving board + Preventable Runs opportunities — also re-fetched
// on every team switch. Same stale-while-revalidate treatment so re-selecting a
// team renders the board instantly. Keyed by the full request param set.
const runSavingBoardCache = new Map<string, RunSavingBoardPayload>();

export function getCachedRunSavingBoard(key: string): RunSavingBoardPayload | undefined {
  return runSavingBoardCache.get(key);
}

export function setCachedRunSavingBoard(key: string, payload: RunSavingBoardPayload): void {
  runSavingBoardCache.set(key, payload);
}

const preventableRunsCache = new Map<string, PreventableRunsOpportunitiesPayload>();

export function getCachedPreventableRuns(key: string): PreventableRunsOpportunitiesPayload | undefined {
  return preventableRunsCache.get(key);
}

export function setCachedPreventableRuns(key: string, payload: PreventableRunsOpportunitiesPayload): void {
  preventableRunsCache.set(key, payload);
}

export function getCachedReplay(gameId: string): PitchingReplayResponse | undefined {
  return replayCache.get(gameId);
}

export function setCachedReplay(gameId: string, payload: PitchingReplayResponse): void {
  replayCache.set(gameId, payload);
}

export function getCachedRecap(gameId: string): PitchingGameRecap | undefined {
  return recapCache.get(gameId);
}

export function setCachedRecap(gameId: string, payload: PitchingGameRecap): void {
  recapCache.set(gameId, payload);
}
