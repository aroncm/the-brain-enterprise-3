// Public, no-login embed of the standalone abs-live-signal Model Scorecard
// dashboard (CORS open) — reached via ?view=scorecard&token=<share-token> on
// this app's root, bypassed straight past auth in ProtectedApp so it never
// touches session state or renders any platform chrome/data.
const viteEnv = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
const LIVE_API_BASE = (
  viteEnv.VITE_LIVE_SIGNAL_API_BASE ?? "https://aroncm--abs-live-signal-fastapi-live-app.modal.run"
).replace(/\/+$/, "");

export function ScorecardShare({ token }: { token: string }) {
  const cleanToken = token.trim();

  if (!cleanToken) {
    return (
      <div className="auth-loading">
        <div className="auth-denied">
          <h2>Invalid scorecard link</h2>
          <p>This link is missing its share token. Ask an admin for the current Model Scorecard link.</p>
        </div>
      </div>
    );
  }

  return (
    <iframe
      src={`${LIVE_API_BASE}/scorecard/shared/${encodeURIComponent(cleanToken)}`}
      title="Baseball brAIn Model Scorecard"
      style={{ position: "fixed", inset: 0, width: "100vw", height: "100vh", border: "none" }}
    />
  );
}
