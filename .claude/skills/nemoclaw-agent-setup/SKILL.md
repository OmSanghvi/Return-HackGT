---
name: nemoclaw-agent-setup
description: Use when standing up the actual NemoClaw agent runtime and registering Meta's Unity MCP Extension for SketchScape / Shared Room — Build Plan step 3 in docs/BUILD_PLAN.md. This is environment/registration work, not application code, and involves cost- or access-sensitive setup that needs explicit user approval at each irreversible step.
---

# NemoClaw agent setup (Build Plan step 3)

Before any NemoClaw tool (`place_objects_in_scene`, `stage_immersive_reveal`,
etc.) can exist, an actual agent runtime has to be running and pointed at a
real Unity MCP session. This repo has so far only *described* NemoClaw and
Unity MCP in documentation (`AGENT.md`, `config/nemoclaw/sketchscape-tools.json`)
— nothing here stands up a live agent yet. This skill is that first step.

## Hard requirements (from AGENT.md — do not deviate)

- Use Meta's own **Unity MCP Extension for Horizon**
  (https://developers.meta.com/horizon/documentation/unity/unity-mcp-extension/)
  as the Unity MCP integration — never a generic/third-party Unity MCP
  server for this track. Follow that page's *current* setup instructions;
  its install steps and tool surface can change, so don't rely on a
  remembered configuration. **Requires Unity Editor 6000.0.66f2 or later**
  (verified September 2026) — check the installed Unity version first.
- Model provider: follow the `nemoclaw-model-providers` skill. The default
  is `NEMOCLAW_MODEL_PROVIDER=meta` (Meta Model API, Muse Spark
  `muse-spark-1.3`), with `xai` (Grok) and `nebius` (Token Factory, open
  models including Llama) switchable. `NEMOCLAW_MODEL_BACKEND` is replaced.
  Meta's Model API doesn't list Llama models; use `nebius` for Llama.
  Confirm `xai` works before anyone relies on it for the Resilience
  Commons framing. It's a config value, not a code fork.
- **Never expose the registered Unity MCP endpoint publicly.** Register only
  a trusted local/private target, per
  `.agents/skills/sketchscape-infrastructure/SKILL.md`'s existing safety
  boundary.
- **Never put credentials in this repo** — not in `config/nemoclaw/*.json`,
  not in a commit, not in a chat message. `config/nemoclaw/mcp-servers.example.json`
  exists as a template; keep it that way.
- Installing NemoClaw or registering new MCP targets is exactly the kind of
  action `AGENT.md`'s hard rules require explicit user approval for before
  proceeding — confirm before installing anything, not after.

## Concrete steps

1. Pick the agent runtime per `AGENT.md`'s "NemoClaw integration" section —
   three verified, currently-real options:
   [OpenClaw](https://github.com/openclaw/openclaw) (MIT, TypeScript,
   config-first via `SOUL.md`, the most widely adopted of the three),
   [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous
   Research, self-improving, built-in Tool Gateway for search/image-gen/TTS),
   or [LangChain Deep Agents](https://github.com/langchain-ai/deepagents)
   (MIT, Python, built on LangGraph, provider-agnostic). Ask the user if none
   has been chosen yet; don't default silently to one.
2. Follow that runtime's current official onboarding docs to install it
   locally.
3. Install and configure the Unity MCP Extension for Horizon per its current
   docs page (link above).
   - It installs from GitHub
     (`https://github.com/meta-quest/Unity-MCP-Extensions.git`) and Meta
     warns that "functionality might vary by version", so **pin a specific
     commit or tag** in `Packages/manifest.json` and record it here.
   - The extension documents only **write** operations (create, update or
     delete GameObjects, relative move/rotate, grabbable, teleport
     hotspots). Any read-only inspection comes from Unity's base MCP
     package that the extension plugs into. Check what that exposes. If
     there's no read tool, read scene state from the backend
     (`compiled-scene`) instead of assuming the extension can.
   - Confirm a read-only inspection of the open `../HackGTUnity` project
     works before attempting any write.
4. Register the Unity MCP Extension as NemoClaw's trusted local Unity target.
5. Configure the runtime's OpenAI-compatible provider from
   `config/nemoclaw/model-providers.example.json`, with keys only in its
   credential provider. Run one tool-calling round trip on `meta`, then on
   `xai` by changing only `NEMOCLAW_MODEL_PROVIDER`.
6. Update `config/nemoclaw/sketchscape-tools.json`: this file is
   documentation-only (its own header says so) — add or update entries for
   any newly-registered capability, keeping the existing `id`/`method`/`path`/
   `purpose`/`approval_required`/`implementation_status` shape. Do not mark
   anything `implemented` until it's actually been run successfully.

## Definition of done

NemoClaw can perform one read-only scene inspection through the Unity MCP
Extension against the real `../HackGTUnity` project and return a sensible
result — no scene mutation yet, no credentials written anywhere in this
repo. Hand off to `nemoclaw-scene-tools` (Build Plan step 4) next.
