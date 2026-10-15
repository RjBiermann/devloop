#!/usr/bin/env python3
"""Mechanical conveyor for the gh-aw pipeline (ADR-0008, amended 2026-10-15).

Non-AI, fails closed. Automates the mechanics of an already-approved chain
and surfaces every real decision as an @mention. It never decides a round,
never merges a PR, never touches ai-* trigger labels, and closes [aw]
diagnostics only when a later Implement/Plan run has succeeded.

  - approve companion (non-AI) runs stuck in `action_required` on
    devloop/* PR branches (needs GH_AW_PROXY_PAT; warns + no-ops if unset)
  - merge readiness: default contract is HUMAN MERGES — label
    `status/ready-to-merge` + ping the owner with the head sha. If the
    adopter sets GH_AW_AUTO_MERGE=true, queue auto-merge instead
    (branch protection remains the real gate either way).
  - chain driver: stamp `status/planned` on story N when story N-1's
    sub-issue closed; stamp story 1 from the chain's round-3 approval;
    close the parent spec issue once every story is closed.
  - plan-loop surrogate: fire `/plan` mechanically across rounds
    (fresh ai-* -> round 1; human answers after round 1 -> round 2;
    owner 'approved' after round 2 -> round 3). Each firing carries a
    per-round dedupe marker so it never loops.
  - decision tags: when a round is waiting on the human, one
    "@owner decision needed" note per round (deduped).
  - watchdog: close transient [aw] diagnostics after a LATER successful
    Implement/Plan run exists.
"""

import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("GITHUB_REPOSITORY", "")
PROXY_PAT = os.environ.get("GH_AW_PROXY_PAT", "")
AUTO_MERGE = os.environ.get("GH_AW_AUTO_MERGE", "false") == "true"
FIRE_PLAN = os.environ.get("GH_AW_ORCH_PLAN", "true") == "true"
TAG_OWNER = os.environ.get("GH_AW_ORCH_TAG_OWNER", "true") == "true"
OWNER = os.environ.get("GH_AW_ORCH_OWNER", "RjBiermann")

MARK = "[orchestrator]"
STORY_RE = re.compile(r"\[spec\]\s*(?:Story\s+|S)(\d+)", re.I)
PARENT_RE = re.compile(r"approved\s+#(\d+)\s+spec", re.I)
ROUND_ANCH = {r: f"Plan round {r} —" for r in (1, 2, 3)}

APPROVE_ALLOWLIST = [
    "99-ci", "Lint", "CodeQL Advanced", "CodeQL",
    "Security scan (08+09 merged)",
    "Automatic Dependency Submission (Gradle)",
]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(f"[orchestrator] rc={r.returncode} on {' '.join(cmd[:5])}: {r.stderr.strip()[:300]}\n")
    return r.stdout


def api(path):
    out = run(["gh", "api", f"repos/{REPO}/{path}"])
    if not out.strip():
        return None
    return json.loads(out)


def comments(num):
    return api(f"issues/{num}/comments?per_page=100") or []


def post_comment(num, body):
    run(["gh", "api", "-X", "POST", f"repos/{REPO}/issues/{num}/comments", "-f", f"body={body}"])


def label_issue(num, name):
    run(["gh", "issue", "edit", str(num), "--add-label", name])


def close_issue(num, reason, body):
    run(["gh", "issue", "close", str(num), "--reason", reason, "-c", body])


def open_pulls():
    return api("pulls?state=open&per_page=50") or []


def story_num(title):
    m = STORY_RE.search(title or "")
    return int(m.group(1)) if m else None


def all_stories():
    out = run(["gh", "issue", "list", "--state", "all", "--limit", "100",
               "--json", "number,title,state,body,labels"])
    if not out.strip():
        return []
    raw = json.loads(out)
    return [i for i in raw if i.get("pull_request") is None and story_num(i.get("title", ""))]


def parent_of(story):
    m = PARENT_RE.search(story.get("body") or "")
    return int(m.group(1)) if m else None


def _round_comment(cs, rnd):
    hit = None
    for c in cs or []:
        if ROUND_ANCH[rnd] in (c.get("body") or ""):
            hit = c
    return hit


def _has_marker(cs, text):
    return any(text in (c.get("body") or "") for c in cs or [])


# --------------------------------------------------------------- approvals
def approve_companion_runs():
    if not PROXY_PAT:
        print("[orchestrator] GH_AW_PROXY_PAT unset — approvals stay manual")
        return
    for pr in open_pulls():
        branch = pr.get("head", {}).get("ref", "")
        if not branch.startswith("devloop/"):
            continue
        runs = run(["gh", "run", "list", "--branch", branch, "--limit", "40",
                    "--json", "databaseId,workflowName,conclusion",
                    "--jq", '.[] | select(.conclusion=="action_required") | "\(.databaseId)|\(.workflowName)"'])
        for line in runs.splitlines():
            if not line.strip():
                continue
            rid, _, wname = line.partition("|")
            if wname in APPROVE_ALLOWLIST:
                out = run(["curl", "-s", "-X", "POST",
                           "-H", f"Authorization: Bearer {PROXY_PAT}",
                           "-H", "Accept: application/vnd.github+json",
                           f"https://api.github.com/repos/{REPO}/actions/runs/{rid}/approve"])
                print(f"[orchestrator] approve {rid} ({wname}): {out[:90]}")
            else:
                print(f"[orchestrator] run {rid} ({wname}) outside allowlist — left for human")


# ---------------------------------------------------------- merge readiness
def merge_readiness():
    for pr in open_pulls():
        num = pr["number"]
        branch = pr.get("head", {}).get("ref", "")
        if pr.get("draft") or not branch.startswith("devloop/issue-"):
            continue
        d = api(f"pulls/{num}") or {}
        mstate = d.get("mergeable_state")
        if mstate != "clean":
            print(f"[orchestrator] PR #{num}: mergeable_state={mstate} — not ready")
            continue
        if AUTO_MERGE:
            run(["gh", "pr", "merge", str(num), "--squash", "--auto"])
            print(f"[orchestrator] PR #{num}: auto-merge queued")
            continue
        sha = ((d.get("head") or {}).get("sha") or "")[:12]
        marker = f"ready @{OWNER} — all required checks green at `{sha}`"
        if _has_marker(comments(num), marker):
            continue
        label_issue(num, "status/ready-to-merge")
        post_comment(num, f"{MARK} ready @{OWNER} — all required checks green at `{sha}`; please review and merge when ready.")
        print(f"[orchestrator] PR #{num}: tagged {OWNER} for merge")


# ------------------------------------------------------------- chain driver
def chain_driver():
    stories = all_stories()
    for s in stories:
        if s["state"] != "open":
            continue
        num_story = story_num(s["title"])
        labels = [l["name"] for l in s.get("labels", [])]
        if "status/planned" in labels:
            continue
        if num_story == 1:
            pnum = parent_of(s)
            approved = pnum and _chain_approved(pnum)
            if approved:
                label_issue(s["number"], "status/planned")
                print(f"[orchestrator] story 1 (issue {s['number']}): trigger stamped (chain approved at round 3)")
            else:
                print(f"[orchestrator] story 1 (issue {s['number']}): no round-3 approval recorded — waiting on human")
            continue
        pstate = _story_state(num_story - 1, stories)
        if pstate in ("closed", "CLOSED"):
            label_issue(s["number"], "status/planned")
            print(f"[orchestrator] story {num_story} (issue {s['number']}): trigger stamped (story {num_story-1} closed)")
        else:
            print(f"[orchestrator] story {num_story} (issue {s['number']}): predecessor still {pstate}")

    # Parent spec issue: close once every story referencing it is closed.
    by_parent = {}
    for s in stories:
        p = parent_of(s)
        if p:
            by_parent.setdefault(p, []).append(s)
    for pid, kids in by_parent.items():
        p = api(f"issues/{pid}")
        if not p or p.get("state") != "open":
            continue
        if all(k["state"] in ("closed", "CLOSED") for k in kids):
            c = comments(pid)
            if not _has_marker(c, "all stories of this approved chain are closed"):
                close_issue(pid, "completed",
                            "Orchestrator (ADR-0008): all stories of this approved chain are closed (merged PRs). Closing the parent.")
                print(f"[orchestrator] parent #{pid}: closed ({len(kids)} stories complete)")


def _chain_approved(pnum):
    for c in comments(pnum):
        if c.get("user", {}).get("login") == OWNER and \
                (c.get("body") or "").strip().lower() in ("approved", "approve", "lgtm", "yes", "ok"):
            return True
    return False


def _story_state(num, stories):
    for s in stories:
        if story_num(s.get("title", "")) == num:
            return s.get("state", "?")
    return "-"


# ------------------------------------------------- plan-loop surrogate (/plan)
def plan_loop_surrogate():
    if not FIRE_PLAN:
        return
    issues = api("issues?state=open&per_page=50") or []
    triggers = ("ai-fix", "ai-build", "ai-remove", "ai-new-site")
    for i in issues:
        if i.get("pull_request"):
            continue
        n = i["number"]
        labels = [l["name"] for l in i.get("labels", [])]
        cs = comments(n)
        r1, r2, r3 = (_round_comment(cs, k) for k in (1, 2, 3))
        kid_stories = [s for s in all_stories() if parent_of(s) == n]

        fresh_trigger = any(l in triggers for l in labels)
        if fresh_trigger and not r1:
            mk = f"{MARK} /plan fired round 1"
            if not _has_marker(cs, mk):
                post_comment(n, mk + " (fresh trigger label; ADR-0008 surrogate)")
                print(f"[orchestrator] {n}: /plan round 1 fired")
            continue
        if not r1:
            continue
        # round 2: human answered after round 1
        if not r2 and not kid_stories:
            if not _has_marker(cs, f"{MARK} /plan fired round 2"):
                human_after = [c for c in cs if c.get("user", {}).get("login") == OWNER and c["created_at"] > r1["created_at"]]
                if human_after:
                    post_comment(n, f"{MARK} /plan fired round 2 (round-1 answers received; ADR-0008 surrogate)")
                    print(f"[orchestrator] {n}: /plan round 2 fired")
        # round 3: owner approved after round 2
        if r2 and not kid_stories and not r3:
            if not _has_marker(cs, f"{MARK} /plan fired round 3"):
                appr = [c for c in cs if c.get("user", {}).get("login") == OWNER
                        and c["created_at"] > r2["created_at"]
                        and (c.get("body") or "").strip().lower() in ("approved", "approve", "lgtm", "yes", "ok")]
                if appr:
                    post_comment(n, f"{MARK} /plan fired round 3 (finalize; round-2 approved; ADR-0008 surrogate)")
                    print(f"[orchestrator] {n}: /plan round 3 fired")


# -------------------------------------------------------- decision tags
def decision_tags():
    if not TAG_OWNER:
        return
    openi = api("issues?state=open&per_page=50") or []
    for i in openi:
        if i.get("pull_request"):
            continue
        n = i["number"]
        cs = comments(n)
        for rnd in (1, 2):
            r = _round_comment(cs, rnd)
            if not r:
                continue
            awaiting = _round_waiting_on(r)
            if not awaiting:
                continue
            if any(MARK in (c.get("body") or "") and c["created_at"] >= r["created_at"] for c in cs):
                continue
            post_comment(n, f"{MARK} decision needed @{OWNER} — plan round {rnd} is waiting on you ({awaiting}).")
            print(f"[orchestrator] {n}: tagged owner for round {rnd}")


def _round_waiting_on(round_comment):
    b = (round_comment.get("body") or "").lower()
    if "clarify" in b:
        return "answers to the clarifier questions"
    if "spec confirmed" in b or "breakdown" in b:
        return "reply `approved` to finalize the spec, or corrections"
    return None


# -------------------------------------------------------- transient watchdog
def watchdog():
    openi = api("issues?state=open&per_page=50") or []
    ml = []
    for i in openi:
        t = i.get("title", "")
        if i.get("pull_request"):
            continue
        if t.startswith("[aw]") and ("no safe outputs" in t or "reported incomplete" in t):
            ml.append((i["number"], i.get("created_at", "")))
    if not ml:
        return
    later = run(["gh", "run", "list", "--limit", "50", "--json", "name,conclusion,createdAt",
                 "--jq", '.[] | select((.conclusion=="success") and ((.name|contains("Implement")) or (.name|contains("Plan")))) | .createdAt']).splitlines()
    for num, created in ml:
        if any(t > created for t in later if t.strip()):
            close_issue(num, "not planned",
                        "Transient-class `[aw]` signal: at least one later Implement/Plan run succeeded after this diagnostic's timestamp (orchestrator watchdog, ADR-0008). If the underlying work is still missing, reopen with the specific evidence.")
            print(f"[orchestrator] closed transient diag #{num}")


if __name__ == "__main__":
    steps = {
        "approvals": approve_companion_runs,
        "merge_readiness": merge_readiness,
        "chain_driver": chain_driver,
        "plan_surrogate": plan_loop_surrogate,
        "decision_tags": decision_tags,
        "watchdog": watchdog,
    }
    only = [a for a in sys.argv[1:] if a in steps]
    for name, fn in steps.items():
        if only and name not in only:
            continue
        try:
            fn()
        except Exception as e:
            sys.stderr.write(f"[orchestrator] {name} failed: {e}\n")
    print("[orchestrator] done")
