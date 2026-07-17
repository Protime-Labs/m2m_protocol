"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { ago, type ConsoleEvent, type PostureRow } from "@/lib/types";
import PosturePill, { AssuranceBadge } from "@/components/PosturePill";
import AgentGraph from "@/components/AgentGraph";

export default function AgentDetail({ params }: { params: Promise<{ src: string; agent: string }> }) {
  const { src: rawSrc, agent: rawAgent } = use(params);
  const src = decodeURIComponent(rawSrc);
  const agent = decodeURIComponent(rawAgent);

  const [row, setRow] = useState<PostureRow | null>(null);
  const [events, setEvents] = useState<ConsoleEvent[]>([]);
  const [tab, setTab] = useState<"overview" | "graph" | "events">("overview");
  const [open, setOpen] = useState<number | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const sb = supabase();
    const { data: p } = await sb.from("console_agent_posture").select("*")
      .eq("src", src).eq("agent", agent).maybeSingle();
    setRow(p as PostureRow | null);
    const { data: ev } = await sb.from("console_events").select("*")
      .eq("src", src).eq("agent", agent).order("id", { ascending: true }).limit(500);
    setEvents((ev ?? []) as ConsoleEvent[]);
  }, [src, agent]);

  useEffect(() => {
    refresh();
    const ch = supabase().channel(`agent-${agent}`)
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "console_events", filter: `agent=eq.${agent}` },
        () => {
          if (debounce.current) clearTimeout(debounce.current);
          debounce.current = setTimeout(refresh, 400);
        })
      .subscribe();
    return () => { supabase().removeChannel(ch); };
  }, [refresh, agent]);

  const birth = (row?.birth ?? {}) as Record<string, unknown>;

  return (
    <>
      <p className="sub" style={{ marginBottom: 4 }}>
        <Link href="/agents">Agents</Link> <span className="mut">/</span>{" "}
        <span className="mono">{src}</span>
      </p>
      <h1 className="page mono" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {agent}
        {row && <PosturePill posture={row.posture} />}
        {row && <AssuranceBadge assurance={row.assurance} />}
      </h1>
      <p className="sub">Last activity {row ? ago(row.last_ts) : "…"} · {events.length} events mirrored from the estate&apos;s hash-chained recorder.</p>

      <div className="tabs">
        {(["overview", "graph", "events"] as const).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t === "graph" ? "Activity graph" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "overview" && row && (
        <div className="cards" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Identity &amp; enrollment (W2 birth)</h3>
            <table><tbody>
              <tr><td className="mut">SPIFFE ID</td><td className="mono">{row.spiffe_id ?? "— (software-attested)"}</td></tr>
              <tr><td className="mut">First seen</td><td>{new Date(row.first_seen).toLocaleString()}</td></tr>
              <tr><td className="mut">Granted tools</td><td className="mono">{((birth["tools"] as string[]) ?? []).join(", ") || "–"}</td></tr>
              <tr><td className="mut">Attestation hash</td><td className="mono">{String(birth["attestation_hash"] ?? "–")}</td></tr>
              <tr><td className="mut">cosign verified</td><td>{birth["cosign_ok"] === true ? "yes" : "no (stand-in manifest)"}</td></tr>
            </tbody></table>
            {row.assurance === "software-attested" && (
              <div className="note honest">
                Enrolled without a cryptographic hardware/artifact root. Weaker assurance is
                shown, not hidden — treat this agent&apos;s attestation as software-only.
              </div>
            )}
          </div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Governance rollup</h3>
            <div className="tiles">
              <div className="tile"><div className="k">Allowed</div><div className="v">{row.allow_count}</div></div>
              <div className="tile"><div className="k">Denied</div><div className="v">{row.deny_count}</div></div>
              <div className="tile"><div className="k">IOCs</div><div className="v">{row.ioc_count}</div></div>
              <div className="tile"><div className="k">Max hygiene tier</div><div className="v">{row.max_tier || "–"}</div></div>
            </div>
            {row.max_tier >= 3 && (
              <div className="note honest">
                Posture <b>quarantined</b> is inferred from a Tier-{row.max_tier} hygiene response
                (revocation). The estate&apos;s revocation list is the source of truth.
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "graph" && <AgentGraph agent={agent} events={events} />}

      {tab === "events" && (
        <div className="scroll" style={{ maxHeight: 560 }}>
          <table>
            <thead><tr><th>#</th><th>Kind</th><th>seq</th><th>t</th><th>When</th><th>Summary</th></tr></thead>
            <tbody>
              {[...events].reverse().map((e) => (
                <>
                  <tr key={e.id} className="click" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    <td className="mono mut">{e.id}</td>
                    <td className="mono">{e.kind}</td>
                    <td className="mono">{e.seq ?? "–"}</td>
                    <td className="mono">{e.t ?? "–"}</td>
                    <td className="mut">{ago(e.ts)}</td>
                    <td className="mut">
                      {e.kind === "call"
                        ? `${String(e.data["tool"])} → ${String(e.data["decision"])}${(e.data["iocs"] as unknown[] | undefined)?.length ? " · IOC" : ""}`
                        : String(e.data["tool"] ?? e.data["task_id"] ?? e.data["tier_name"] ?? "")}
                    </td>
                  </tr>
                  {open === e.id && (
                    <tr key={`${e.id}-x`}><td colSpan={6}>
                      <div className="payload">{JSON.stringify(e.data, null, 2)}</div>
                    </td></tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
