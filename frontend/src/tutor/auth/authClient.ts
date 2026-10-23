// The slice of a Supabase client the tutor uses for sign-in. A local type, so a host that mounts the tutor
// with host identity (AuDHS) does not need @supabase/supabase-js at all; a real SupabaseClient fits it.
export interface AuthSession {
  access_token: string;
  user: { id: string };
}

export interface AuthClient {
  auth: {
    getSession(): Promise<{ data: { session: AuthSession | null } }>;
    onAuthStateChange(callback: (event: string, session: AuthSession | null) => void): {
      data: { subscription: { unsubscribe(): void } };
    };
    signInWithPassword(credentials: { email: string; password: string }): Promise<{ error: { message: string } | null }>;
    signOut(): Promise<unknown>;
  };
}
