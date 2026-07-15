# AATA C6 -- Constitutional policy bundle (production form).
#
# The prototype's aata/pdp.py is a compact stand-in for THIS. In a real
# deployment the C12 Governance Console's "constitutional compiler" emits a
# signed OPA bundle containing exactly this Rego, distributed with a TTL so it
# evaluates locally in Degraded/Isolated mode (no cloud callback).
#
# Load with:  opa eval -d constitution.rego -i input.json 'data.aata.decision'
#
# input schema (produced by the C1 gateway per call):
# {
#   "tool": "actuator_move",
#   "actuation_class": "kinetic",         # informational|reversible|financial|kinetic
#   "data_level": "public",               # public|internal|confidential|secret
#   "cost": 5,
#   "confidence": 0.9,
#   "threat_level": 2.0,                  # 0=connected .. raised in degraded/isolated
#   "capability_ok": true                 # C5 Biscuit verified upstream
# }

package aata

import future.keywords.if
import future.keywords.in

irreversible := {"financial", "kinetic"}

prohibited_tools := {"self_destruct"}

# Authored (connected-mode) confidence thresholds per actuation class.
base_threshold := {
	"informational": 0.0,
	"reversible": 0.3,
	"financial": 0.7,
	"kinetic": 0.8,
}

# Threat-posture tightening: irreversible classes need more confidence as
# connectivity is lost (the W4 "kinetic thresholds tighten" mechanic).
required_confidence(class) := t if {
	class in irreversible
	t := min([1.0, base_threshold[class] + 0.15 * input.threat_level])
}

required_confidence(class) := base_threshold[class] if {
	not class in irreversible
}

# --- deny rules (first match wins in spirit; any deny => deny) --------------

deny["capability insufficient (C5)"] if not input.capability_ok

deny[sprintf("tool %q constitutionally prohibited", [input.tool])] if {
	input.tool in prohibited_tools
}

deny[msg] if {
	input.confidence < required_confidence(input.actuation_class)
	msg := sprintf(
		"confidence %.2f < required %.2f for %q",
		[input.confidence, required_confidence(input.actuation_class), input.actuation_class],
	)
}

# --- fail-closed semantics for engine/bundle failure -----------------------
# (handled by the sidecar: if OPA is unreachable OR the bundle TTL expired,
#  the C1 gateway defaults DENY for classes in `irreversible`, ALLOW-degraded
#  otherwise. That control lives at the enforcement point, not in policy.)

default allow := false

allow if count(deny) == 0

decision := {
	"allow": allow,
	"deny_reasons": deny,
	"required_confidence": required_confidence(input.actuation_class),
	"fail_closed_class": input.actuation_class in irreversible,
}
