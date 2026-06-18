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
// yesterday..today so the picker has the club's games even before first pitch;
// hydrate=team so each game carries team.abbreviation (the bare schedule embeds
// only {id, name, link}).
function scheduleUrl(): string {
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  return `https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=${ymd(yesterday)}&endDate=${ymd(today)}&hydrate=team`;
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
      const summaries: EnterpriseGameSummary[] = usable.map((g) => ({
        game_id: String(g.gamePk),
        date: String(g.gameDate ?? "").slice(0, 10),
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

// Compact outcome card for a COMPLETED game (the Live Dugout does NOT duplicate the
// full replay). Built from the live replay payload; links to the full Game Replays.
export function LiveOutcomeSummary({
  replay,
  teamAbbr,
  games,
  selectedGameId,
  onGameChange,
  onViewReplay,
}: {
  replay: PitchingReplayResponse | null;
  teamAbbr: string;
  games: EnterpriseGameSummary[];
  selectedGameId: string | null;
  onGameChange: (id: string) => void;
  onViewReplay: () => void;
}) {
  const game = replay?.game;
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

  if (!game) {
    return (
      <section className="workflow theme-mobian">
        <article className="live-outcome live-outcome--empty">
          <p>No game loaded. Pick a recent game above, or wait for a live one.</p>
        </article>
      </section>
    );
  }
  return (
    <section className="workflow theme-mobian">
      <article className="live-outcome">
        {games.length > 1 ? (
          <label className="live-outcome__picker">
            <span>Game</span>
            <select value={selectedGameId ?? ""} onChange={(e) => onGameChange(e.target.value)}>
              {games.map((g) => (
                <option key={g.game_id} value={g.game_id}>
                  {g.away_team} @ {g.home_team} · {g.date}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <p className="live-outcome__eyebrow">Game Outcome · Final</p>
        <h2 className="live-outcome__score">
          {game.away_team} {game.final_away_score ?? 0} <span className="live-outcome__dash">—</span> {game.final_home_score ?? 0} {game.home_team}
        </h2>
        <p className="live-outcome__detail">
          {starterName ? <strong>{starterName}</strong> : "Starter"} ·{" "}
          {peakStatus === "STAY" ? (
            <>the model never signaled a pull.</>
          ) : (
            <>
              model peaked at <strong>{peakStatus}</strong>
              {peakInning ? ` in the ${peakInning}` : ""}
              {peakHook != null ? ` · Hook ${peakHook}%` : ""}.
            </>
          )}
        </p>
        <p className="live-outcome__hint">
          The Live Dugout tracks in‑progress games. This game is final — open the full replay for the pitch‑by‑pitch
          breakdown and the outcome audit.
        </p>
        <button type="button" className="live-outcome__cta" onClick={onViewReplay}>
          View full replay →
        </button>
      </article>
    </section>
  );
}
