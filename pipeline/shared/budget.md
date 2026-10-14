# Budget stamps (Ledger protocol — imported by agent workflows)

The attempt budget lives in the issue comment history, not in any state
store. A **budget stamp** is a comment whose body **begins** with:

```
gh-aw budget: attempt=N kind=<fix|new|remove|review|repair|spec> run=<url or id> credits=<n>
```

Rules (ported from `devloop/ledger.py`):

- **Producers only**: an agent workflow posts a stamp via `add-comment`
  whenever it completes a work attempt (build, review round, repair
  cycle) or observes a reset.
- **Reset**: a human `/retry` posts `gh-aw budget: reset` — stamped
  resets clear the attempt count for that issue.
- **Parsers only count stamped comments**: lines beginning
  `gh-aw budget:` are protocol; everything else on the timeline is
  prose that can never move an attempt budget. The sweeper's parser
  counts stamps back out of the history — `max_attempts` (default 3)
  and the daily cap read the same scan.
- **Never edit or reformat** an existing stamp; only append.
- When posting results, always close your turn with a stamp if your
  workflow's body instructs it (attempt-bearing work only — narration
  comments carry no stamps).
