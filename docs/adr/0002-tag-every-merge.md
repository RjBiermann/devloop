# Tag every merge to master

Versions were hand-applied tags (`v0.1.8`…`v0.2.17`), so releases were
irregular and the tag vocabulary depended on whoever remembered to tag. We
decided every push to master gets exactly one tag: a GitHub Actions workflow
runs the same test matrix as ci.yml, then bumps the patch of the latest tag
(`minor:` in the head commit's subject opts into a minor bump) and pushes a
`chore: bump version` commit plus the tag. Majors stay fully manual.

The alternative — humans tagging deliberate release points — was rejected
because "Tag = release" already holds here, and an untagged merge is
indistinguishable from a forgotten tag. The cost we accept: versions count
merges, not significance, so tags can be trivial; significance lives in the
changelog and the merge message, which humans own. Tags are irreversible once
pushed, so the scheme is dumb on purpose: latest tag → +0.0.1, and a
pre-existing next tag fails the run loudly rather than being skipped.
