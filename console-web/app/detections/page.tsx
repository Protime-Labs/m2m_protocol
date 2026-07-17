"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { ago, type ConsoleEvent } from "@/lib/types";

type Det = ConsoleEvent & { category: "ioc" | "response" | "recorded-not-adjudicated" };

const CAT_TONE: Record<Det["category"], string> = {
  ioc: "var(--warn)",
  response: "var(--critical)",
  "recorded-not-adjudicated": "var(--accent)",
};

export default function Detections() {
  const [rows, setRows] = useState<Det[]>([]);
  const [cat, setCat] = useState("all");
  const [open, setOpen] = useState<number | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const { data } = await supabase().from("console_detections").select("*").limit(300);
    setRows((data ?? []) as Det[]);
  }, []);

  useEffect(() => {
    refresh();
    const ch = supabase().channel("detections")
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "console_events" },
        () => {
          if (debounce.current) clearTimeout(debounce.current);
          debounce.current = setTimeout(refresh, 400);
        })
      .subscribe();
    return () => { supabase().removeChannel(ch); };
  }, [refresh]);

  const view = rows.filter((r) => cat === "all" || r.category === cat);

  return (
    <>
      <h1 className="page">Detections &amp; responses</h1>
      <p className="sub">IOCs, autonomous hygiene responses, and semantic-judge notes across the fleet.</p>

      <div className="note honest">
        <b>Recorded, not adjudicated:</b> the overlay&apos;s gates are syntactic (spec 10.1).
        Semantic-judge entries are advisory signals that were <i>captured and evidenced</i> —
        they were never verified, never enforced, and are never shown as &quot;clean&quot;.
        A lone judge signal can at most narrow an agent (Tier 1); it cannot quarantine.
      </div>

      <div className="filters">
        <select value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="all">All categories</option>
          <option value="ioc">IOC (deterministic detection)</option>
          <option value="response">Hygiene response (W3)</option>
          <option value="recorded-not-adjudicated">Judge — recorded, not adjudicated</option>
        </select>
        <span className="mut" style={{ fontSize: 12.5 }}>{view.length} entries</span>
      </div>

      <div className="scroll" style={{ maxHeight: 620 }}>
        <table>
          <thead><tr><th>Category</th><th>Agent</th><th>Kind</th><th>Detail</th><th>When</th></tr></thead>
          <tbody>
            {view.map((r) => (
              <>
                <tr key={r.id} className="click" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td><span className="pill" style={{ color: CAT_TONE[r.category] }}>
                    <span className="dot" />{r.category}</span></td>
                  <td className="mono">
                    {r.agent
                      ? <Link href={`/agents/${encodeURIComponent(r.src)}/${encodeURIComponent(r.agent)}`}>{r.agent}</Link>
                      : "—"}
                  </td>
                  <td className="mono">{r.kind}</td>
                  <td className="mut">
                    {r.kind === "hygiene"
                      ? `Tier ${String(r.data["tier"])} — ${String(r.data["tier_name"] ?? "")}`
                      : r.kind === "call"
                        ? `${String(r.data["tool"])}: ${((r.data["iocs"] as string[]) ?? []).join(", ")}`
                        : String(r.data["verdict"] ?? "")}
                  </td>
                  <td className="mut">{ago(r.ts)}</td>
                </tr>
                {open === r.id && (
                  <tr key={`${r.id}-x`}><td colSpan={5}>
                    <div className="payload">{JSON.stringify(r.data, null, 2)}</div>
                  </td></tr>
                )}
              </>
            ))}
            {view.length === 0 && <tr><td colSpan={5} className="mut">No detections.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
