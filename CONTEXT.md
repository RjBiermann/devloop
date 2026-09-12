# Context

Domain vocabulary for devloop. Terms here are the words this project uses — don't drift to synonyms.

## Glossary

### Ledger

The issue comment history as state. Failure and reset comments on an issue are
a protocol, not prose: the attempt cap (`max_attempts`) counts them back out of
the comment history — no extra state anywhere. The **ledger module**
(`devloop/ledger.py`) owns this interface: producer functions (`failure`,
`reset`) and the parser (`count`). Marker strings are load-bearing for
comments already on live issues and never change — only append.

Related terms from AGENTS.md: trigger labels, `ready-for-human`, the
`devloop: status=` marker (the spec-loop counterpart of the ledger protocol).
