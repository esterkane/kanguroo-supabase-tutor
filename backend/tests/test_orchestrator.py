"""Orchestrator tests against a scripted fake Anthropic client (real SDK message types, no network)."""
from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, Self
from uuid import uuid4

import pytest
from anthropic.types.beta import BetaMessage

from backend.tutor import orchestrator as o
from backend.tutor.ledger import LedgerDelta, LedgerEntry
from backend.tutor.prompt import SessionState
from backend.tutor.schemas import Chunk
from backend.tutor.tools import TOOLS, ToolContext
from backend.tutor.turn_parser import FenceSplitter, TurnParseError, parse_turn, split_reply

TURN_JSON: dict[str, Any] = {"mode": "lesson", "language": "de", "persona_on": True,
             "speech": "Welche Kontrolle prüfst du zuerst?", "next_question": "Welche Kontrolle prüfst du zuerst?"}


def answer(markdown: str, turn: dict[str, Any] | None = None) -> str:
    """A contract-conforming reply: Markdown ending with the question, then the JSON block."""
    turn = turn or TURN_JSON
    question = str(turn.get("next_question") or "")
    if markdown and question and question not in markdown:
        markdown = f"{markdown}\n\n{question}"
    return f"{markdown}\n\n```json tutor_turn\n{json.dumps(turn)}\n```"


def message(content: list[dict[str, Any]], stop: str = "end_turn") -> BetaMessage:
    return BetaMessage.model_validate({
        "id": f"msg_{uuid4().hex[:8]}", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "stop_reason": stop, "stop_sequence": None, "content": content,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}})


class FakeStream:
    def __init__(self, chunks: list[str], final: BetaMessage, fail: bool = False) -> None:
        self.chunks, self.final, self.fail = chunks, final, fail

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def _events(self) -> Any:
        for c in self.chunks:
            yield SimpleNamespace(type="text", text=c)
        if self.fail:
            raise ValueError("unparseable tool input JSON")

    def __aiter__(self) -> Any:
        return self._events()

    async def get_final_message(self) -> BetaMessage:
        return self.final


class FakeClient:
    def __init__(self, script: list[FakeStream]) -> None:
        self.script = script
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs: Any) -> FakeStream:
        self.requests.append(copy.deepcopy(kwargs))
        return self.script.pop(0)


def text_reply(markdown: str, chunk: int = 7, turn: dict[str, Any] | None = None) -> FakeStream:
    full = answer(markdown, turn)
    return FakeStream([full[i:i + chunk] for i in range(0, len(full), chunk)],
                      message([{"type": "text", "text": full}]))


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, k: int = 8, products: Sequence[str] | None = None) -> list[Chunk]:
        self.calls += 1
        return [Chunk(chunk_id=uuid4(), url="https://supabase.com/docs/guides/troubleshooting/x.md", anchor="a",
                      heading_path="42501 > Missing grants", content="grant select ...", tier=1,
                      fetched_at=None, score=0.03)]


class FakeLedger:
    async def read(self, user_id: Any) -> list[LedgerEntry]:
        return []

    async def update(self, user_id: Any, deltas: list[LedgerDelta]) -> list[LedgerEntry]:
        return []


def ctx(retriever: FakeRetriever | None = None) -> ToolContext:
    return ToolContext(user_id=uuid4(), retriever=retriever or FakeRetriever(), ledger=FakeLedger())


async def run(client: FakeClient, history: list[dict[str, Any]] | None = None,
              state: SessionState | None = None, c: ToolContext | None = None) -> list[o.TurnEvent]:
    orch = o.Orchestrator(client=client, model="claude-sonnet-5-5", effort="medium")  # type: ignore[arg-type]
    return [e async for e in orch.run_turn(history=history or [], user_text="Hallo", state=state or SessionState(),
                                           ctx=c or ctx())]


# ----------------------------------------------------------------------------- parser
def test_fence_splitter_holds_back_partial_fence_across_chunks() -> None:
    s = FenceSplitter()
    out = s.feed("Antwort ``") + s.feed("`json tut") + s.feed("or_turn\n{}") + s.feed("more")
    assert out == "Antwort " and s.flush() == ""


def test_fence_splitter_releases_backticks_that_are_not_the_fence() -> None:
    s = FenceSplitter()
    assert s.feed("code: ``") == "code: "
    assert s.feed("`sql\nselect 1") == "```sql\nselect 1"
    assert s.feed(" ``") == " " and s.flush() == "``"


def test_parse_turn_fills_text_from_markdown() -> None:
    md, js = split_reply(answer("**Markdown** answer"))
    turn = parse_turn(md, js)
    assert turn.text == "**Markdown** answer\n\nWelche Kontrolle prüfst du zuerst?" and turn.guard_flags == []


@pytest.mark.parametrize(("reply", "fragment"), [
    ("no block at all", "no ```json tutor_turn"),
    ("x\n```json tutor_turn\n{not json\n```", "not valid JSON"),
    (answer("x", {**TURN_JSON, "speech": None}), "speech"),
    (answer("x", {**TURN_JSON, "surprise": 1}), "surprise"),
])
def test_parse_turn_errors_name_the_problem(reply: str, fragment: str) -> None:
    with pytest.raises(TurnParseError, match=fragment.replace("`", ".")):
        parse_turn(*split_reply(reply))


# ----------------------------------------------------------------------------- loop
async def test_simple_turn_streams_markdown_only_and_builds_request() -> None:
    client = FakeClient([text_reply("Kleinkünstler, GRANT ist der Schlüssel.")])
    events = await run(client)
    tokens = "".join(e.text for e in events if isinstance(e, o.Token))
    assert tokens.strip() == "Kleinkünstler, GRANT ist der Schlüssel.\n\nWelche Kontrolle prüfst du zuerst?"
    final = events[-1]
    assert isinstance(final, o.Final)
    assert final.turn.text.startswith("Kleinkünstler, GRANT ist der Schlüssel.")
    assert final.turn.guard_flags == [] and final.findings == []
    assert [m["role"] for m in final.new_messages] == ["user", "system", "assistant"]
    assert final.new_messages[1]["content"].startswith("# MODE: lesson")
    assert final.usage["cache_read_input_tokens"] == 50

    req = client.requests[0]
    assert req["model"] == "claude-sonnet-5-5"
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    assert req["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert req["output_config"] == {"effort": "medium"}
    assert len(req["system"]) == 1 and req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in req["tools"]] == [t["name"] for t in TOOLS]
    assert all(t["eager_input_streaming"] is True for t in req["tools"])
    assert all("eager_input_streaming" not in t for t in TOOLS)  # the contract copy stays pristine


async def test_tool_loop_passes_thinking_back_unchanged() -> None:
    retriever = FakeRetriever()
    first = FakeStream([], message([
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
        {"type": "tool_use", "id": "toolu_1", "name": "search_docs", "input": {"query": "42501 grant"}},
    ], stop="tool_use"))
    cited = {**TURN_JSON, "citations": [{"n": 1, "url": "https://supabase.com/docs/guides/troubleshooting/x.md#a",
                                         "title": "Missing grants", "tier": 1}]}
    client = FakeClient([first, text_reply("Es fehlt das GRANT [1].", turn=cited)])
    events = await run(client, c=ctx(retriever))

    assert [type(e).__name__ for e in events if not isinstance(e, o.Token)] == \
        ["ToolCall", "ToolResultSummary", "Final"]
    assert retriever.calls == 1
    second_msgs = client.requests[1]["messages"]
    assert second_msgs[2]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    tool_result = second_msgs[3]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert not tool_result["is_error"] and "troubleshooting/x.md#a" in tool_result["content"]
    final = events[-1]
    assert isinstance(final, o.Final) and [m["role"] for m in final.new_messages] == \
        ["user", "system", "assistant", "user", "assistant"]


async def test_history_is_append_only_across_turns() -> None:
    client = FakeClient([text_reply("Erste Antwort."), text_reply("Zweite Antwort.")])
    first = (await run(client))[-1]
    assert isinstance(first, o.Final)
    history = first.new_messages
    await run(client, history=history, state=SessionState(mode="incident", objective="locks"))
    req1, req2 = client.requests
    assert req2["system"] == req1["system"] and req2["tools"] == req1["tools"]
    assert req2["messages"][: len(history)] == history  # earlier turns sent back byte-identical
    assert req2["messages"][len(history) + 1]["content"].startswith("# MODE: incident")


async def test_invalid_turn_gets_one_repair_then_unstructured() -> None:
    first_md = "Antwort ohne Block. Welche Kontrolle prüfst du zuerst?"
    fixed = FakeStream([], message([{"type": "text", "text": answer("")}]))
    client = FakeClient([FakeStream([first_md], message([{"type": "text", "text": first_md}])), fixed])
    final = (await run(client))[-1]
    assert isinstance(final, o.Final)
    assert final.turn.text == first_md and final.turn.guard_flags == []
    repair = client.requests[1]["messages"][-1]
    assert repair["role"] == "user" and repair["content"].startswith("[app message, not from the learner]")

    broken = FakeStream(["kaputt"], message([{"type": "text", "text": "kaputt"}]))
    client = FakeClient([broken, FakeStream(["immer noch"], message([{"type": "text", "text": "immer noch"}]))])
    final = (await run(client))[-1]
    assert isinstance(final, o.Final) and final.turn.guard_flags == ["unstructured"]
    assert final.turn.text == "immer noch"


async def test_refusal_returns_flagged_turn_in_session_language() -> None:
    client = FakeClient([FakeStream([], message([], stop="refusal"))])
    final = (await run(client, state=SessionState(language="en")))[-1]
    assert isinstance(final, o.Final) and final.turn.guard_flags == ["refusal"]
    assert final.turn.text.startswith("I can't answer that")


async def test_truncated_tool_input_is_never_run() -> None:
    retriever = FakeRetriever()
    cut = FakeStream([], message([{"type": "tool_use", "id": "toolu_9", "name": "search_docs",
                                   "input": {"query": "par"}}], stop="max_tokens"))
    client = FakeClient([cut, text_reply("Weiter.")])
    events = await run(client, c=ctx(retriever))
    assert retriever.calls == 0
    result = client.requests[1]["messages"][3]["content"][0]
    assert result["is_error"] and "cut off" in result["content"]
    assert isinstance(events[-1], o.Final)


async def test_unparseable_stream_is_reissued() -> None:
    bad = FakeStream(["Ich schau"], message([]), fail=True)
    client = FakeClient([bad, text_reply("Fertig.")])
    final = (await run(client))[-1]
    assert isinstance(final, o.Final) and final.turn.text.startswith("Fertig.")
    assert len(client.requests) == 2 and len(client.requests[1]["messages"]) == 2  # nothing appended


def test_echo_content_drops_internal_blocks_before_fallback() -> None:
    msg = message([
        {"type": "thinking", "thinking": "", "signature": "s1"},
        {"type": "text", "text": "partial "},
        {"type": "tool_use", "id": "t1", "name": "search_docs", "input": {"query": "x"}},
        {"type": "fallback", "from": {"model": "claude-sonnet-5-5"}, "to": {"model": "claude-sonnet-5"},
         "trigger": {"type": "refusal", "category": None}},
        {"type": "thinking", "thinking": "", "signature": "s2"},
        {"type": "text", "text": "rest"},
    ])
    echoed = o.echo_content(msg.content)
    assert [b["type"] for b in echoed] == ["text", "fallback", "thinking", "text"]
    assert echoed[1]["from"] == {"model": "claude-sonnet-5-5"}  # alias kept for the wire format
