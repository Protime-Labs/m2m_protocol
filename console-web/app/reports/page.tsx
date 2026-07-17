"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { ago } from "@/lib/types";

interface Rollup { posture: string; agents: number }
interface Denial { id: number; src: string; agent: string; ts: number; tool: string; reason: string }

const TONE: Record<string, string> = {
  compliant: "var(--good)", drifting: "var(--warn)", "out-of-scope": "var(--serious)",
  quarantined: "var(--critical)", stale: "var(--neutral)",
};

export default function Reports() {
  const [rollup, setRollup] = useState<Rollup[]>([]);
  const [denials, setDenials] = useState<Denial[]>([]);

  useEffect(() => {
    (async () => {
      const sb = supabase();
      const { data: r } = await sb.from("console_fleet_rollup").select("*");
      setRollup((r ?? []) as Rollup[]);
      const { data: d } = await sb.from("console_denials").select("*").limit(200);
      setDenials((d ?? []) as Denial[]);
    })();
  }, []);

  const total = rollup.reduce((a, r) => a + r.agents, 0);
  const byReason = denials.reduce<Record<string, number>>((acc, d) => {
    const key = (d.reason ?? "unknown").split(":")[0].slice(0, 60);
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <h1 className="page">Reports</h1>
      <p className="sub">Fleet compliance rollups, backed by the console&apos;s SQL views (query them directly for ad-hoc reporting).</p>

      <div className="cards" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Fleet posture distribution</h3>
          {total > 0 && (
            <div style={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", margin: "8px 0 14px" }}>
              {rollup.map((r) => (
                <div key={r.posture} title={`${r.posture}: ${r.agents}`}
                  style={{ width: `${(100 * r.agents) / total}%`, background: TONE[r.posture] ?? "var(--neutral)" }} />
              ))}
            </div>
          )}
          <table><tbody>
            {rollup.map((r) => (
              <tr key={r.posture}>
                <td><span className="pill" style={{ color: TONE[r.posture] }}><span className="dot" />{r.posture}</span></td>
                <td style={{ textAlign: "right", fontWeight: 600 }}>{r.agents}</td>
                <td className="mut" style={{ textAlign: "right" }}>{total ? Math.round((100 * r.agents) / total) : 0}%</td>
              </tr>
            ))}
            <tr><td className="mut">total</td><td style={{ textAlign: "right", fontWeight: 700 }}>{total}</td><td /></tr>
          </tbody></table>
        </div>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>Denials by cause</h3>
          <table><tbody>
            {Object.entries(byReason).sort((a, b) => b[1] - a[1]).map(([reason, n]) => (
              <tr key={reason}><td className="mut">{reason}</td>
                <td style={{ textAlign: "right", fontWeight: 600 }}>{n}</td></tr>
            ))}
            {denials.length === 0 && <tr><td className="mut">No denials recorded.</td></tr>}
          </tbody></table>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3 style={{ marginTop: 0 }}>Recent denials</h3>
        <div className="scroll" style={{ maxHeight: 380 }}>
          <table>
            <thead><tr><th>Agent</th><th>Tool</th><th>Reason</th><th>When</th></tr></thead>
            <tbody>
              {denials.map((d) => (
                <tr key={d.id}>
                  <td className="mono">
                    <Link href={`/agents/${encodeURIComponent(d.src)}/${encodeURIComponent(d.agent)}`}>{d.agent}</Link>
                  </td>
                  <td className="mono">{d.tool ?? "–"}</td>
                  <td className="mut">{d.reason}</td>
                  <td className="mut">{ago(d.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
