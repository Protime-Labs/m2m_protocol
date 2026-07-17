"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

/** Client-side auth gate: renders the login card until a Supabase session exists.
 *  Reads are additionally enforced server-side by RLS (authenticated-only), so this
 *  gate is UX -- the data plane does not rely on it. */
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const sb = supabase();
    sb.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!ready) return null;

  if (!session) {
    const signIn = async (e: React.FormEvent) => {
      e.preventDefault();
      setBusy(true);
      setErr("");
      const { error } = await supabase().auth.signInWithPassword({ email, password });
      if (error) setErr(error.message);
      setBusy(false);
    };
    return (
      <div className="login">
        <div className="card">
          <div className="brand" style={{ padding: 0, marginBottom: 10 }}>
            <div className="logo">M2</div>
            <div><b>M2M Fleet Console</b><small>AATA overlay — operator sign-in</small></div>
          </div>
          <form onSubmit={signIn}>
            <input type="email" placeholder="Email" value={email} autoComplete="username"
              onChange={(e) => setEmail(e.target.value)} required />
            <input type="password" placeholder="Password" value={password} autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)} required />
            <button className="btn" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
            {err && <div className="err">{err}</div>}
          </form>
          <p className="mut" style={{ fontSize: 12, marginTop: 12 }}>
            Accounts are provisioned by your administrator (Supabase Auth).
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
