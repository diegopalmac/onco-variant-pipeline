"""Recover a usable JSON object from a truncated LLM response.

Long reports produce more output than the model returns in one call, so the
response can stop in the middle of the ``variantes`` list. Rather than lose
the whole extraction, we cut the list back to the last complete variant.
"""
import json
import re
from typing import Optional


def repair_truncated_json(raw: str) -> Optional[str]:
    """Return valid JSON that keeps every *complete* variant, or None.

    Heuristic: walk the ``variantes`` list tracking brace depth (ignoring
    braces inside strings) and remember where the last top-level object
    closed. Everything after that point is dropped and the list is closed.
    """
    start = re.search(r'"variantes"\s*:\s*\[', raw)
    if not start:
        return None

    prefix = raw[: start.end()]
    body = raw[start.end():]

    last_complete = -1
    depth = 0
    in_string = False
    for i, char in enumerate(body):
        if char == '"' and (i == 0 or body[i - 1] != "\\"):
            in_string = not in_string
        elif in_string:
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rest = body[i + 1:].lstrip()
                # Only accept the object if it is followed by a separator,
                # the end of the list, or the end of the text.
                if not rest or rest[0] in ",]":
                    last_complete = i

    variants = body[: last_complete + 1] if last_complete != -1 else ""
    candidate = prefix + variants + "]}"
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return candidate
