"""Source files must not contain invisible control or bidirectional characters.

Such characters can make code look different from what it does ("Trojan
Source"). Where tests or code need them, they are written as escape sequences.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVISIBLE = (
    {c for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}
    | set(range(0x7F, 0xA0))
    | {0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2028, 0x2029, 0xFEFF}
    | set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
)
SUFFIXES = {".py", ".json", ".md", ".toml", ".txt", ""}


def test_no_invisible_or_bidi_characters_in_sources() -> None:
    offenders: list[str] = []
    checked = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in {".git", "__pycache__", ".pytest_cache", "build", "dist"} or part.endswith(".egg-info") for part in path.parts):
            continue
        text = path.read_text("utf-8")
        checked += 1
        for number, line in enumerate(text.split("\n"), 1):
            for char in line:
                if ord(char) in INVISIBLE:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: U+{ord(char):04X}")
    assert checked > 30
    assert offenders == []
