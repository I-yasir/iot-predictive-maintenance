import { useQueryClient } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { keys } from "../api/queries";
import s from "./shell.module.css";

export function Login() {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const next = (loc.state as { from?: string } | null)?.from ?? "/overview";
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/login", null, { method: "POST", json: { password: pw } });
      qc.setQueryData(keys.me, { authenticated: true, auth_enabled: true });
      void qc.invalidateQueries({ queryKey: keys.me });
      nav(next, { replace: true });
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 401 ? "Wrong password." : "Could not reach the backend.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className={s.login}>
      <form className={`card ${s.loginCard}`} onSubmit={submit}>
        <h1 style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Activity color="var(--accent)" aria-hidden="true" /> PdM-Live
        </h1>
        <label>
          Dashboard password
          <input type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required autoFocus />
        </label>
        {err ? <p role="alert" style={{ color: "var(--state-critical-text)" }}>{err}</p> : null}
        <button className="primary" type="submit" disabled={busy || !pw}>Sign in</button>
      </form>
    </main>
  );
}
