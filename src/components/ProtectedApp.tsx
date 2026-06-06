import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { Login } from "../pages/Login";

export function ProtectedApp({ children }: { children: ReactNode }) {
  const { session, profile, loading, profileLoading, needsPasswordSetup } = useAuth();

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
