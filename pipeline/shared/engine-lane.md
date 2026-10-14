---
# ADOPTER-OWNED FILE — this is the one fragment every adopting repo
# writes for itself (engine, model, secret lane, network). The pilot's
# lane (below) is one example, not the default. Sources in this pipeline
# never hardcode an engine; they import this file relatively.
engine:
  id: pi
  version: "1.1.0"
  env:
    OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
pre-agent-steps:
  - name: Ship pi models.json (OpenCode Go lane - glm-5.3-flash)
    run: |
      DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
      mkdir -p "$DIR"
      cat > "$DIR/models.json" <<'PI_MODELS'
      {
        "providers": {
          "opencode-go": {
            "baseUrl": "https://opencode.ai/zen/go/v1",
            "api": "openai-completions",
            "apiKey": "$OPENCODE_API_KEY",
            "models": [
              {
                "id": "glm-5.3-flash",
                "name": "GLM-5.3-Flash (OpenCode Go)",
                "input": ["text"],
                "cost": { "input": 0.15, "output": 0.5, "cacheRead": 0.03, "cacheWrite": 0 }
              }
            ]
          }
        }
      }
      PI_MODELS
network:
  allowed:
    - defaults
    - opencode.ai
---

# Engine lane: pi + OpenCode Go (ADR-0007 — single model, single provider)

Model: **opencode-go/glm-5.3-flash** for every workflow in this pipeline.
GLM-5.3-Flash speaks OpenAI Chat Completions (`/v1/chat/completions`) —
the surface pi's `openai-completions` API implements against
`https://opencode.ai/zen/go/v1`. Authentication: one secret,
`OPENCODE_API_KEY`, referenced by pi's `models.json` as the literal
`$OPENCODE_API_KEY` and interpolated by pi at request time — the key is
never committed and never appears in workflow frontmatter. Go is a metered
lane: glm-5.3-flash carries a **$60/month (Go tier) or $180 (Go Plus)**
per-model usage cap; the per-workflow `max-ai-credits` is the gh-aw-side
ceiling and the plan cap is the provider-side one. Pi is a **validated Go
client** (agent session headers sent by current builds; hence the version
pin), so no custom header work is needed here.
