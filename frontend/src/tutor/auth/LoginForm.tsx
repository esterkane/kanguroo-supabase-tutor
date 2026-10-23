import { useState } from "react";
import type { AuthClient } from "./authClient";
import type { Strings } from "../i18n";

export function LoginForm({ supabase, s }: { supabase: AuthClient; s: Strings }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setError(error ? `${s.signInFailed}: ${error.message}` : null);
  };

  return (
    <form onSubmit={submit} className="mx-auto mt-24 w-80 space-y-3 rounded border border-zinc-800 p-4 text-sm">
      <h1 className="font-semibold">{s.title}</h1>
      <label className="block">{s.email}
        <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
               className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 p-1.5" />
      </label>
      <label className="block">{s.password}
        <input type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)}
               className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 p-1.5" />
      </label>
      {error && <p role="alert" className="text-red-400">{error}</p>}
      <button type="submit" className="w-full rounded bg-sky-700 py-1.5">{s.signIn}</button>
    </form>
  );
}
