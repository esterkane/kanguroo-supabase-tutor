"""Split a tutor reply into the streamed Markdown and its trailing ```json tutor_turn block."""
from __future__ import annotations

import json

from pydantic import ValidationError

from backend.tutor.schemas import TutorTurn

FENCE = "```json tutor_turn"


class TurnParseError(ValueError):
    """The reply has no valid tutor_turn block; the message is sent back to the model for one repair."""


def split_reply(reply: str) -> tuple[str, str | None]:
    """(markdown, json_text or None). Uses the last fence, so earlier examples in the answer don't count."""
    idx = reply.rfind(FENCE)
    if idx < 0:
        return reply.strip(), None
    body = reply[idx + len(FENCE):]
    end = body.find("```")
    return reply[:idx].strip(), (body[:end] if end >= 0 else body).strip()


def parse_turn(markdown: str, json_text: str | None) -> TutorTurn:
    if json_text is None:
        raise TurnParseError(f"no {FENCE} block at the end of the reply")
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise TurnParseError(f"tutor_turn is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise TurnParseError("tutor_turn must be a JSON object")
    data["text"] = markdown  # the app owns `text`: it is what the learner saw stream
    data.pop("guard_flags", None)
    try:
        return TutorTurn.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise TurnParseError(f"tutor_turn does not match the schema: {problems}") from e


class FenceSplitter:
    """Streams text tokens up to (not including) the tutor_turn fence, across chunk boundaries."""

    def __init__(self) -> None:
        self._held = ""
        self._done = False

    def feed(self, chunk: str) -> str:
        if self._done:
            return ""
        buf = self._held + chunk
        idx = buf.find(FENCE)
        if idx >= 0:
            self._done = True
            self._held = ""
            return buf[:idx]
        # Hold back the longest suffix that could still become the fence.
        keep = next((n for n in range(min(len(FENCE) - 1, len(buf)), 0, -1) if FENCE.startswith(buf[-n:])), 0)
        self._held = buf[len(buf) - keep:] if keep else ""
        return buf[: len(buf) - keep]

    def flush(self) -> str:
        out, self._held = ("" if self._done else self._held), ""
        return out
