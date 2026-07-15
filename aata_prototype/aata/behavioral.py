"""
C11 -- Behavioral Analytics (BUILD component; agent-native UEBA).
Control: AATA-OB-03.

Production tooling: stream processing (Flink/Faust) over the C8 bus;
embedding-space baselines per agent role; fleet-level distribution drift over
tool-use, token economics, and delegation graphs.

Role in W3 (step 2): CORROBORATION. The covert-channel monitor (C10) flags an
IOC; behavioral analytics independently corroborates via delegation-graph and
token-economics drift. Two independent signals reduce false-positive quarantines.

This prototype tracks, per agent:
  * tool-use distribution         (are they calling tools they never called?)
  * token economics / spend rate  (sudden spend spike?)
  * delegation fan-out            (spawning more sub-agents than baseline?)

Honest limitation (spec 10.3): baselining assumes stationarity agents lack.
A patient adversary shapes the baseline before acting; in Isolated mode the
baseline drifts self-referentially with no external ground truth. `warmup`
models the window an adversary could poison.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Baseline:
    calls: int = 0
    tools_seen: set[str] = field(default_factory=set)
    total_spend: int = 0
    delegations: int = 0

    @property
    def mean_spend(self) -> float:
        return self.total_spend / self.calls if self.calls else 0.0


@dataclass
class DriftSignal:
    agent_id: str
    score: float             # 0..1, higher = more anomalous
    reasons: list[str] = field(default_factory=list)

    @property
    def corroborates(self) -> bool:
        return self.score >= 0.5


class BehavioralAnalytics:
    def __init__(self, warmup: int = 3, spend_spike: float = 3.0):
        self.warmup = warmup
        self.spend_spike = spend_spike
        self._base: dict[str, Baseline] = defaultdict(Baseline)

    def observe_call(self, agent_id: str, tool: str, cost: int) -> DriftSignal:
        b = self._base[agent_id]
        reasons: list[str] = []
        score = 0.0
        if b.calls >= self.warmup:
            if tool not in b.tools_seen:
                score += 0.35
                reasons.append(f"first-ever use of tool '{tool}'")
            if b.mean_spend > 0 and cost > self.spend_spike * b.mean_spend:
                score += 0.4
                reasons.append(
                    f"spend {cost} > {self.spend_spike}x baseline mean {b.mean_spend:.1f}")
        # update baseline AFTER scoring
        b.calls += 1
        b.tools_seen.add(tool)
        b.total_spend += cost
        return DriftSignal(agent_id, min(1.0, score), reasons)

    def observe_delegation(self, agent_id: str, fanout_limit: int = 4) -> DriftSignal:
        b = self._base[agent_id]
        b.delegations += 1
        if b.delegations > fanout_limit:
            return DriftSignal(agent_id, 0.6,
                               [f"delegation fan-out {b.delegations} > {fanout_limit}"])
        return DriftSignal(agent_id, 0.0)


# ===========================================================================
# Fleet-level analytics (C11 / AATA-OB-03) -- the layer that only exists at scale
# ===========================================================================

@dataclass
class CohortOutlier:
    agent_id: str
    cohort: str               # "<type>/<variant>"
    metric: str               # "spend" | "tool_diversity" | ...
    value: float
    cohort_median: float
    mad_score: float          # robust z-score (deviation / MAD)
    reason: str


@dataclass
class MonocultureAlarm:
    cohort: str
    variant: str
    n_agents: int
    n_drifting: int
    reason: str


class FleetAnalytics:
    """
    Fleet-level distribution drift + monoculture detection across a heterogeneous
    fleet. Two things per-agent baselining (BehavioralAnalytics) structurally
    cannot catch:

      1. COHORT OUTLIER -- an agent that looks fine against its OWN (possibly
         adversary-poisoned) baseline but is anomalous versus its role/variant
         peers. Uses a robust median + MAD, so a few poisoned members don't move
         the reference. Directly attacks the spec-10.3 self-reference gap.

      2. MONOCULTURE / CORRELATED DRIFT -- when >= k agents that share a build
         variant drift the SAME way at once, that is a shared-exploit signature,
         not independent noise. This is the P7 case, and the reason quorum/BFT
         schemes fail here (spec 10.4): correlated faults break the independence
         assumption. Acute for the 50 identical rovers / 50 identical vehicles.

    Feeds the hygiene orchestrator: a monoculture alarm triggers a blast-radius
    cap (freeze the affected rollout ring / variant) rather than treating each
    agent as an isolated incident.
    """

    def __init__(self, mad_k: float = 3.5, monoculture_frac: float = 0.4,
                 monoculture_min: int = 3):
        self.mad_k = mad_k                      # robust-z threshold for outlier
        self.monoculture_frac = monoculture_frac
        self.monoculture_min = monoculture_min
        # cohort -> { agent_id -> {spend_total, calls, tools:set} }
        self._cohort: dict[str, dict[str, dict]] = {}
        self._agent_cohort: dict[str, str] = {}

    def register(self, agent_id: str, type_id: str, variant: str) -> None:
        cohort = f"{type_id}/{variant}"
        self._agent_cohort[agent_id] = cohort
        self._cohort.setdefault(cohort, {})[agent_id] = {
            "spend_total": 0, "calls": 0, "tools": set()}

    def observe(self, agent_id: str, tool: str, cost: int) -> None:
        cohort = self._agent_cohort.get(agent_id)
        if cohort is None:
            return
        rec = self._cohort[cohort][agent_id]
        rec["spend_total"] += cost
        rec["calls"] += 1
        rec["tools"].add(tool)

    @staticmethod
    def _median(xs: list[float]) -> float:
        s = sorted(xs)
        n = len(s)
        if n == 0:
            return 0.0
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    def _mad(self, xs: list[float], med: float) -> float:
        devs = [abs(x - med) for x in xs]
        return self._median(devs) or 1.0     # avoid divide-by-zero

    def assess(self) -> tuple[list[CohortOutlier], list[MonocultureAlarm]]:
        """
        Two independent readouts:
          * cohort outlier -- robust-z of an agent's spend vs its OWN cohort median
            (catches a lone member drifting from peers).
          * monoculture alarm -- a whole build VARIANT elevated vs its SIBLING
            variant of the same type. Comparing variant-to-variant is robust even
            when ~half the variant is compromised (the within-cohort median is
            useless then -- swamping -- but the clean sibling variant is not).
        """
        outliers: list[CohortOutlier] = []
        alarms: list[MonocultureAlarm] = []
        seen: set[str] = set()

        # group cohorts by type: type -> variant -> {agent: spend}
        by_type: dict[str, dict[str, dict[str, int]]] = {}
        for cohort, agents in self._cohort.items():
            type_id, variant = cohort.split("/", 1)
            spends = {a: r["spend_total"] for a, r in agents.items() if r["calls"] > 0}
            if spends:
                by_type.setdefault(type_id, {})[variant] = spends

        for type_id, variants in by_type.items():
            # (a) within-cohort robust-z outliers
            for variant, spends in variants.items():
                ids = list(spends)
                if len(ids) < self.monoculture_min:
                    continue
                vals = [spends[a] for a in ids]
                med = self._median(vals)
                mad = self._mad(vals, med)
                for a in ids:
                    z = abs(spends[a] - med) / mad
                    if z >= self.mad_k and spends[a] > med and a not in seen:
                        seen.add(a)
                        outliers.append(CohortOutlier(
                            a, f"{type_id}/{variant}", "spend", spends[a], med,
                            round(z, 2),
                            f"spend {spends[a]} is {z:.1f}x MAD above cohort median {med}"))

            # (b) monoculture: one variant elevated vs its sibling variant baseline
            if len(variants) >= 2:
                medians = {vr: self._median(list(s.values())) for vr, s in variants.items()}
                baseline = min(medians.values()) or 1.0
                for vr, spends in variants.items():
                    if medians[vr] < 1.5 * baseline:
                        continue
                    elevated = [a for a, s in spends.items() if s >= 1.8 * baseline]
                    need = max(self.monoculture_min, int(self.monoculture_frac * len(spends)))
                    if len(elevated) >= need:
                        alarms.append(MonocultureAlarm(
                            cohort=f"{type_id}/{vr}", variant=vr, n_agents=len(spends),
                            n_drifting=len(elevated),
                            reason=f"{len(elevated)}/{len(spends)} of variant '{vr}' "
                                   f"({type_id}) elevated {medians[vr]/baseline:.1f}x vs "
                                   f"sibling variant -- correlated (shared-exploit) signature"))
                        for a in elevated:
                            if a not in seen:
                                seen.add(a)
                                outliers.append(CohortOutlier(
                                    a, f"{type_id}/{vr}", "spend", spends[a], baseline,
                                    round(spends[a] / baseline, 2),
                                    f"elevated {spends[a]/baseline:.1f}x vs sibling-variant baseline"))
        return outliers, alarms
