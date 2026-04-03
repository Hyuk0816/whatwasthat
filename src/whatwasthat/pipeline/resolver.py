"""대명사 해소 - 지시어/대명사를 실제 명칭으로 치환."""

import re

from whatwasthat.models import Chunk, Turn

_PRONOUN_PATTERNS = [
    r"그걸로",
    r"그거로",
    r"그걸",
    r"그거",
    r"그게",
    r"그것",
    r"그것으로",
]

_NOUN_PATTERN = re.compile(
    r"([\w\-\.]+(?:\s+[\w\-\.]+)?)"
    r"(?:을|를|이|가|은|는|으로|로|에서|에|의|와|과|랑|이랑)"
)


_TECH_NAME_PATTERN = re.compile(r"[A-Z]")


def _extract_last_noun(text: str) -> str | None:
    matches = _NOUN_PATTERN.findall(text)
    if not matches:
        return None
    # Prefer tokens that look like proper/technical names (contain uppercase letters)
    tech_matches = [m.strip() for m in matches if _TECH_NAME_PATTERN.search(m)]
    if tech_matches:
        return tech_matches[-1]
    return matches[-1].strip()


def _find_referent(turns: list[Turn], current_idx: int) -> str | None:
    for i in range(current_idx - 1, -1, -1):
        if turns[i].role == "assistant":
            noun = _extract_last_noun(turns[i].content)
            if noun:
                return noun
    return None


def resolve_references(chunk: Chunk) -> Chunk:
    """Chunk 내 대명사/지시어를 실제 명칭으로 치환."""
    new_turns: list[Turn] = []
    changed = False

    for idx, turn in enumerate(chunk.turns):
        content = turn.content
        for pattern in _PRONOUN_PATTERNS:
            if re.search(pattern, content):
                referent = _find_referent(chunk.turns, idx)
                if referent:
                    content = re.sub(pattern, referent, content, count=1)
                    changed = True
                    break
        new_turns.append(Turn(role=turn.role, content=content, timestamp=turn.timestamp))

    if not changed:
        return chunk

    raw_text = "\n".join(f"[{t.role}]: {t.content}" for t in new_turns)
    return Chunk(
        id=chunk.id,
        session_id=chunk.session_id,
        turns=new_turns,
        raw_text=raw_text,
        timestamp=chunk.timestamp,
    )
