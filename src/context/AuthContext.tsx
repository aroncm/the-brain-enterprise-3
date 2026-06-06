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

function detectInitialPasswordSetup(): boolean {
  if (typeof window === "undefined") return false;
  // Supabase emits ?type=invite|recovery|signup (PKCE) or
  // #type=invite|recovery|signup (legacy hash). If we see either, the
  // user just clicked an email link and needs the password-setup form
  // — even though Supabase will also fire PASSWORD_RECOVERY shortly,
  // we flip the flag immediately so ProtectedApp doesn't briefly
  // render the App while the auth event is still in flight.
  const search = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const type = (search.get("type") || hash.get("type") || "").toLowerCase();
  return type === "invite" || type === "recovery" || type === "signup";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [needsPasswordSetup, setNeedsPasswordSetup] = useState<boolean>(() => detectInitialPasswordSetup());

  useEffect(() => {
    let cancelled = false;
    supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setSession(data.session);
      setLoading(false);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, nextSession) => {
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
