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
  PitchingGameRecap,
  PitchingReplayResponse,
} from "./types";

const replayCache = new Map<string, PitchingReplayResponse>();
const recapCache = new Map<string, PitchingGameRecap>();

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
