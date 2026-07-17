import type { Posture } from "@/lib/types";

export default function PosturePill({ posture }: { posture: Posture }) {
  return (
    <span className={`pill st-${posture}`}>
      <span className="dot" />
      {posture}
    </span>
  );
}

export function AssuranceBadge({ assurance }: { assurance: string }) {
  const crypto = assurance === "crypto-attested";
  return (
    <span className={`assure${crypto ? " crypto" : ""}`}
      title={crypto
        ? "Birth carried a real SPIFFE ID + cosign-verified artifact digests."
        : "Enrolled without a cryptographic root — weaker assurance, shown, not hidden."}>
      {assurance}
    </span>
  );
}
