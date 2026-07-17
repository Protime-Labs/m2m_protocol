"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import { ago, type ConsoleEvent, type PostureRow } from "@/lib/types";
import PosturePill from "@/components/PosturePill";

const POSTURES = ["compliant", "drifting", "out-of-scope", "quarantined", "stale"] as const;

export default function Dashboard() {
  const [rows, setRows] = useState<PostureRow[]>([]);
  const [ticker, setTicker] = useState<ConsoleEvent[]>([]);
  const [feedHealth, setFeedHealth] = useState<Record<string, unknown> | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const sb = supabase();
    const { data } = await sb.from("console_agent_posture").select("*");
    setRows((data ?? []) as PostureRow[]);
    const { data: ev } = await sb.from("console_events").select("*")
      .order("id", { ascending: false }).limit(30);
    const evs = (ev ?? []) as ConsoleEvent[];
    setTicker(evs);
    const fh = evs.find((e) => e.kind === "feed-health");
    if (fh) setFeedHealth(fh.data);
  }, []);

  useEffect(() => {
    refresh();
    // Realtime: any new event -> debounced refresh (an agent appears the moment
    // its birth event lands; posture flips as soon as evidence arrives).
    const ch = supabase().channel("dash")
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "console_events" },
        () => {
          if (debounce.current) clearTimeout(debounce.current);
          debounce.current = setTimeout(refresh, 400);
        })
      .subscribe();
    return () => { supabase().removeChannel(ch); };
  }, [refresh]);

  const by = (p: string) => rows.filter((r) => r.posture === p).length;
  const denials = rows.reduce((a, r) => a + r.deny_count, 0);
  const iocs = rows.reduce((a, r) => a + r.ioc_count, 0);
  const sources = new Set(rows.map((r) => r.src)).size;

  return (
    <>
      <h1 className="page">Fleet dashboard</h1>
      <p className="sub">Live posture of every enrolled agent, across {sources || "…"} reporting estate{sources === 1 ? "" : "s"}.</p>

      <div className="strip">
        <span className="gauge" style={{ color: iocs || denials ? "var(--warn)" : "var(--good)" }}>
          <span className="dot" /> {denials} denials · {iocs} IOCs
        </span>
        <span className="gauge" style={{ color: by("quarantined") ? "var(--critical)" : "var(--good)" }}>
          <span className="dot" /> {by("quarantined")} quarantined
        </span>
        <span className="gauge" style={{ color: "var(--good)" }}>
          <span className="dot" /> evidence mirror of hash-chained C9 recorders
        </span>
        {feedHealth != null && (
          <span className="gauge" style={{ color: Number(feedHealth["dropped"] ?? 0) > 0 ? "var(--warn)" : "var(--good)" }}>
            <span className="dot" /> feed: {String(feedHealth["emitted"] ?? "?")} emitted · {String(feedHealth["dropped"] ?? 0)} dropped
          </span>
        )}
      </div>

      <div className="tiles" style={{ marginBottom: 18 }}>
        <div className="tile"><div className="k">Agents</div><div className="v">{rows.length}</div>
          <div className="s">enrolled via W2 birth</div></div>
        {POSTURES.map((p) => (
          <div className="tile" key={p}>
            <div className="k">{p}</div>
            <div className="v"><span className={`pill st-${p}`}><span className="dot" />{by(p)}</span></div>
          </div>
        ))}
      </div>

      <div className="cards" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Attention needed</h3>
          <div className="scroll" style={{ maxHeight: 340 }}>
            <table>
              <thead><tr><th>Agent</th><th>Posture</th><th>Deny</th><th>IOC</th><th>Tier</th><th>Last seen</th></tr></thead>
              <tbody>
                {rows.filter((r) => r.posture !== "compliant")
                  .sort((a, b) => b.max_tier - a.max_tier || b.ioc_count - a.ioc_count)
                  .map((r) => (
                    <tr key={`${r.src}/${r.agent}`} className="click"
                      onClick={() => (window.location.href = `/agents/${encodeURIComponent(r.src)}/${encodeURIComponent(r.agent)}`)}>
                      <td className="mono">{r.agent}<div className="mut" style={{ fontSize: 10.5 }}>{r.src}</div></td>
                      <td><PosturePill posture={r.posture} /></td>
                      <td>{r.deny_count}</td><td>{r.ioc_count}</td><td>{r.max_tier || "–"}</td>
                      <td className="mut">{ago(r.last_ts)}</td>
                    </tr>
                  ))}
                {rows.length > 0 && rows.every((r) => r.posture === "compliant") && (
                  <tr><td colSpan={6} className="mut">Entire fleet compliant.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Live events</h3>
          <div className="ticker">
            {ticker.filter((e) => e.kind !== "feed-health").map((e) => {
              const deny = e.kind === "call" && e.data["allowed"] === false;
              const warn = e.kind === "hygiene" || (Array.isArray(e.data["iocs"]) && (e.data["iocs"] as unknown[]).length > 0);
              return (
                <div key={e.id} className={`tick${deny ? " deny" : warn ? " warn" : ""}`}>
                  <span className="t">{ago(e.ts)}</span>
                  <span className="mono">{e.agent ?? "—"}</span>
                  <span>{e.kind}{e.kind === "call" ? ` · ${String(e.data["tool"] ?? "")} → ${String(e.data["decision"] ?? "")}` : ""}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}
