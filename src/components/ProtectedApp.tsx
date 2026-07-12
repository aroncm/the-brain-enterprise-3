import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { Login } from "../pages/Login";
import { ScorecardShare } from "./ScorecardShare";

export function ProtectedApp({ children }: { children: ReactNode }) {
  const { session, profile, loading, profileLoading, needsPasswordSetup } = useAuth();

  // Phase JJ.3b — Game Briefings share links render the locked single-game
  // replay WITHOUT a session. The pitching data endpoints are public; the
  // share view itself hides all navigation chrome (see App shareMode), and
  // the grant id is validated against the backend before anything renders.
  const shareParams = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  if (shareParams.get("view") === "shared-replay" && (shareParams.get("grant") || "").trim()) {
    return <>{children}</>;
  }

  // Model Scorecard share link — public, no-login embed of the standalone
  // abs-live-signal dashboard. Unlike shared-replay above, this never renders
  // App/children at all: it's a flat iframe onto a separate, self-contained
  // Modal-hosted page, so no platform chrome, nav, or session state is ever
  // reachable through this URL.
  if (shareParams.get("view") === "scorecard") {
    return <ScorecardShare token={shareParams.get("token") || ""} />;
  }

  if (loading) {
    return (
      <div className="auth-loading">
        <div className="auth-loading__spinner" aria-label="Loading" />
      </div>
    );
  }

  // Even when a session exists, force the password-setup screen if
  // the user came in via an invite or recovery email — otherwise
  // the App renders behind a logged-in-but-passwordless user who
  // would never see the setup form.
  if (needsPasswordSetup) {
    return <Login />;
  }

  if (!session) {
    return <Login />;
  }

  if (profileLoading && !profile) {
    return (
      <div className="auth-loading">
        <div className="auth-loading__spinner" aria-label="Loading profile" />
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="auth-loading">
        <div className="auth-denied">
          <h2>Profile not configured</h2>
          <p>Your account exists but no Baseball brAIn profile is attached. Contact your administrator.</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
