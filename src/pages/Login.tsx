import { useEffect, useMemo, useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../context/AuthContext";

type Mode = "signIn" | "setPassword" | "forgotPassword";

const ENTERPRISE_BASE_URL =
  typeof window !== "undefined" ? `${window.location.origin}/` : "https://baseballbrain.club/";

// Suffix appended to redirect URLs so Supabase preserves the flow type
// in the final landing URL. Without this, the PKCE redirect only carries
// ?code=... and we lose the recovery/invite signal.
const RECOVERY_REDIRECT = `${ENTERPRISE_BASE_URL}?type=recovery`;

function detectInitialMode(): Mode {
  if (typeof window === "undefined") return "signIn";
  // Supabase appends ?type=invite|recovery in PKCE flows and
  // #type=invite|recovery in legacy hash flows. Read both.
  const search = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const type = (search.get("type") || hash.get("type") || "").toLowerCase();
  if (type === "invite" || type === "recovery" || type === "signup") {
    return "setPassword";
  }
  return "signIn";
}

export function Login() {
  const { clearPasswordSetup, needsPasswordSetup } = useAuth();
  const initialMode = useMemo(() => (needsPasswordSetup ? "setPassword" : detectInitialMode()), [needsPasswordSetup]);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // When AuthContext has consumed an invite/recovery link (token_hash /
  // code / hash) it sets needsPasswordSetup and clears the URL — by then the
  // ?type= param is gone, so drive setPassword mode off the context flag
  // rather than re-reading the (now-empty) URL.
  useEffect(() => {
    if (needsPasswordSetup) setMode("setPassword");
  }, [needsPasswordSetup]);

  // Supabase fires a PASSWORD_RECOVERY event when the user lands here
  // from a recovery email — flip to setPassword mode so they don't get
  // stuck on a sign-in form they have no password for.
  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") {
        setMode("setPassword");
      }
    });
    return () => {
      data.subscription.unsubscribe();
    };
  }, []);

  const resetMessages = () => {
    setError(null);
    setInfo(null);
  };

  const onSignIn = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    resetMessages();
    setSubmitting(true);
    const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
    if (signInError) {
      setError(signInError.message);
    }
    setSubmitting(false);
  };

  const onSetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    resetMessages();
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setError(updateError.message);
      setSubmitting(false);
      return;
    }
    setInfo("Password set. Signing you in…");
    // Supabase already has an active session from the invite/recovery
    // token, so the app will pick up on it. Clean the URL so a refresh
    // doesn't re-trigger setPassword mode.
    if (window.history.replaceState) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    // Release the needs-password gate in AuthContext so ProtectedApp
    // renders the App now that the user actually has a password.
    clearPasswordSetup();
    setSubmitting(false);
  };

  const onForgotPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    resetMessages();
    if (!email) {
      setError("Enter your email above first.");
      return;
    }
    setSubmitting(true);
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: RECOVERY_REDIRECT,
    });
    if (resetError) {
      setError(resetError.message);
    } else {
      setInfo("If an account exists for that email, a password-reset link is on its way.");
    }
    setSubmitting(false);
  };

  const inlineStyles = (
    <style>{`
      .login-subhead {
        margin: -4px 0 14px;
        text-align: center;
        font-size: 12px;
        color: #9a9a9a;
        line-height: 1.4;
      }
      .login-info {
        padding: 10px 12px;
        background: rgba(46, 196, 160, 0.10);
        border: 1px solid rgba(46, 196, 160, 0.45);
        border-radius: 8px;
        color: #74e0c2;
        font-size: 12px;
      }
      .login-link {
        background: none;
        border: none;
        padding: 0;
        color: #74e0c2;
        font: inherit;
        font-size: inherit;
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 2px;
      }
      .login-link:hover {
        color: #a5ecd6;
      }
    `}</style>
  );

  const brand = (
    <div className="login-brand">
      <svg className="login-brand__svg" viewBox="0 0 565 115" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Baseball brAIn">
        <text x="20" y="82" fontFamily="'Helvetica Neue',Helvetica,Arial,sans-serif" fontSize="36" fontWeight="300" letterSpacing="6" fill="#FFFFFF">BASEBALL</text>
        <text x="322" y="82" fontFamily="'Helvetica Neue',Helvetica,Arial,sans-serif" fontSize="84" fontWeight="700" letterSpacing="-1" fill="#FFFFFF" fillOpacity="0.7">
          <tspan fillOpacity="0.7">br</tspan>
          <tspan fill="#2ec4a0" fillOpacity="1">AI</tspan>
          <tspan fillOpacity="0.7">n</tspan>
        </text>
        <polygon points="277,17 312,52 277,87 242,52" fill="none" stroke="#FFFFFF" strokeWidth="2.5" strokeLinejoin="miter" />
        <line x1="269" y1="52" x2="285" y2="52" stroke="#2ec4a0" strokeWidth="1.8" strokeLinecap="round" />
        <line x1="277" y1="44" x2="277" y2="60" stroke="#2ec4a0" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <p className="login-brand__tagline">Advanced Baseball Intelligence</p>
    </div>
  );

  const renderMessages = () => (
    <>
      {error ? <div className="login-error">{error}</div> : null}
      {info ? <div className="login-info">{info}</div> : null}
    </>
  );

  if (mode === "setPassword") {
    return (
      <div className="login-shell">
        <div className="login-card">
          {brand}
          <h2 className="login-heading">Set up your password</h2>
          <p className="login-subhead">Pick a password for {email || "your account"}. Use 8+ characters.</p>
          <form onSubmit={onSetPassword} className="login-form">
            <label className="login-field">
              <span className="login-field__label">New password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
                className="login-field__input"
                placeholder="At least 8 characters"
              />
            </label>
            <label className="login-field">
              <span className="login-field__label">Confirm password</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
                className="login-field__input"
                placeholder="Re-enter the same password"
              />
            </label>
            {renderMessages()}
            <button type="submit" disabled={submitting} className="login-submit">
              {submitting ? "Saving…" : "Set password and continue"}
            </button>
          </form>
          <p className="login-footnote">
            Already have a password?{" "}
            <button
              type="button"
              className="login-link"
              onClick={() => {
                resetMessages();
                setMode("signIn");
              }}
            >
              Sign in
            </button>
          </p>
        </div>
      </div>
    );
  }

  if (mode === "forgotPassword") {
    return (
      <div className="login-shell">
        <div className="login-card">
          {brand}
          <h2 className="login-heading">Reset your password</h2>
          <p className="login-subhead">
            Enter your email and we'll send you a link to set a new password.
          </p>
          <form onSubmit={onForgotPassword} className="login-form">
            <label className="login-field">
              <span className="login-field__label">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
                className="login-field__input"
                placeholder="you@example.com"
              />
            </label>
            {renderMessages()}
            <button type="submit" disabled={submitting} className="login-submit">
              {submitting ? "Sending…" : "Send reset link"}
            </button>
          </form>
          <p className="login-footnote">
            <button
              type="button"
              className="login-link"
              onClick={() => {
                resetMessages();
                setMode("signIn");
              }}
            >
              Back to sign in
            </button>
          </p>
        </div>
      </div>
    );
  }

  // Default: sign-in mode
  return (
    <div className="login-shell">
      {inlineStyles}
      <div className="login-card">
        {brand}
        <h2 className="login-heading">Sign in</h2>
        <form onSubmit={onSignIn} className="login-form">
          <label className="login-field">
            <span className="login-field__label">Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoComplete="email"
              className="login-field__input"
              placeholder="you@example.com"
            />
          </label>
          <label className="login-field">
            <span className="login-field__label">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoComplete="current-password"
              className="login-field__input"
              placeholder="••••••••"
            />
          </label>
          {renderMessages()}
          <button type="submit" disabled={submitting} className="login-submit">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="login-footnote">
          <button
            type="button"
            className="login-link"
            onClick={() => {
              resetMessages();
              setMode("forgotPassword");
            }}
          >
            Forgot password?
          </button>
          {" · "}
          Access is invite-only.
        </p>
      </div>
    </div>
  );
}
