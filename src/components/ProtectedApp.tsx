import { useState, type ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { Login } from "../pages/Login";
import { PublicSite } from "../pages/PublicSite";
import { ScorecardShare } from "./ScorecardShare";

export function ProtectedApp({ children }: { children: ReactNode }) {
  const { session, profile, loading, profileLoading, needsPasswordSetup } = useAuth();
  const [showLogin, setShowLogin] = useState(false);

  // Phase JJ.3b — Game Briefings share links render the locked single-game
  // replay WITHOUT a session. The pitching data endpoints are public; the
  // share view itself hides all navigation chrome (see App shareMode), and
  // the grant id is validated against the backend before anything renders.
  const shareParams = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  if (shareParams.get("view") === "shared-replay" && (shareParams.get("grant") || "").trim()) {
    return <>{children}</>;
  }

  // Public, no-login pages (terms + privacy) — reachable regardless of
  // session so carrier/partner reviewers and recipients can read them.
  const publicPage = shareParams.get("page");
  if (publicPage === "terms" || publicPage === "privacy") {
    return <PublicSite page={publicPage} onSignIn={() => { window.location.href = "/?signin=1"; }} />;
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
    // Public landing for signed-out visitors (the login form itself sits
    // behind the Sign in button, or directly via /?signin=1). Toll-free
    // verification requires the root domain to describe the business and
    // the text-alert program without requiring a login.
    if (showLogin || shareParams.get("signin") === "1") {
      return <Login />;
    }
    return <PublicSite page="landing" onSignIn={() => setShowLogin(true)} />;
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
