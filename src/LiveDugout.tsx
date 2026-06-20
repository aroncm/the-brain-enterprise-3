import { useCallback, useEffect, useRef, useState } from "react";
import { fetchPitchingReplay } from "./api";
import type { EnterpriseGameSummary, PitchingReplayResponse } from "./types";

// The live replay payload is served by the standalone abs-live-signal Modal app
// (CORS open), separate from the main enterprise API base. It returns the SAME
// shape the postgame Game Replays screen consumes, so GameAudit renders it verbatim.
const viteEnv = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
const LIVE_API_BASE = (
  viteEnv.VITE_LIVE_SIGNAL_API_BASE ?? "https://aroncm--abs-live-signal-fastapi-live-app.modal.run"
).replace(/\/+$/, "");
// ~5s poll for near-real-time hook latency. Cheap on the server: the endpoint
// returns 304 (no body, no recompute) unless a new pitch has arrived, and gzips
// the changed payload. See the live-replay endpoint in live_signal_app.py.
const REFRESH_MS = 5_000;

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}
// A handful of recent days so the picker has several completed games to choose
// from (plus any live game today). The StatsAPI filters startDate/endDate by
// officialDate, so a generous lookback captures the club's recent slate.
const LOOKBACK_DAYS = 5;
// hydrate=team so each game carries team.abbreviation (the bare schedule embeds
// only {id, name, link}).
function scheduleUrl(): string {
  const today = new Date();
  const start = new Date(today.getTime() - LOOKBACK_DAYS * 86_400_000);
  return `https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=${ymd(start)}&endDate=${ymd(today)}&hydrate=team`;
}

export type LiveDugoutState = {
  games: EnterpriseGameSummary[];
  selectedGameId: string | null;
  setSelectedGameId: (id: string) => void;
  replay: PitchingReplayResponse | null;
  status: "idle" | "loading" | "ready" | "error";
  reason: string | null;
  lastUpdated: Date | null;
  refreshing: boolean;
  isLive: boolean; // the SELECTED game is in progress
};

// Live game discovery + 30s polling of /v1/live/replay. Returned as a hook (no DOM
// wrapper) so App can render GameAudit as a direct child of .app-main — the sticky
// banner + 3-col grid only lay out correctly there. `enabled` gates all fetching to
// the live tab.
export function useLiveDugout(teamAbbr: string, enabled: boolean): LiveDugoutState {
  const [games, setGames] = useState<EnterpriseGameSummary[]>([]);
  const [liveIds, setLiveIds] = useState<Set<string>>(new Set());
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);
  const [replay, setReplay] = useState<PitchingReplayResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [reason, setReason] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef<number | null>(null);
  // ETag of the current game's last live payload → sent as If-None-Match so an
  // unchanged poll comes back as a tiny 304. Reset when the selected game changes.
  const etagRef = useRef<string | null>(null);

  const loadGames = useCallback(async () => {
    try {
      const res = await fetch(scheduleUrl(), { headers: { Accept: "application/json" } });
      const data = (await res.json()) as { dates?: Array<{ games?: any[] }> };
      const all = (data.dates ?? []).flatMap((d) => d.games ?? []);
      const isLive = (g: any) => String(g.status?.detailedState ?? "").includes("In Progress");
      const isFinal = (g: any) => ["Final", "Game Over"].includes(String(g.status?.detailedState ?? ""));
      const isOurs = (g: any) =>
        g.teams?.home?.team?.abbreviation === teamAbbr || g.teams?.away?.team?.abbreviation === teamAbbr;
      const usable = all.filter((g) => (isLive(g) || isFinal(g)) && isOurs(g));
      // officialDate is the game's local calendar date; gameDate is the UTC start
      // instant, which rolls a night game over to the next day (a 7pm ET game reads
      // as tomorrow in UTC). Always label by officialDate so a completed game isn't
      // mislabeled as a future date.
      const summaries: EnterpriseGameSummary[] = usable.map((g) => ({
        game_id: String(g.gamePk),
        date: String(g.officialDate ?? String(g.gameDate ?? "").slice(0, 10)),
        home_team: g.teams?.home?.team?.abbreviation ?? "HOME",
        away_team: g.teams?.away?.team?.abbreviation ?? "AWAY",
      }));
      const liveSet = new Set(usable.filter(isLive).map((g) => String(g.gamePk)));
      summaries.sort((a, b) => {
        const al = liveSet.has(a.game_id) ? 0 : 1;
        const bl = liveSet.has(b.game_id) ? 0 : 1;
        return al - bl || b.date.localeCompare(a.date);
      });
      setLiveIds(liveSet);
      setGames(summaries);
      setSelectedGameId((cur) => {
        if (cur && summaries.some((g) => g.game_id === cur)) return cur;
        const mineLive = summaries.find((g) => liveSet.has(g.game_id) && (g.home_team === teamAbbr || g.away_team === teamAbbr));
        const anyLive = summaries.find((g) => liveSet.has(g.game_id));
        return (mineLive ?? anyLive ?? summaries[0])?.game_id ?? cur ?? null;
      });
    } catch {
      /* schedule is best-effort */
    }
  }, [teamAbbr]);

  useEffect(() => {
    if (!enabled) return;
    void loadGames();
    const id = window.setInterval(() => void loadGames(), 60_000);
    return () => window.clearInterval(id);
  }, [enabled, loadGames]);

  // Live in-progress game → the live signal endpoint (CORS-open, on-the-fly compute).
  const fetchLiveEndpoint = useCallback(async (pk: string) => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (etagRef.current) headers["If-None-Match"] = etagRef.current;
    const res = await fetch(`${LIVE_API_BASE}/v1/live/replay/${pk}`, { headers });
    // 304 → no new pitch since the last poll; keep the current replay as-is.
    if (res.status === 304) return;
    if (!res.ok) throw new Error(`replay ${res.status}`);
    etagRef.current = res.headers.get("ETag");
    const payload = (await res.json()) as PitchingReplayResponse & { available?: boolean; reason?: string };
    if (payload && payload.available === false) {
      setReplay(null);
      setReason(payload.reason ?? "No live signal yet for this game.");
    } else {
      setReplay(payload as PitchingReplayResponse);
      setReason(null);
    }
  }, []);

  const fetchReplay = useCallback(
    async (pk: string, initial: boolean, live: boolean) => {
      if (initial) {
        // Switching games: drop the prior game's payload so its replay can't flash in
        // the new game's view while the new fetch is in flight, and clear the ETag so
        // the first fetch is unconditional (not a 304 against the old game).
        etagRef.current = null;
        setReplay(null);
        setReason(null);
        setStatus("loading");
      } else {
        setRefreshing(true);
      }
      try {
        if (live) {
          await fetchLiveEndpoint(pk);
        } else {
          // Completed game → read the POSTGAME replay (the exact source the Game Replays
          // tab renders) so the Outcome Summary matches it. The live endpoint computes
          // on-the-fly and can diverge by a pitch or two; the nightly postgame artifact
          // is the accurate one. If it isn't built yet for a just-finished game, fall
          // back to the live endpoint's final data.
          try {
            setReplay(await fetchPitchingReplay(pk));
            setReason(null);
          } catch {
            await fetchLiveEndpoint(pk);
          }
        }
        setStatus("ready");
        setLastUpdated(new Date());
      } catch (caught) {
        setReason(caught instanceof Error ? caught.message : String(caught));
        if (initial) setStatus("error");
      } finally {
        setRefreshing(false);
      }
    },
    [fetchLiveEndpoint],
  );

  // Only the LIVE selected game keeps polling. A completed game is fetched once
  // (so the Outcome Summary has data) but not re-polled.
  const selectedIsLive = selectedGameId != null && liveIds.has(selectedGameId);
  useEffect(() => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (!enabled || !selectedGameId) {
      if (!enabled) {
        setReplay(null);
        setStatus("idle");
      }
      return;
    }
    void fetchReplay(selectedGameId, true, selectedIsLive);
    if (selectedIsLive) {
      pollRef.current = window.setInterval(() => void fetchReplay(selectedGameId, false, true), REFRESH_MS);
    }
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [enabled, selectedGameId, selectedIsLive, fetchReplay]);

  return {
    games,
    selectedGameId,
    setSelectedGameId,
    replay,
    status,
    reason,
    lastUpdated,
    refreshing,
    isLive: selectedIsLive,
  };
}

// ── Small presentational pieces ──────────────────────────────────────────────

// A subtle, layout-neutral LIVE indicator (fixed-position pill, below the navbar).
export function LiveBadge({ lastUpdated, refreshing }: { lastUpdated: Date | null; refreshing: boolean }) {
  return (
    <div className="live-badge" aria-live="polite">
      <span className={`live-badge__dot${refreshing ? " live-badge__dot--pulse" : ""}`} aria-hidden />
      LIVE · auto-refresh {Math.round(REFRESH_MS / 1000)}s{lastUpdated ? ` · ${lastUpdated.toLocaleTimeString()}` : ""}
    </div>
  );
}

const STATUS_RANK: Record<string, number> = { DISTRESS: 4, "PULL NOW": 3, PREP: 2, WATCH: 1, STAY: 0 };
function statusLabel(s: unknown): string {
  return String(s || "STAY").replace(/_/g, " ").toUpperCase();
}
function rank(s: unknown): number {
  return STATUS_RANK[statusLabel(s)] ?? 0;
}
function finalScore(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
// Postgame artifacts store names as "Last, First"; the live feed gives "First Last".
// Normalize to "First Last" so the Starter card reads the same from either source.
function personName(raw: unknown): string {
  const s = String(raw ?? "").trim();
  const m = s.match(/^([^,]+),\s*(.+)$/);
  return m ? `${m[2]} ${m[1]}`.trim() : s;
}

// Mirror of App's isRelieverReplayEntry / pitchCount so the starter scope + ordering
// match Game Replays exactly. The live payload keeps relievers in reliever_entries, so
// `entries` is starters-only; this is belt-and-suspenders.
function isReliever(e: any): boolean {
  return e?.entry_type === "reliever_rss" || statusLabel(e?.snapshot?.role) === "RELIEVER" || !!e?.snapshot?.reliever_state;
}
function pitchCountOf(e: any): number {
  const st = e?.snapshot?.reliever_state ?? e?.snapshot?.starter_state ?? {};
  return st.official_pitch_count_in_game ?? st.pitch_count_in_game ?? st.replay_pitch_count_in_game ?? 0;
}
// Mirror of App's headlinePeak: cumulative max of decision_pressure_score (floored at 0,
// falling back to starter_state.normalized_degradation_score) THROUGH `idx`. This is the
// "Hook Score at Pull" the Game Replays Actual Outcome Summary shows — a peak *up to* the
// pull pitch, NOT the global game max.
function headlinePeakThrough(entries: any[], idx: number): number | null {
  let peak: number | null = null;
  const cap = Math.min(idx + 1, entries.length);
  for (let i = 0; i < cap; i++) {
    const dps = entries[i]?.recommendation?.decision_pressure_score;
    const fb = entries[i]?.snapshot?.starter_state?.normalized_degradation_score;
    const raw =
      typeof dps === "number" && Number.isFinite(dps)
        ? dps
        : typeof fb === "number" && Number.isFinite(fb)
          ? fb
          : null;
    if (raw == null) continue;
    const score = Math.max(0, raw);
    peak = peak == null ? score : Math.max(peak, score);
  }
  return peak;
}

export type LiveOutcomeSummaryData = {
  awayTeam: string;
  homeTeam: string;
  awayScore: number | null;
  homeScore: number | null;
  starterName: string;
  peakStatus: string;
  peakInning: number | null;
  peakHook: number | null;
};

// Derives the COMPLETED-game outcome (final score + the starter's peak model signal)
// from the live replay payload. Pure data only — App renders it inline with the shared
// Mobian panel/outcome-card styling (and CustomSelect picker), so the Live Dugout matches
// Game Replays without a circular import. The peak signal + Hook are computed the SAME way
// the Game Replays Actual Outcome Summary computes them: monotonic statuses (a signal can't
// downgrade once it fires), anchored on the FIRST pitch window that reached the peak signal
// (the pull pitch), with Hook = the cumulative pull-pressure peak THROUGH that window — not
// the global game max. The `game` block carries final_{home,away}_score at runtime (the
// frontend type doesn't declare them, hence the cast). Returns null until available.
export function summarizeLiveOutcome(
  replay: PitchingReplayResponse | null,
  teamAbbr: string,
): LiveOutcomeSummaryData | null {
  const game = replay?.game as
    | (PitchingReplayResponse["game"] & { final_home_score?: unknown; final_away_score?: unknown })
    | undefined;
  if (!game) return null;

  // Our team's STARTER entries, ordered by pitch count (matches Game Replays' starterEntries).
  const starterEntries = ((replay?.entries ?? []) as any[])
    .filter((e) => e?.snapshot?.fielding_team === teamAbbr && !isReliever(e))
    .sort((a, b) => pitchCountOf(a) - pitchCountOf(b));

  const starterName = personName(starterEntries[0]?.snapshot?.pitcher_name);

  // monotonicStatuses: running max status across the appearance.
  let running = "STAY";
  const mono = starterEntries.map((e) => {
    const s = statusLabel(e?.recommendation?.status);
    if (rank(s) > rank(running)) running = s;
    return running;
  });

  const peakStatus = mono.length ? mono[mono.length - 1] : "STAY";
  // First window that reached the peak signal — the pull pitch for a PULL NOW peak.
  const anchorIndex = mono.findIndex((s) => rank(s) >= rank(peakStatus));
  const peakInning = anchorIndex >= 0 ? (starterEntries[anchorIndex]?.snapshot?.inning ?? null) : null;
  const hookRaw = anchorIndex >= 0 ? headlinePeakThrough(starterEntries, anchorIndex) : null;
  const peakHook = hookRaw == null ? null : Math.round(Math.max(0, Math.min(1, hookRaw)) * 100);

  return {
    awayTeam: game.away_team,
    homeTeam: game.home_team,
    awayScore: finalScore(game.final_away_score),
    homeScore: finalScore(game.final_home_score),
    starterName,
    peakStatus,
    peakInning,
    peakHook,
  };
}
