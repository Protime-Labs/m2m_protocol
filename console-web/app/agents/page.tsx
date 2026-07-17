"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { ago, liveness, type PostureRow } from "@/lib/types";
import PosturePill, { AssuranceBadge } from "@/components/PosturePill";

export default function Agents() {
  const [rows, setRows] = useState<PostureRow[]>([]);
  const [src, setSrc] = useState("all");
  const [posture, setPosture] = useState("all");
  const [q, setQ] = useState("");
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const { data } = await supabase().from("console_agent_posture").select("*");
    setRows((data ?? []) as PostureRow[]);
  }, []);

  useEffect(() => {
    refresh();
    const ch = supabase().channel("agents")
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "console_events" },
        () => {
          if (debounce.current) clearTimeout(debounce.current);
          debounce.current = setTimeout(refresh, 400);
        })
      .subscribe();
    return () => { supabase().removeChannel(ch); };
  }, [refresh]);

  const sources = [...new Set(rows.map((r) => r.src))].sort();
  const view = rows.filter((r) =>
    (src === "all" || r.src === src) &&
    (posture === "all" || r.posture === posture) &&
    (!q || r.agent.toLowerCase().includes(q.toLowerCase())));

  const dot = { live: "var(--good)", idle: "var(--warn)", offline: "var(--neutral)" } as const;

  return (
    <>
      <h1 className="page">Agents</h1>
      <p className="sub">Every agent enrolled through W2 birth, live. An agent appears here the moment its birth record lands.</p>

      <div className="filters">
        <input type="text" placeholder="Search agent id…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={src} onChange={(e) => setSrc(e.target.value)}>
          <option value="all">All sources</option>
          {sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={posture} onChange={(e) => setPosture(e.target.value)}>
          <option value="all">All postures</option>
          {["compliant", "drifting", "out-of-scope", "quarantined", "stale"].map((p) =>
            <option key={p} value={p}>{p}</option>)}
        </select>
        <span className="mut" style={{ fontSize: 12.5 }}>{view.length} of {rows.length} agents</span>
      </div>

      <div className="scroll">
        <table>
          <thead>
            <tr><th></th><th>Agent</th><th>Source</th><th>Posture</th><th>Assurance</th>
              <th>Allow</th><th>Deny</th><th>IOCs</th><th>Hygiene tier</th><th>Records</th><th>Last seen</th></tr>
          </thead>
          <tbody>
            {view.map((r) => {
              const lv = liveness(r);
              return (
                <tr key={`${r.src}/${r.agent}`} className="click"
                  onClick={() => (window.location.href = `/agents/${encodeURIComponent(r.src)}/${encodeURIComponent(r.agent)}`)}>
                  <td><span title={lv} style={{ display: "inline-block", width: 8, height: 8, borderRadius: 4, background: dot[lv] }} /></td>
                  <td className="mono">
                    <Link href={`/agents/${encodeURIComponent(r.src)}/${encodeURIComponent(r.agent)}`}>{r.agent}</Link>
                  </td>
                  <td className="mono mut" style={{ fontSize: 11 }}>{r.src}</td>
                  <td><PosturePill posture={r.posture} /></td>
                  <td><AssuranceBadge assurance={r.assurance} /></td>
                  <td>{r.allow_count}</td>
                  <td style={r.deny_count ? { color: "var(--critical)", fontWeight: 600 } : undefined}>{r.deny_count}</td>
                  <td style={r.ioc_count ? { color: "var(--warn)", fontWeight: 600 } : undefined}>{r.ioc_count}</td>
                  <td>{r.max_tier || "–"}</td>
                  <td>{r.record_count}</td>
                  <td className="mut">{ago(r.last_ts)}</td>
                </tr>
              );
            })}
            {view.length === 0 && <tr><td colSpan={11} className="mut">No agents match.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
