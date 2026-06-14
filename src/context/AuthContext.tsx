import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";

export type Role = "admin" | "viewer";

export interface Profile {
  role: Role;
  fullName: string | null;
  teamAbbrs: string[];
}

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  profile: Profile | null;
  loading: boolean;
  profileLoading: boolean;
  needsPasswordSetup: boolean;
  signOut: () => Promise<void>;
  reloadProfile: () => Promise<void>;
  clearPasswordSetup: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchProfile(userId: string): Promise<Profile | null> {
  const [{ data: profileRow, error: profileError }, { data: memberRows, error: memberError }] = await Promise.all([
    supabase.from("profiles").select("role, full_name").eq("user_id", userId).maybeSingle(),
    supabase.from("team_memberships").select("team_abbr").eq("user_id", userId),
  ]);
  if (profileError) {
    console.warn("[auth] profile fetch failed", profileError);
    return null;
  }
  if (!profileRow) {
    return null;
  }
  if (memberError) {
    console.warn("[auth] team_memberships fetch failed", memberError);
  }
  const role = (profileRow.role === "admin" ? "admin" : "viewer") as Role;
  const teamAbbrs = (memberRows ?? [])
    .map((row) => String(row.team_abbr || "").toUpperCase())
    .filter((value, index, all) => Boolean(value) && all.indexOf(value) === index)
    .sort();
  return {
    role,
    fullName: profileRow.full_name ?? null,
    teamAbbrs,
  };
}

type AuthLinkParams = {
  code: string | null;
  tokenHash: string | null;
  accessToken: string | null;
  refreshToken: string | null;
  type: string | null;
  errorDescription: string | null;
};

function readAuthLinkParams(): AuthLinkParams {
  if (typeof window === "undefined") {
    return { code: null, tokenHash: null, accessToken: null, refreshToken: null, type: null, errorDescription: null };
  }
  const search = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const pick = (key: string) => search.get(key) || hash.get(key) || null;
  return {
    code: pick("code"),
    tokenHash: pick("token_hash"),
    accessToken: pick("access_token"),
    refreshToken: pick("refresh_token"),
    type: (pick("type") || "").toLowerCase() || null,
    errorDescription: pick("error_description"),
  };
}

function clearAuthLinkUrl() {
  if (typeof window === "undefined") return;
  if (!window.history?.replaceState) return;
  window.history.replaceState({}, document.title, window.location.pathname + window.location.search.replace(/[?&]?(code|token_hash|type|access_token|refresh_token|expires_in|expires_at|token_type|provider_token|provider_refresh_token|error|error_code|error_description)=[^&]*/g, "").replace(/^&/, "?"));
}

function isPasswordSetupType(type: string | null): boolean {
  return type === "invite" || type === "recovery" || type === "signup";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  // Seed from the URL synchronously. Any sign-in via URL params (code OR
  // access_token) means the user clicked an invite or recovery link, and
  // they need to set/reset their password before anything else. Default
  // to true if ANY URL param looks auth-related; we only learn the type
  // for sure after the exchange.
  const [needsPasswordSetup, setNeedsPasswordSetup] = useState<boolean>(() => {
    const params = readAuthLinkParams();
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.log("[auth] initial URL params", {
        href: window.location.href,
        ...params,
      });
    }
    return Boolean(params.code) || Boolean(params.tokenHash) || Boolean(params.accessToken) || isPasswordSetupType(params.type);
  });
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const finishUrlExchange = async () => {
      const params = readAuthLinkParams();
      // eslint-disable-next-line no-console
      console.log("[auth] finishUrlExchange start", params);
      if (params.errorDescription) {
        setLinkError(params.errorDescription);
        clearAuthLinkUrl();
        setLoading(false);
        return;
      }
      let exchangeOk = false;
      try {
        if (params.tokenHash) {
          // Supabase server-generated invite/recovery links (token_hash flow).
          // verifyOtp needs no client code_verifier — unlike exchangeCodeForSession,
          // which fails for admin-generated links since the verifier never existed
          // on this device. This is the durable path for our invite-only app.
          const otpType = (params.type || "invite") as "invite" | "recovery" | "signup" | "email";
          const { error } = await supabase.auth.verifyOtp({ type: otpType, token_hash: params.tokenHash });
          if (error) throw error;
          exchangeOk = true;
          // eslint-disable-next-line no-console
          console.log("[auth] verifyOtp (token_hash) succeeded", { type: otpType });
        } else if (params.code) {
          await supabase.auth.exchangeCodeForSession(params.code);
          exchangeOk = true;
          // eslint-disable-next-line no-console
          console.log("[auth] exchangeCodeForSession succeeded");
        } else if (params.accessToken && params.refreshToken) {
          await supabase.auth.setSession({
            access_token: params.accessToken,
            refresh_token: params.refreshToken,
          });
          exchangeOk = true;
          // eslint-disable-next-line no-console
          console.log("[auth] setSession from hash succeeded");
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[auth] URL exchange failed", err);
        if (!cancelled) {
          setLinkError(err instanceof Error ? err.message : "Could not complete sign-in link");
        }
      }
      if (params.code || params.tokenHash || params.accessToken) {
        clearAuthLinkUrl();
      }
      if (!cancelled) {
        const { data } = await supabase.auth.getSession();
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.log("[auth] post-exchange session", {
          hasSession: !!data.session,
          userEmail: data.session?.user?.email,
          exchangeOk,
        });
        setSession(data.session);
        // If we just consumed URL auth params AND landed on a session,
        // force password setup. Invite + recovery are the only flows
        // that put auth params in the URL for an invite-only app, and
        // both need the user to set a password before the next time.
        if (exchangeOk) {
          setNeedsPasswordSetup(true);
        }
        setLoading(false);
      }
    };

    void finishUrlExchange();

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, nextSession) => {
      // eslint-disable-next-line no-console
      console.log("[auth] onAuthStateChange", event, { hasSession: !!nextSession });
      setSession(nextSession);
      if (event === "PASSWORD_RECOVERY") {
        setNeedsPasswordSetup(true);
      }
      if (event === "SIGNED_OUT") {
        setNeedsPasswordSetup(false);
      }
    });
    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  const loadProfile = useCallback(async (userId: string | null) => {
    if (!userId) {
      setProfile(null);
      return;
    }
    setProfileLoading(true);
    try {
      const next = await fetchProfile(userId);
      setProfile(next);
    } finally {
      setProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProfile(session?.user?.id ?? null);
  }, [session?.user?.id, loadProfile]);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setProfile(null);
    setNeedsPasswordSetup(false);
  }, []);

  const reloadProfile = useCallback(async () => {
    await loadProfile(session?.user?.id ?? null);
  }, [loadProfile, session?.user?.id]);

  const clearPasswordSetup = useCallback(() => {
    setNeedsPasswordSetup(false);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      user: session?.user ?? null,
      profile,
      loading,
      profileLoading,
      needsPasswordSetup,
      signOut,
      reloadProfile,
      clearPasswordSetup,
    }),
    [session, profile, loading, profileLoading, needsPasswordSetup, signOut, reloadProfile, clearPasswordSetup],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
