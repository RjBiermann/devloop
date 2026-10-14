#!/usr/bin/env bash
# Taxonomy bootstrap (Plan A5). Idempotent; gh label create exits 1 on
# existing labels — `|| true` absorbs that once, after verifying the label
# exists (`gh label list | grep`) when GH_LABEL_STRICT is set.
set -u
mk() { # mk <name> <color> <description>
  gh label create "$1" --color "$2" --description "$3" 2>/dev/null \
    || gh label edit "$1" --color "$2" --description "$3" >/dev/null
}

# Family 1 — trigger labels: human-only, reserved `ai-` prefix (ADR-0003).
mk "ai-fix"    "D92438" "Trigger: agent fixes something broken (human-only)"
mk "ai-build"  "1D76DB" "Trigger: agent builds new work (human-only)"
mk "ai-remove" "B60205" "Trigger: agent removes something, evidence first (human-only)"

# Family 2 — state machine: agents may transition, except status/planned.
mk "status/queued"         "0E8A16" "Specified, waiting for triage"
mk "status/planned"        "006B75" "Spec finalized; implement may start (human-only label)"
mk "status/in-review"      "BFD4F2" "PR open; review loop engaged"
mk "status/fixing"         "FBCA04" "Repair acting on review findings"
mk "status/fixing-stuck"   "D93F0B" "Fix loop hit its cycle cap; needs human"
mk "status/ready-to-merge" "0E8A16" "Review clean + verify + security cleared; human clicks merge"

# Family 3 — intake provenance: agent-applicable, never starts a build.
mk "triage/from-agent" "C2E0C6" "Tagged by an agent during triage (provenance only)"

# Security family (08-security-scan).
mk "security/blocked" "B60205" "Security scan found a blocker"
mk "security/flagged" "D4C5F9" "Security scan flagged for human review"

echo "labels: taxonomy synced."
