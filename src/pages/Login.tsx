import { useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
    if (signInError) {
      setError(signInError.message);
    }
    setSubmitting(false);
  };

  return (
    <div className="login-shell">
      <div className="login-card">
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

        <h2 className="login-heading">Sign in</h2>

        <form onSubmit={onSubmit} className="login-form">
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

          {error ? <div className="login-error">{error}</div> : null}

          <button type="submit" disabled={submitting} className="login-submit">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="login-footnote">Access is invite-only. Contact your administrator if you need an account.</p>
      </div>
    </div>
  );
}
