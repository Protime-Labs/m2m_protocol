"use client";

import { useMemo, useState } from "react";
import type { ConsoleEvent } from "@/lib/types";

/** The clickable, explorable activity graph for one agent.
 *
 * Columnar layout (agent → calls → evidence → signals → response), hand-rolled SVG —
 * the same approach as the repo dashboard's graphView(). Every node is clickable and
 * expands to the full event payload; edges follow the evidence joins:
 *   call → pre-actuation via evidence_seq (never task_id, which collides),
 *   pre-actuation → result via task_id within this agent,
 *   call → IOC (per detected kind), IOC → hygiene response.
 */

interface GNode {
  id: string;
  col: number;
  label: string;
  sub: string;
  tone?: string;                 // css color var
  evt?: ConsoleEvent;
}

const COLS = ["Agent", "Calls", "Evidence", "Signals", "Response"];
const MAX_CALLS = 50;

export default function AgentGraph({ agent, events }: { agent: string; events: ConsoleEvent[] }) {
  const [sel, setSel] = useState<string | null>(null);

  const { nodes, edges } = useMemo(() => {
    const nodes: GNode[] = [{ id: "agent", col: 0, label: agent, sub: "identity", tone: "var(--accent)" }];
    const edges: [string, string][] = [];

    const calls = events.filter((e) => e.kind === "call").slice(-MAX_CALLS);
    const records = events.filter((e) => e.kind !== "call" && e.kind !== "feed-health");
    const preBySeq = new Map<number, ConsoleEvent>();
    const preByTask = new Map<string, string>();

    for (const r of records) {
      const id = `rec-${r.id}`;
      const deny = r.kind === "hygiene";
      if (r.kind === "hygiene") continue;              // hygiene rendered in Response column
      nodes.push({
        id, col: 2, label: `${r.kind}${r.seq != null ? ` #${r.seq}` : ""}`,
        sub: String(r.data["tool"] ?? r.data["task_id"] ?? ""), evt: r,
        tone: deny ? "var(--critical)" : undefined,
      });
      if (r.kind === "pre-actuation" && r.seq != null) preBySeq.set(r.seq, r);
      if (r.kind === "pre-actuation" && r.data["task_id"]) preByTask.set(String(r.data["task_id"]), id);
      if (r.kind === "result" && r.data["task_id"] && preByTask.has(String(r.data["task_id"]))) {
        edges.push([preByTask.get(String(r.data["task_id"]))!, id]);
      } else if (r.kind === "birth" || r.kind === "mode") {
        edges.push(["agent", id]);
      }
    }

    let iocN = 0;
    const iocIds: string[] = [];
    for (const c of calls) {
      const id = `call-${c.id}`;
      const allowed = c.data["allowed"] === true;
      nodes.push({
        id, col: 1,
        label: `${String(c.data["tool"] ?? "?")}`,
        sub: String(c.data["decision"] ?? (allowed ? "allow" : "deny")),
        tone: allowed ? undefined : "var(--critical)", evt: c,
      });
      edges.push(["agent", id]);
      const seq = c.data["evidence_seq"];
      if (typeof seq === "number" && preBySeq.has(seq)) edges.push([id, `rec-${preBySeq.get(seq)!.id}`]);
      for (const k of (c.data["iocs"] as string[] | undefined) ?? []) {
        const iid = `ioc-${c.id}-${iocN++}`;
        nodes.push({ id: iid, col: 3, label: k, sub: "IOC", tone: "var(--warn)", evt: c });
        edges.push([id, iid]);
        iocIds.push(iid);
      }
    }

    for (const h of events.filter((e) => e.kind === "hygiene")) {
      const id = `hyg-${h.id}`;
      nodes.push({
        id, col: 4, label: `Tier ${String(h.data["tier"] ?? "?")}`,
        sub: String(h.data["tier_name"] ?? "response"), tone: "var(--critical)", evt: h,
      });
      if (iocIds.length) edges.push([iocIds[iocIds.length - 1], id]);
      else edges.push(["agent", id]);
    }
    return { nodes, edges };
  }, [agent, events]);

  // columnar layout
  const W = 1100, NW = 150, NH = 40, padY = 46;
  const byCol = COLS.map((_, i) => nodes.filter((n) => n.col === i));
  const H = Math.max(360, padY * 2 + Math.max(...byCol.map((c) => c.length)) * (NH + 14));
  const pos = new Map<string, { x: number; y: number }>();
  byCol.forEach((list, ci) => {
    const x = 40 + ci * ((W - 80 - NW) / (COLS.length - 1));
    list.forEach((n, i) => pos.set(n.id, { x, y: padY + 18 + i * ((H - padY * 2) / Math.max(list.length, 1)) }));
  });

  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const [a, b] of edges) {
      if (!m.has(a)) m.set(a, new Set());
      if (!m.has(b)) m.set(b, new Set());
      m.get(a)!.add(b);
      m.get(b)!.add(a);
    }
    return m;
  }, [edges]);

  const selEvt = nodes.find((n) => n.id === sel)?.evt;

  return (
    <div>
      <div className="graphwrap">
        <svg viewBox={`0 0 ${W} ${H}`}>
          {COLS.map((c, i) => (
            <text key={c} className="glabel" x={40 + i * ((W - 80 - NW) / (COLS.length - 1))} y={22}>{c}</text>
          ))}
          {edges.map(([a, b], i) => {
            const pa = pos.get(a), pb = pos.get(b);
            if (!pa || !pb) return null;
            const x1 = pa.x + NW, y1 = pa.y + NH / 2, x2 = pb.x, y2 = pb.y + NH / 2;
            const mx = (x1 + x2) / 2;
            const hl = sel != null && (a === sel || b === sel);
            return <path key={i} className={`gedge${hl ? " hl" : ""}`}
              d={`M ${x1},${y1} C ${mx},${y1} ${mx},${y2} ${x2},${y2}`} />;
          })}
          {nodes.map((n) => {
            const p = pos.get(n.id)!;
            const dim = sel != null && n.id !== sel && !(neighbors.get(sel)?.has(n.id) ?? false);
            return (
              <g key={n.id} className={`gnode${sel === n.id ? " sel" : ""}`}
                transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.35 : 1}
                onClick={() => setSel(sel === n.id ? null : n.id)}>
                <rect width={NW} height={NH} rx={6}
                  style={n.tone ? { stroke: n.tone } : undefined} />
                <text x={10} y={17} style={n.tone ? { fill: n.tone } : undefined}>
                  {n.label.length > 20 ? n.label.slice(0, 19) + "…" : n.label}
                </text>
                <text x={10} y={31} className="sub">
                  {n.sub.length > 22 ? n.sub.slice(0, 21) + "…" : n.sub}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {selEvt && (
        <div className="card" style={{ marginTop: 12 }}>
          <b className="mono">{selEvt.kind}</b>{" "}
          <span className="mut">seq={String(selEvt.seq ?? "–")} · t={String(selEvt.t ?? "–")} · event #{selEvt.id}</span>
          <div className="payload">{JSON.stringify(selEvt.data, null, 2)}</div>
        </div>
      )}
      {!selEvt && <p className="mut" style={{ fontSize: 12.5, marginTop: 8 }}>
        Click any node to inspect its full payload; connected nodes stay lit.</p>}
    </div>
  );
}
