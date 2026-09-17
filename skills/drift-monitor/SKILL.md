---
name: drift-monitor
description: Scheduled cheap health probes of the system under maintenance, producing a verdict table and flagging chronic problem areas. Use on a schedule, not per-PR.
---

# Drift monitoring

Maintenance becomes continuous: probe often, report honestly, let a human decide.

## Steps

1. For each monitored unit, run the **cheapest possible probe** that still touches reality (one read, one action, one verification — not the full pipeline).
2. Record a verdict per unit: `ok | degraded | broken`, with one line of evidence.
3. Post/refresh the verdict table on the tracking issue. Keep history visible — a unit that has been `broken` repeatedly across runs is a **chronic** candidate.
4. Chronic units: flag for the maintainer with a one-line recommendation (fix vs remove), with the evidence linked. Never act unilaterally.
5. New breakage: open an issue with the evidence, **without** any trigger label — triage and the decision to build are human steps.

## Rules

- The monitor never fixes. It observes and files. Fixing goes through the normal spec → build → verify → review loop.
- A probe that can't run is `broken` with the error, not silently skipped.
