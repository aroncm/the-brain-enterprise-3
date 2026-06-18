import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import type { EnterpriseGameSummary, PitchingReplayResponse } from "./types";

// The live replay payload is served by the standalone abs-live-signal Modal app
// (CORS open), separate from the main enterprise API base. It returns the SAME
// shape the postgame Game Replays screen consumes, so GameAudit renders it verbatim.
const viteEnv = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
const LIVE_API_BASE = (
  viteEnv.VITE_LIVE_SIGNAL_API_BASE ?? "https://aroncm--abs-live-signal-fastapi-live-app.modal.run"
).replace(/\/+$/, "");
const SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1";
const REFRESH_MS = 30_000;

type LiveRender = (args: {
  replay: PitchingReplayResponse | null;
  games: EnterpriseGameSummary[];
  selectedGameId: string | null;
  onGameChange: (id: string) => void;
}) => ReactNode;

export default function LiveDugout({ team, children }: { team: { abbr: string }; children: LiveRender }) {
  const [games, setGames] = useState<EnterpriseGameSummary[]>([]);
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);
  const [replay, setReplay] = useState<PitchingReplayResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [reason, setReason] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Discover today's in-progress games; default to the one involving the club in focus.
  const loadGames = useCallback(async () => {
    try {
      const res = await fetch(SCHEDULE_URL, { headers: { Accept: "application/json" } });
      const data = (await res.json()) as { dates?: Array<{ games?: any[] }> };
      const all = (data.dates ?? []).flatMap((d) => d.games ?? []);
      const live: EnterpriseGameSummary[] = all
        .filter((g) => String(g.status?.detailedState ?? "").includes("In Progress"))
        .map((g) => ({
          game_id: String(g.gamePk),
          date: String(g.gameDate ?? "").slice(0, 10),
          home_team: g.teams?.home?.team?.abbreviation ?? "HOME",
          away_team: g.teams?.away?.team?.abbreviation ?? "AWAY",
        }));
      setGames(live);
      setSelectedGameId((cur) => {
        if (cur && live.some((g) => g.game_id === cur)) return cur;
        const mine = live.find((g) => g.home_team === team.abbr || g.away_team === team.abbr);
        return (mine ?? live[0])?.game_id ?? cur ?? null;
      });
    } catch {
      /* schedule is best-effort */
    }
  }, [team.abbr]);

  useEffect(() => {
    void loadGames();
    const id = window.setInterval(() => void loadGames(), 60_000);
    return () => window.clearInterval(id);
  }, [loadGames]);

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

  useEffect(() => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (!selectedGameId) {
      setReplay(null);
      setStatus("idle");
      return;
    }
    void fetchReplay(selectedGameId, true);
    pollRef.current = window.setInterval(() => void fetchReplay(selectedGameId, false), REFRESH_MS);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [selectedGameId, fetchReplay]);

  return (
    <div className="live-dugout">
      <div className="live-statusbar">
        <span className={`live-dot${refreshing ? " live-dot--pulse" : ""}`} aria-hidden />
        <span>
          {!selectedGameId
            ? games.length
              ? "Select a live game"
              : "No games in progress"
            : lastUpdated
              ? `LIVE · updated ${lastUpdated.toLocaleTimeString()} · auto-refresh 30s`
              : "Loading live game…"}
        </span>
      </div>
      {status === "error" ? <p className="live-message live-message--error">Live signal unavailable: {reason}</p> : null}
      {status === "ready" && !replay && reason ? <p className="live-message">{reason}</p> : null}
      {children({ replay, games, selectedGameId, onGameChange: setSelectedGameId })}
    </div>
  );
}
