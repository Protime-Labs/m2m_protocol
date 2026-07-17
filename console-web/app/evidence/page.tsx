"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { ago, type ConsoleEvent } from "@/lib/types";

const KINDS = ["birth", "pre-actuation", "result", "hygiene", "task-outcome", "mode"];

export default function Evidence() {
  const [rows, setRows] = useState<ConsoleEvent[]>([]);
  const [kind, setKind] = useState("all");
  const [agent, setAgent] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    let q = supabase().from("console_events").select("*")
      .not("kind", "in", "(call,feed-health)")
      .order("id", { ascending: false }).limit(400);
    if (kind !== "all") q = kind === "reconciled" ? q.like("kind", "reconciled:%") : q.eq("kind", kind);
    if (agent) q = q.eq("agent", agent);
    const { data } = await q;
    setRows((data ?? []) as ConsoleEvent[]);
  }, [kind, agent]);

  useEffect(() => {
    refresh();
    const ch = supabase().channel("evidence")
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "console_events" },
        () => {
          if (debounce.current) clearTimeout(debounce.current);
          debounce.current = setTimeout(refresh, 500);
        })
      .subscribe();
    return () => { supabase().removeChannel(ch); };
  }, [refresh]);

  return (
    <>
      <h1 className="page">Evidence explorer</h1>
      <p className="sub">C9 flight-recorder records, mirrored live from every reporting estate.</p>

      <div className="note">
        This is an <b>operational mirror</b>. The evidence of record is each estate&apos;s
        hash-chained WORM recorder (verify() + Merkle root at the source); rows here carry
        the recorder <span className="mono">seq</span>/<span className="mono">t</span> for correlation back to it.
      </div>

      <div className="filters">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="all">All kinds</option>
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          <option value="reconciled">reconciled:*</option>
        </select>
        <input type="text" placeholder="Filter by agent id…" value={agent}
          onChange={(e) => setAgent(e.target.value)} />
        <span className="mut" style={{ fontSize: 12.5 }}>{rows.length} records</span>
      </div>

      <div className="scroll" style={{ maxHeight: 620 }}>
        <table>
          <thead><tr><th>#</th><th>Kind</th><th>Agent</th><th>Source</th><th>seq</th><th>t</th><th>When</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <>
                <tr key={r.id} className="click" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td className="mono mut">{r.id}</td>
                  <td className="mono">{r.kind}</td>
                  <td className="mono">
                    {r.agent
                      ? <Link href={`/agents/${encodeURIComponent(r.src)}/${encodeURIComponent(r.agent)}`}>{r.agent}</Link>
                      : "—"}
                  </td>
                  <td className="mono mut" style={{ fontSize: 11 }}>{r.src}</td>
                  <td className="mono">{r.seq ?? "–"}</td>
                  <td className="mono">{r.t ?? "–"}</td>
                  <td className="mut">{ago(r.ts)}</td>
                </tr>
                {open === r.id && (
                  <tr key={`${r.id}-x`}><td colSpan={7}>
                    <div className="payload">{JSON.stringify(r.data, null, 2)}</div>
                  </td></tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
