"""
C12 Governance Console copilot -- Claude DRAFTS human-facing artifacts from evidence.

The lowest-risk Claude role: it READS the hash-chained evidence and drafts an incident
summary or the justification package an autonomous (isolated-mode) decision requires --
for a human to review and sign off. It is used honestly:

  * READS-ONLY. It gates nothing, decides nothing, adjudicates nothing. "The ledger has
    it" is provenance, not adjudication (spec 10.8) -- the human adjudicates; the copilot
    only assembles the record into prose and flags what is unresolved.
  * Every draft is grounded in cited record seqs; the fact that a draft was produced is
    itself recorded as an advisory `governance-note` (provenance), never as a decision.

Offline by default (transport-injectable; nothing imports `anthropic` at load).
"""
from __future__ import annotations

import json

from aata.scenario import Estate

CONSOLE_MODEL = "claude-sonnet-5"   # good balance for evidence summarization

_INCIDENT_KINDS = ("birth", "pre-actuation", "result", "hygiene", "judge", "task-outcome")

_SYSTEM = (
    "You are the Governance Console copilot (C12) for the AATA autonomous-agent trust "
    "overlay. You are given hash-chained evidence records about one agent. DRAFT a concise, "
    "factual, human-facing {kind} for an operator to review and SIGN OFF. Rules: ground "
    "every statement in the evidence and cite the record seq (e.g. 'seq 7'); do not invent "
    "facts not in the evidence; explicitly flag anything unresolved or ambiguous; state what "
    "a human still needs to decide. You do NOT make or approve decisions -- 'the ledger has "
    "it' is provenance, not adjudication (spec 10.8). End with a one-line 'For human "
    "sign-off:' item."
)


def _anthropic_transport(model, system, messages):
    import anthropic  # lazy
    client = anthropic.Anthropic()
    return client.messages.create(model=model, max_tokens=2048,
                                  system=system, messages=messages)


def _text_of(resp) -> str:
    out = []
    for b in getattr(resp, "content", []) or []:
        if getattr(b, "type", None) == "text" or (isinstance(b, dict) and b.get("type") == "text"):
            out.append(getattr(b, "text", None) or (b.get("text", "") if isinstance(b, dict) else ""))
    return "".join(out)


class GovernanceConsole:
    def __init__(self, estate: Estate, model: str = CONSOLE_MODEL, transport=None):
        self.estate = estate
        self.model = model
        self._transport = transport or _anthropic_transport

    # -- evidence gathering (reads-only) ------------------------------------
    def gather(self, agent_id: str) -> list[dict]:
        """All chain records that reference the agent, in order (auth + ledger)."""
        recs = self.estate.authoritative.records + self.estate.ddil.ledger.records
        out = []
        for r in recs:
            if r.kind in _INCIDENT_KINDS and r.payload.get("agent") == agent_id:
                out.append({"seq": r.seq, "kind": r.kind, "hash": r.this_hash[:12],
                            "payload": r.payload})
        return sorted(out, key=lambda d: d["seq"])

    def _evidence_block(self, records: list[dict]) -> str:
        lines = []
        for r in records:
            lines.append(f"[seq {r['seq']} · {r['kind']} · {r['hash']}] "
                         + json.dumps(r["payload"], sort_keys=True)[:600])
        return "\n".join(lines) or "(no evidence records for this agent)"

    def _draft(self, agent_id: str, kind: str) -> str:
        records = self.gather(agent_id)
        system = _SYSTEM.replace("{kind}", kind)
        merkle = self.estate.authoritative.merkle_root()
        user = (
            f"Agent: {agent_id}\n"
            f"Evidence merkle root: {merkle}\n"
            "Note: these records are FILTERED to this agent, so record seqs are naturally "
            "non-contiguous (missing seqs belong to other agents, not chain gaps).\n"
            f"Records ({len(records)}):\n{self._evidence_block(records)}\n\n"
            f"Draft the {kind}."
        )
        resp = self._transport(self.model, system, [{"role": "user", "content": user}])
        draft = _text_of(resp).strip()
        # record that a draft was produced -- provenance, NOT a decision
        self.estate.ddil.active_recorder.append("governance-note", {
            "agent": agent_id, "note_type": kind, "model": self.model,
            "evidence_records": [r["seq"] for r in records], "chars": len(draft),
            "note": "advisory human-facing draft (C12); provenance, not adjudication (10.8)",
        })
        return draft

    # -- public: the two artifacts ------------------------------------------
    def incident_summary(self, agent_id: str) -> str:
        """A concise incident summary for an operator to review."""
        return self._draft(agent_id, "incident summary")

    def justification_package(self, agent_id: str) -> str:
        """The justification an autonomous (isolated-mode) decision requires (W4)."""
        return self._draft(agent_id, "justification package for the autonomous decision")
