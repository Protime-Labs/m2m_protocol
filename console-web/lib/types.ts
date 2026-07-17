export type Posture =
  | "compliant" | "drifting" | "out-of-scope" | "quarantined" | "stale";

export interface PostureRow {
  src: string;
  agent: string;
  first_seen: string;
  birth: Record<string, unknown>;
  spiffe_id: string | null;
  allow_count: number;
  deny_count: number;
  ioc_count: number;
  hygiene_count: number;
  max_tier: number;
  record_count: number;
  last_ts: number | null;
  assurance: "crypto-attested" | "software-attested";
  posture: Posture;
}

export interface ConsoleEvent {
  id: number;
  src: string;
  agent: string | null;
  kind: string;
  seq: number | null;
  t: number | null;
  ts: number;
  data: Record<string, unknown>;
  created_at?: string;
}

export function ago(unixS: number | null): string {
  if (!unixS) return "–";
  const d = Date.now() / 1000 - unixS;
  if (d < 5) return "now";
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

export function liveness(row: PostureRow): "live" | "idle" | "offline" {
  if (!row.last_ts) return "offline";
  const d = Date.now() / 1000 - row.last_ts;
  if (d < 60) return "live";
  if (d < 300) return "idle";
  return "offline";
}
