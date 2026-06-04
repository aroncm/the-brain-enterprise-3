import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { Login } from "../pages/Login";

export function ProtectedApp({ children }: { children: ReactNode }) {
  const { session, profile, loading, profileLoading } = useAuth();

  if (loading) {
    return (
      <div className="auth-loading">
        <div className="auth-loading__spinner" aria-label="Loading" />
      </div>
    );
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
