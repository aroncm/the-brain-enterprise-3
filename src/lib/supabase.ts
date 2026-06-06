import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

// detectSessionInUrl is disabled because the default behavior processes
// the URL synchronously at client construction time — BEFORE React
// mounts. The PASSWORD_RECOVERY event then fires before any listener is
// attached, and the recovery / invite flow silently drops the user into
// the App with no chance to set a password. We handle the URL ourselves
// in AuthContext via exchangeCodeForSession + an explicit hash parse.
export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    detectSessionInUrl: false,
    persistSession: true,
    autoRefreshToken: true,
    flowType: "pkce",
  },
});
