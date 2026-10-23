"""One tutor turn: Claude tool loop with streaming, ending in a parsed TutorTurn.

History is append-only. Current models replay earlier thinking blocks only while `system`, `tools`
and every earlier message are unchanged, so the caller persists exactly the messages a turn returns
(`Final.new_messages`, full content blocks) and sends them back unchanged next turn. Per-turn
context (mode, session state) goes in as a mid-conversation system message after the learner's
message instead of editing `system`. As a safety net, `drop_block` makes the API drop thinking
blocks it can no longer bind instead of rejecting the request.
"""
from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

from backend.tutor import guard
from backend.tutor.host import ModelCall
from backend.tutor.prompt import SessionState, system_blocks, turn_system_text
from backend.tutor.schemas import GuardFinding, TutorTurn
from backend.tutor.tools import TOOLS, ToolContext, TurnBudget, dispatch
from backend.tutor.turn_parser import FenceSplitter, TurnParseError, parse_turn, split_reply

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "medium"  # recommended starting point for multistep tool use on this model
MAX_TOKENS = 16000
MAX_MODEL_CALLS = 10  # tool budget is 6 calls; this bounds the loop even if the model ignores it
MAX_STREAM_RETRIES = 2
BETAS = [
    "server-side-fallback-2026-07-01",  # fallbacks="default": retry policy declines on another model
    "thinking-binding-controls-2026-08-01",  # block_binding.prefix_mismatch_behavior
]
# Blocks that must not be echoed when they precede a fallback switch point (refusal fallback rules).
_DROP_BEFORE_FALLBACK = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}

Message = dict[str, Any]


# ----------------------------------------------------------------------------- events
@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResultSummary:
    name: str
    is_error: bool
    summary: str


@dataclass(frozen=True)
class Rewrite:
    """The guard rejected the streamed answer; the UI should replace it with what streams next."""

    codes: list[str]


@dataclass(frozen=True)
class Final:
    turn: TutorTurn
    new_messages: list[Message]
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    findings: list[GuardFinding] = field(default_factory=list)


TurnEvent = Token | ToolCall | ToolResultSummary | Rewrite | Final


# ----------------------------------------------------------------------------- helpers
def api_tools() -> list[dict[str, Any]]:
    """TOOLS as sent: eager input streaming on (inputs are validated by dispatch before running)."""
    return [{**tool, "eager_input_streaming": True} for tool in TOOLS]


def echo_content(blocks: list[Any]) -> list[dict[str, Any]]:
    """Assistant content to append to history, unchanged except for the fallback echo rule."""
    dumped = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks]
    last_fallback = max((i for i, b in enumerate(dumped) if b.get("type") == "fallback"), default=-1)
    return [b for i, b in enumerate(dumped) if i > last_fallback or b.get("type") not in _DROP_BEFORE_FALLBACK]


def reply_text(content: list[dict[str, Any]]) -> str:
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def _speech(markdown: str, words: int = 60) -> str:
    plain = " ".join(ln for ln in markdown.splitlines() if not ln.lstrip().startswith(("```", "|", "#")))
    return " ".join(plain.split()[:words])


def fallback_turn(state: SessionState, text: str, flag: str) -> TutorTurn:
    return TutorTurn(mode=state.mode, language=state.language, persona_on=state.persona_on,
                     speech=_speech(text), text=text, guard_flags=[flag])


REFUSAL_TEXT = {
    "de": "Dazu kann ich in dieser Sitzung keine Antwort geben. Formuliere die Frage bitte anders, "
          "oder wir machen mit dem Lab weiter.",
    "en": "I can't answer that in this session. Try rephrasing the question, or let's continue with the lab.",
}


def _add_usage(total: dict[str, int], usage: Any) -> None:
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total[key] = total.get(key, 0) + (getattr(usage, key, None) or 0)


# ----------------------------------------------------------------------------- loop
@dataclass
class Orchestrator:
    client: AsyncAnthropic
    model: str = field(default_factory=lambda: os.environ.get("TUTOR_MODEL", DEFAULT_MODEL))
    effort: str = field(default_factory=lambda: os.environ.get("TUTOR_EFFORT", DEFAULT_EFFORT))
    max_tokens: int = MAX_TOKENS
    on_call: Callable[[ModelCall], Awaitable[None]] | None = None  # host accounting, one call per API request

    def _request(self, session_persona_on: bool, learner_name: str, messages: list[Message]) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_blocks(session_persona_on, learner_name),
            "tools": api_tools(),
            "messages": messages,
            "thinking": {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},  # caches the growing conversation prefix
            "fallbacks": "default",
            "betas": BETAS,
        }

    async def run_turn(
        self,
        *,
        history: list[Message],
        user_text: str,
        state: SessionState,
        ctx: ToolContext,
        session_persona_on: bool | None = None,
        learner_name: str | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """Stream one turn. `session_persona_on`/`learner_name` fix `system` for the session; they
        default to the state's values and must not change between turns of one session."""
        persona = state.persona_on if session_persona_on is None else session_persona_on
        name = learner_name or state.learner_name
        new: list[Message] = [
            {"role": "user", "content": user_text},
            {"role": "system", "content": turn_system_text(state)},
        ]
        budget = TurnBudget()
        usage: dict[str, int] = {}
        markdown = ""
        repaired = False
        guard_retried = False
        stream_retries = 0
        model_used = self.model

        for _ in range(MAX_MODEL_CALLS):
            splitter = FenceSplitter()
            started = time.monotonic()
            try:
                async with self.client.beta.messages.stream(
                    **self._request(persona, name, history + new)
                ) as stream:
                    async for event in stream:
                        if event.type == "text" and (out := splitter.feed(event.text)):
                            yield Token(out)
                    final = await stream.get_final_message()
            except ValueError:
                # Tool input JSON the SDK could not parse: no tool_use id to answer, so re-issue.
                stream_retries += 1
                if stream_retries > MAX_STREAM_RETRIES:
                    raise
                continue
            if tail := splitter.flush():
                yield Token(tail)

            _add_usage(usage, final.usage)
            model_used = final.model
            if self.on_call:
                call_usage: dict[str, int] = {}
                _add_usage(call_usage, final.usage)
                await self.on_call(ModelCall(final.model, call_usage, round((time.monotonic() - started) * 1000, 1)))
            content = echo_content(final.content)
            new.append({"role": "assistant", "content": content})

            if final.stop_reason == "refusal":
                yield Final(fallback_turn(state, REFUSAL_TEXT[state.language], "refusal"), new, usage, model_used)
                return

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if tool_uses:
                results = []
                for block in tool_uses:
                    raw = block.get("input")
                    args = raw if isinstance(raw, dict) else {}
                    yield ToolCall(block["name"], args)
                    if final.stop_reason == "max_tokens":
                        # A truncated input can parse as a valid partial object: never run it.
                        res_block = {"type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                                     "content": "tool input was cut off (max_tokens); call the tool again"}
                        yield ToolResultSummary(block["name"], True, "truncated input, not run")
                    else:
                        result = await dispatch(block["name"], args, ctx, budget)
                        res_block = result.to_block(block["id"])
                        yield ToolResultSummary(block["name"], result.is_error, result.content[:200])
                    results.append(res_block)
                new.append({"role": "user", "content": results})
                continue

            reply_md, json_text = split_reply(reply_text(content))
            markdown = reply_md or markdown  # a repair reply carries only the JSON block
            try:
                turn = parse_turn(markdown, json_text)
            except TurnParseError as e:
                if repaired:
                    turn = guard.redact_secrets(fallback_turn(state, markdown, "unstructured"), user_text)
                    yield Final(turn, new, usage, model_used)
                    return
                repaired = True
                new.append({"role": "user", "content": (
                    f"[app message, not from the learner] {e}. Reply with only the corrected "
                    "```json tutor_turn block for your previous answer (without `text`).")})
                continue

            gctx = guard.GuardContext(sources=guard.collect_sources(history + new), learner_text=user_text,
                                      ran_lab_sql=guard.ran_tool(new, "run_lab_sql"),
                                      known_evidence=len(state.incident.model.evidence) if state.incident else 0)
            findings = guard.check(turn, gctx)
            blocking = [f for f in findings if f.severity == "block"]
            if blocking and not guard_retried:
                guard_retried = True
                yield Rewrite(sorted({f.code for f in blocking}))
                new.append({"role": "user", "content": guard.repair_message(findings)})
                continue
            turn = guard.redact_secrets(turn, user_text).model_copy(
                update={"guard_flags": sorted({f.code for f in findings})})
            yield Final(turn, new, usage, model_used, findings)
            return

        yield Final(fallback_turn(state, markdown or REFUSAL_TEXT[state.language], "tool_loop_limit"),
                    new, usage, model_used)
