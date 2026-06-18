import { useCallback, useEffect, useRef, useState } from "react";
import type { EnterpriseGameSummary, PitchingReplayResponse } from "./types";

// The live replay payload is served by the standalone abs-live-signal Modal app
// (CORS open), separate from the main enterprise API base. It returns the SAME
// shape the postgame Game Replays screen consumes, so GameAudit renders it verbatim.
const viteEnv = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
const LIVE_API_BASE = (
  viteEnv.VITE_LIVE_SIGNAL_API_BASE ?? "https://aroncm--abs-live-signal-fastapi-live-app.modal.run"
).replace(/\/+$/, "");
const REFRESH_MS = 30_000;

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

  const fetchReplay = useCallback(async (pk: string, initial: boolean) => {
    if (initial) setStatus("loading");
    else setRefreshing(true);
    try {
      const res = await fetch(`${LIVE_API_BASE}/v1/live/replay/${pk}`, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`replay ${res.status}`);
      const payload = (await res.json()) as PitchingReplayResponse & { available?: boolean; reason?: string };
      if (payload && payload.available === false) {
        setReplay(null);
        setReason(payload.reason ?? "No live signal yet for this game.");
      } else {
        setReplay(payload as PitchingReplayResponse);
        setReason(null);
      }
      setStatus("ready");
      setLastUpdated(new Date());
    } catch (caught) {
      setReason(caught instanceof Error ? caught.message : String(caught));
      if (initial) setStatus("error");
    } finally {
      setRefreshing(false);
    }
  }, []);

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
    void fetchReplay(selectedGameId, true);
    if (selectedIsLive) {
      pollRef.current = window.setInterval(() => void fetchReplay(selectedGameId, false), REFRESH_MS);
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
      LIVE · auto-refresh 30s{lastUpdated ? ` · ${lastUpdated.toLocaleTimeString()}` : ""}
    </div>
  );
}

const STATUS_RANK: Record<string, number> = { DISTRESS: 4, "PULL NOW": 3, PREP: 2, WATCH: 1, STAY: 0 };
function statusLabel(s: unknown): string {
  return String(s || "STAY").replace(/_/g, " ").toUpperCase();
}
function pct(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(Math.max(0, Math.min(1, n)) * 100) : null;
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

function finalScore(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// Derives the COMPLETED-game outcome (final score + the starter's peak model signal)
// from the live replay payload. Pure data only — App renders it inline with the shared
// Mobian panel/outcome-card styling (and CustomSelect picker), so the Live Dugout
// matches Game Replays without a circular import. The live replay `game` block carries
// final_{home,away}_score at runtime (the frontend type doesn't declare them, hence the
// cast). Returns null until the payload (and its game block) is available.
export function summarizeLiveOutcome(
  replay: PitchingReplayResponse | null,
  teamAbbr: string,
): LiveOutcomeSummaryData | null {
  const game = replay?.game as
    | (PitchingReplayResponse["game"] & { final_home_score?: unknown; final_away_score?: unknown })
    | undefined;
  if (!game) return null;
  const entries = ((replay?.entries ?? []) as any[]).filter((e) => e?.snapshot?.fielding_team === teamAbbr);
  let starterName = "";
  let peakStatus = "STAY";
  let peakInning: number | null = null;
  let peakHook: number | null = null;
  for (const e of entries) {
    const snap = e.snapshot ?? {};
    const rec = e.recommendation ?? {};
    if (!starterName) starterName = snap.pitcher_name ?? "";
    const st = statusLabel(rec.status);
    if ((STATUS_RANK[st] ?? 0) > (STATUS_RANK[peakStatus] ?? 0)) {
      peakStatus = st;
      peakInning = snap.inning ?? null;
    }
    const h = pct(rec.decision_pressure_score);
    if (h != null && (peakHook == null || h > peakHook)) peakHook = h;
  }
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
