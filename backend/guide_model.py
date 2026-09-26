"""The model client behind the guide runtime: one OpenAI-compatible adapter.

Mirrors `config/nemoclaw/model-providers.example.json` (a test asserts the
two match) and the same three providers `nemoclaw-model-providers` uses for
NemoClaw's own reasoning: Meta Model API (Muse Spark, default), xAI Grok, and
Nebius Token Factory. The guide runtime picks its provider independently via
`SKETCHSCAPE_GUIDE_MODEL_PROVIDER` (default `mock`), since a live guide call
needs separate approval from a live NemoClaw call.

Mock is the default everywhere in this repo (Hard Rule 2): `openai` is
imported lazily, only inside `OpenAICompatGuideModel`, so the base install
and every test never need it installed or configured.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Protocol

PROVIDERS: dict[str, dict[str, str | None]] = {
    "meta": {"base_url": "https://api.meta.ai/v1", "key_env": "META_MODEL_API_KEY", "model": "muse-spark-1.3"},
    "xai": {"base_url": "https://api.x.ai/v1", "key_env": "XAI_API_KEY", "model": "grok-4.7"},
    "nebius": {"base_url": "https://api.tokenfactory.nebius.com/v1/", "key_env": "NEBIUS_API_KEY", "model": None},
}

# Whether `tool_choice="required"` is honored by the configured provider.
# Set from the 32.0 spike results; `auto` is the safe default until that
# spike has run and this is updated (a reply with no tool call already
# becomes the scripted fallback either way, so `auto` never breaks safety).
GUIDE_TOOL_CHOICE = os.environ.get("SKETCHSCAPE_GUIDE_TOOL_CHOICE", "auto")

_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for word in _WORD_PATTERN.findall(text.lower()):
        tokens.add(word)
        if len(word) > 3 and word.endswith("s"):
            tokens.add(word[:-1])
    return tokens


class GuideModel(Protocol):
    backend: str
    model: str

    async def turn(
        self, tour: Any, session: dict, event: dict, tool: dict, timeout_s: float
    ) -> tuple[dict | None, dict, int]:
        """Return `(args_dict, usage, latency_ms)`. `args_dict` is `None` when
        the model returned no tool call (`validate_turn` then falls back)."""
        ...


class MockGuideModel:
    """Deterministic, offline stand-in (Hard Rule 2's default provider).

    - `ask_about`/`linger`: the first fact of that element not yet in
      `session.said_fact_ids`.
    - `more`: the next unsaid fact of the current step.
    - `question`: the fact with the highest keyword overlap with the
      visitor's text (the same tokenizer as `main.compose_connection_mock`),
      or a `decline` when the overlap is 0.
    """

    backend = "mock"
    model = "mock-guide-v1"

    async def turn(
        self, tour: Any, session: dict, event: dict, tool: dict, timeout_s: float
    ) -> tuple[dict | None, dict, int]:
        start = time.monotonic()
        said = set(session.get("said_fact_ids", []))
        facts_by_id = {fact.fact_id: fact for fact in tour.facts}
        current_step_id = session.get("current_step_id")
        current_step = next((s for s in tour.steps if s.step_id == current_step_id), None)
        event_type = event.get("type")

        fact_id: str | None = None
        intent = "answer"

        if event_type in ("ask_about", "linger"):
            element = next((e for e in tour.elements if e.element_id == event.get("element_id")), None)
            if element is not None:
                fact_id = next((fid for fid in element.fact_ids if fid not in said), None)
                if fact_id is None and element.fact_ids:
                    fact_id = element.fact_ids[0]
        elif event_type == "more" and current_step is not None:
            fact_id = next((fid for fid in current_step.fact_ids if fid not in said), None)
            if fact_id is None and current_step.fact_ids:
                fact_id = current_step.fact_ids[0]
        elif event_type == "question":
            query_tokens = _tokens(event.get("text") or "")
            best_score, best_id = 0, None
            for fact in tour.facts:
                score = len(query_tokens & _tokens(fact.text))
                if score > best_score:
                    best_score, best_id = score, fact.fact_id
            if best_id is not None:
                fact_id = best_id
            else:
                intent = "decline"

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = {"input_tokens": 0, "output_tokens": 0}

        if intent == "decline" or fact_id is None:
            args = {
                "intent": "decline",
                "step_id": current_step_id or (tour.steps[0].step_id if tour.steps else ""),
                "say": [{"text": tour.guardrails.off_topic_reply, "fact_ids": []}],
                "highlight_element_ids": [],
                "reveal_element_ids": [],
                "move_to_element_id": "",
            }
            return args, usage, latency_ms

        fact = facts_by_id[fact_id]
        args = {
            "intent": intent,
            "step_id": current_step_id or (tour.steps[0].step_id if tour.steps else ""),
            "say": [{"text": fact.text, "fact_ids": [fact_id]}],
            "highlight_element_ids": [],
            "reveal_element_ids": [],
            "move_to_element_id": "",
        }
        return args, usage, latency_ms


class OpenAICompatGuideModel:
    """One OpenAI-SDK-compatible client for any of `PROVIDERS`.

    `openai` is imported lazily (see module docstring). Fails fast at
    construction if the provider's key env var isn't set -- never falls back
    silently to mock.
    """

    def __init__(self, provider: str, *, model: str | None = None, timeout_s: float = 15.0) -> None:
        if provider not in PROVIDERS:
            raise RuntimeError(
                f"Unknown SKETCHSCAPE_GUIDE_MODEL_PROVIDER {provider!r}. "
                f"Use one of: mock, {', '.join(PROVIDERS)}."
            )
        config = PROVIDERS[provider]
        key = os.environ.get(config["key_env"])
        if not key:
            raise RuntimeError(
                f"{config['key_env']} is not set; it's required for "
                f"SKETCHSCAPE_GUIDE_MODEL_PROVIDER={provider}."
            )
        resolved_model = model or config["model"]
        if not resolved_model:
            raise RuntimeError(
                f"SKETCHSCAPE_GUIDE_MODEL must be set for provider {provider!r} "
                "(it has no default model)."
            )
        self.backend = provider
        self.model = resolved_model
        self._base_url = config["base_url"]
        self._key = key
        self._timeout_s = timeout_s
        self._client = None  # resolved lazily on first call

    def _resolve_client(self):
        if self._client is None:
            import openai  # noqa: PLC0415 - lazy, see module docstring

            self._client = openai.AsyncOpenAI(
                base_url=self._base_url, api_key=self._key, timeout=self._timeout_s, max_retries=0
            )
        return self._client

    async def turn(
        self, tour: Any, session: dict, event: dict, tool: dict, timeout_s: float
    ) -> tuple[dict | None, dict, int]:
        from guide_prompts import render_system_prompt, render_user_blocks  # noqa: PLC0415

        client = self._resolve_client()
        messages = [{"role": "system", "content": render_system_prompt(tour.persona.name)}]
        messages.extend({"role": "user", "content": block} for block in render_user_blocks(tour, session, event))

        start = time.monotonic()
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=[tool],
            tool_choice=GUIDE_TOOL_CHOICE,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        args: dict | None = None
        if tool_calls:
            import json  # noqa: PLC0415

            try:
                args = json.loads(tool_calls[0].function.arguments)
            except (ValueError, AttributeError):
                args = None

        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
        }
        return args, usage, latency_ms


def create_guide_model(provider: str | None = None) -> GuideModel:
    """Build the configured guide model. `provider` overrides
    `SKETCHSCAPE_GUIDE_MODEL_PROVIDER` (default `mock`, Hard Rule 2)."""
    selected = (provider or os.environ.get("SKETCHSCAPE_GUIDE_MODEL_PROVIDER", "mock")).strip().lower()
    if selected == "mock":
        return MockGuideModel()
    return OpenAICompatGuideModel(selected, model=os.environ.get("SKETCHSCAPE_GUIDE_MODEL"))
