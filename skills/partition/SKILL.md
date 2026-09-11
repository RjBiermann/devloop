---
name: partition
description: Design the task tree so concurrent work never conflicts — every story gets a touch-set, overlapping stories get merged or sequenced. Use during decompose before creating sub-issues.
---

# Partition

Merge conflicts are a spec bug, not a git problem. Two stories that edit the
same file were not decomposed correctly — they are one story or a sequence.

## Steps

1. Before creating any issue, sketch the **touch-set** of each story: the
   files/dirs/modules it will realistically change.
2. **Disjoint or merged.** If two stories share a touch path:
   - if the shared file is small and the stories are small → merge into one
     story (cheapest fix; a bigger PR beats two conflicted ones)
   - if they are genuinely independent → give each an explicit order
     dependency in its body (`Depends on #N — shares <path>`) so the
     orchestrator serializes them instead of racing
3. **Contention zones get one owner.** Shared plumbing (framework hooks,
   shared modules, shared config, a central registry) is assigned to exactly
   one story. Everyone else consumes it, nobody else edits it.
4. Write `Touch-set:` into every story issue body — the orchestrator uses
   this to serialize overlapping work even when humans apply trigger labels
   out of order.
5. The partition is part of the proposal the human approves. A review of the
   breakdown is implicitly a review of the conflict plan.

## Rules

- Parallelism is a throughput knob, never a correctness assumption. Correct
  is: no two in-flight PRs touch the same path. Fast is: more stories
  in-flight with disjoint touch-sets.
- Never resolve a partition problem by hoping git merges cleanly — textual
  merge success with semantic conflict (two stories changing one behavior
  from two sides) is worse than a textual conflict because it passes the
  gate and breaks later.
- Touch-sets are estimates and may be wrong. When a build discovers it must
  edit outside its declared touch-set, it comments on its issue with the
  expanded touch-set and finishes — the queue, not the agent, decides
  whether to wait.
