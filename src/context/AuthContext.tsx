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
  signOut: () => Promise<void>;
  reloadProfile: () => Promise<void>;
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setSession(data.session);
      setLoading(false);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
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
  }, []);

  const reloadProfile = useCallback(async () => {
    await loadProfile(session?.user?.id ?? null);
  }, [loadProfile, session?.user?.id]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      user: session?.user ?? null,
      profile,
      loading,
      profileLoading,
      signOut,
      reloadProfile,
    }),
    [session, profile, loading, profileLoading, signOut, reloadProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
