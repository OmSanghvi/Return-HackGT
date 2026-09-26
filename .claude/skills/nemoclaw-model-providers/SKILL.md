---
name: nemoclaw-model-providers
description: Use whenever configuring or changing the model behind NemoClaw's reasoning or vision (part of Build Plan step 3, used by steps 4, 4a, 5, 6 and 24). Covers the three supported providers — Meta Model API (Muse Spark), xAI Grok API, and Nebius Token Factory (open models including Llama) — their verified base URLs, key variables and models, the single OpenAI-compatible adapter, the provider/model fields recorded on outputs, and key handling.
---

# NemoClaw model providers

Verified 2026-09-25. The example config is
`config/nemoclaw/model-providers.example.json`.

## Providers

| `NEMOCLAW_MODEL_PROVIDER` | Service | Base URL | Key env var | Default model | Use |
| --- | --- | --- | --- | --- | --- |
| `meta` (**default**) | Meta Model API, Muse Spark | `https://api.meta.ai/v1` | `META_MODEL_API_KEY` | `muse-spark-1.3` (tool calling, image input, 1M context) | Meta track: Meta's own current model through Meta's own API |
| `xai` | xAI Grok API | `https://api.x.ai/v1` | `XAI_API_KEY` | `grok-4.7` | Resilience Commons (Grok) track; fallback |
| `nebius` | Nebius Token Factory | `https://api.tokenfactory.nebius.com/v1/` | `NEBIUS_API_KEY` | pick from the catalog | Open models (Llama, Qwen, and others), for example when a Llama-specific story is wanted |

Facts to keep straight:
- **All three are OpenAI-SDK compatible**, so build **one** adapter where
  `base_url`, key, and model come from config. No per-provider code paths
  beyond those capability flags.
- **Meta Model API** is in **public preview for US developers** (since
  2026-07-09) at $1.25 / $4.25 per million input/output tokens.
  - Meta's docs example calls the key `MODEL_API_KEY`; this project names
    it `META_MODEL_API_KEY` and maps it in the runtime config.
  - The docs don't list Llama models there. The older public-preview Llama
    API is gone, so Llama means Nebius (or another host).
- **Muse Spark is a reasoning/multimodal model.** It has nothing to do with
  "Meta Muse Image", the image-generation backend this project rejected
  and removed. That rejection still stands; this provider doesn't bring
  image generation back.
- **Grok image input varies by model.** Set `NEMOCLAW_VISION_MODEL` to a
  vision-capable Grok model (check docs.x.ai/developers/models) before
  using `identify_subject` on xAI.
- For **Nebius**, choose exact model ids from the Token Factory catalog:
  one that supports tool calling for the agent, and one vision model for
  `identify_subject`. Write the chosen ids into the example config and
  AGENT.md. Don't guess ids.

## Configuration

- `NEMOCLAW_MODEL_PROVIDER` = `meta` | `xai` | `nebius` (default `meta`).
- `NEMOCLAW_MODEL` overrides the provider's default model.
- `NEMOCLAW_VISION_MODEL` overrides the model used for image input
  (`identify_subject`, `read_sketch_layout`).
- The old `NEMOCLAW_MODEL_BACKEND=llama|grok` is **replaced**. Map it once
  (`grok` → `xai`, `llama` → `nebius`), then remove it. Don't keep both.
- The agent runtime (OpenClaw, Hermes Agent, or LangChain Deep Agents; see
  `nemoclaw-agent-setup`) is configured with an OpenAI-compatible provider
  using the base URL and key above.
- Keys live **only** in the runtime's credential provider or environment.
  Never put them in the repo, `config/`, the web app, the Unity project, or
  chat. The gate script scans for xAI `xai-` keys and for any
  `*_API_KEY=`/`*_SECRET=` assignment with a real value.

## Recorded on outputs

`ConnectionInsight`, subject labels, and staging plans record `backend`
(`mock` | `meta` | `xai` | `nebius`) and `model` (the exact model id). Mock
output is always `backend="mock"` and never described as a model result
(AGENT.md AI rule).

## Safety

- All user text (labels, memory text, room prompt, letter notes) is passed
  as delimited data, never as instructions.
- Every model output that becomes a blueprint is schema-validated before
  it's saved.
- Live model calls during development need explicit approval (Hard Rule
  3). Tests use mocks.
- Watch spend: provider calls cost money per token. Log token usage per
  compose call.

## Definition of done (as part of step 3)

NemoClaw completes one tool-calling round trip on the default provider
(`meta`), then the same with `xai` by changing only the env var. Both
recorded outputs carry the correct `backend` and `model`. No key appears in
any file, and `python3 scripts/check_collab_gates.py --status` passes.

## Sources

- https://dev.meta.ai/models/muse-spark/
- https://dev.meta.ai/resources/blog/build-with-muse-spark/
- https://ai.meta.com/blog/introducing-muse-spark-meta-model-api/
- https://docs.x.ai/developers/quickstart
- https://docs.x.ai/developers/models
- https://docs.tokenfactory.nebius.com/api-reference/introduction
