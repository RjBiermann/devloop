---
# ADOPTER-OWNED FILE — this is the one fragment every adopting repo
# writes for itself (engine, model, secret lane, network). The pilot's
# lane (below) is one example, not the default. Sources in this pipeline
# never hardcode an engine; they import this file relatively.
#
# glm-5.3-flash on OpenCode Go speaks ONLY Chat Completions; gh-aw
# v0.89.21's sandboxed pi gateway forces Responses for the openai/ lane
# (confirmed by runtime 400 ModelProtocolUnsupported). Per gh-aw's own
# documented escape hatch, the agent sandbox is disabled for this lane
# (MCP gateway stays on) with a explicit per-workflow strict opt-out;
# every agent-level guardrail outside the firewall remains: read-only
# agent job, safe-output allow-lists, human-only labels/merge, on.roles.
engine:
  id: pi
  version: "1.1.0"
  model: openai/glm-5.3-flash
  env:
    # Validation-step alias: GenerateMultiSecretValidationStep validates
    # the user-supplied secret when engine.env overrides a credential key.
    CODEX_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
    OPENAI_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
pre-agent-steps:
  - name: Ship pi models.json (OpenCode Go lane - glm-5.3-flash, native)
    run: |
      DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
      mkdir -p "$DIR"
      cat > "$DIR/models.json" <<'JSON'
      {
        "providers": {
          "openai": {
            "baseUrl": "https://opencode.ai/zen/go/v1",
            "api": "openai-completions",
            "apiKey": "$OPENCODE_API_KEY",
            "models": [
              {
                "id": "glm-5.3-flash",
                "name": "GLM-5.3-Flash (OpenCode Go)",
                "reasoning": false,
                "input": ["text"],
                "contextWindow": 128000,
                "maxTokens": 12000
              }
            ]
          }
        }
      }
      JSON
env:
  OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
network:
  allowed:
    - defaults
    - opencode.ai
---

# Engine lane: pi + OpenCode Go (ADR-0007 — single model, single provider)

Model: **`openai/glm-5.3-flash`** for every workflow in this pipeline —
the `openai/` prefix routes through gh-aw's credential-isolated gateway
as the OpenAI-compatible backend while `OPENAI_BASE_URL` re-targets it to
`https://opencode.ai/zen/go/v1` (Go). `engine.config.model` declares the
**Chat Completions** wire protocol (`api: openai-completions`) — Go's
glm-5.3-flash surface — plus input/context/output limits and
**`"reasoning": false`** (the GLM upstream 400s on `reasoning_effort`;
the adopting repo's own #479/#493 history — never omit it).

Authentication: one secret, **`OPENAI_API_KEY`** (same OpenCode key as
the repo's `OPENCODE_API_KEY` — only the binding name follows gh-aw's
provider contract). `network.allowed` includes `opencode.ai`. Pi is a
**validated Go client** (session headers, current builds; hence the
version pin) — no custom header work needed here. Metering: glm-5.3-flash
carries a $60/month (Go) / $180 (Go Plus) per-model cap; per-workflow
`max-ai-credits` is the gh-aw-side ceiling.

History: the original draft of this lane used pi's own `models.json` +
pre-agent-step writing, then `model: opencode-go/...` with
`model-provider: openai` — both proved unsupported on v0.89.21 (the
latter silently routed pi to the Copilot gateway and made the shipped
locks demand a nonexistent `COPILOT_GITHUB_TOKEN`). The recognized-prefix
form above is what the compiler's own resolution code accepts; treat
"model segments not in the allowlist" as a compile-day tripwire.
