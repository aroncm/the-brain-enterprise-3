import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
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
// Yesterday..today so the picker has games to render even before first pitch
// (recently-finished games replay fine; in-progress games are prioritized).
function scheduleUrl(): string {
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  // hydrate=team so each game carries team.abbreviation (the bare schedule embeds
  // only {id, name, link}); we filter the picker to the selected club by abbr.
  return `https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=${ymd(yesterday)}&endDate=${ymd(today)}&hydrate=team`;
}

type LiveRender = (args: {
  replay: PitchingReplayResponse | null;
  games: EnterpriseGameSummary[];
  selectedGameId: string | null;
  onGameChange: (id: string) => void;
}) => ReactNode;

export default function LiveDugout({ team, children }: { team: { abbr: string }; children: LiveRender }) {
  const [games, setGames] = useState<EnterpriseGameSummary[]>([]);
  const [liveIds, setLiveIds] = useState<Set<string>>(new Set());
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);
  const [replay, setReplay] = useState<PitchingReplayResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [reason, setReason] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Discover in-progress + recently-finished games; default to a live game
  // involving the club in focus (else any live game, else the most recent final).
  const loadGames = useCallback(async () => {
    try {
      const res = await fetch(scheduleUrl(), { headers: { Accept: "application/json" } });
      const data = (await res.json()) as { dates?: Array<{ games?: any[] }> };
      const all = (data.dates ?? []).flatMap((d) => d.games ?? []);
      const isLive = (g: any) => String(g.status?.detailedState ?? "").includes("In Progress");
      const isFinal = (g: any) => ["Final", "Game Over"].includes(String(g.status?.detailedState ?? ""));
      // Only THIS club's games — GameAudit filters entries to team.abbr, so a game
      // that doesn't involve the selected team would render nothing.
      const isOurs = (g: any) =>
        g.teams?.home?.team?.abbreviation === team.abbr || g.teams?.away?.team?.abbreviation === team.abbr;
      const usable = all.filter((g) => (isLive(g) || isFinal(g)) && isOurs(g));
      const summaries: EnterpriseGameSummary[] = usable.map((g) => ({
        game_id: String(g.gamePk),
        date: String(g.gameDate ?? "").slice(0, 10),
        home_team: g.teams?.home?.team?.abbreviation ?? "HOME",
        away_team: g.teams?.away?.team?.abbreviation ?? "AWAY",
      }));
      // Live games first, then most-recent finals.
      summaries.sort((a, b) => {
        const al = usable.find((g) => String(g.gamePk) === a.game_id && isLive(g)) ? 0 : 1;
        const bl = usable.find((g) => String(g.gamePk) === b.game_id && isLive(g)) ? 0 : 1;
        return al - bl || b.date.localeCompare(a.date);
      });
      setLiveIds(new Set(usable.filter(isLive).map((g) => String(g.gamePk))));
      setGames(summaries);
      setSelectedGameId((cur) => {
        if (cur && summaries.some((g) => g.game_id === cur)) return cur;
        const liveSet = new Set(usable.filter(isLive).map((g) => String(g.gamePk)));
        const mineLive = summaries.find((g) => liveSet.has(g.game_id) && (g.home_team === team.abbr || g.away_team === team.abbr));
        const anyLive = summaries.find((g) => liveSet.has(g.game_id));
        return (mineLive ?? anyLive ?? summaries[0])?.game_id ?? cur ?? null;
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
        {(() => {
          const isLive = selectedGameId != null && liveIds.has(selectedGameId);
          return (
            <>
              <span className={`live-dot${isLive ? "" : " live-dot--final"}${refreshing ? " live-dot--pulse" : ""}`} aria-hidden />
              <span>
                {!selectedGameId
                  ? games.length
                    ? "Select a game"
                    : "No recent games"
                  : lastUpdated
                    ? `${isLive ? "LIVE" : "FINAL · review"} · updated ${lastUpdated.toLocaleTimeString()}${isLive ? " · auto-refresh 30s" : ""}`
                    : "Loading game…"}
              </span>
            </>
          );
        })()}
      </div>
      {status === "error" ? <p className="live-message live-message--error">Live signal unavailable: {reason}</p> : null}
      {status === "ready" && !replay && reason ? <p className="live-message">{reason}</p> : null}
      {children({ replay, games, selectedGameId, onGameChange: setSelectedGameId })}
    </div>
  );
}
