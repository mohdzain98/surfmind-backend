# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

"""Add the SurfMind licence header to Python source files.

Covers every `*.py` under `src/` and `scripts/`, skipping `.venv`,
`__pycache__`, `migrations/versions/`, and empty files. Adds the header
where missing and rewrites an existing one whose text differs, so editing
HEADER and rerunning updates every file. `--check` changes nothing and
exits 1 if any file is missing or has an outdated header.
"""

import re
import sys
from pathlib import Path

HEADER = (
    "# Copyright (c) 2025 Mohd Zain. SurfMind Backend.\n"
    "# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).\n"
    "# Commercial use requires a separate license: "
    "https://surfmind.docschat.in/contact\n"
)
MARKER = "PolyForm Noncommercial"
ROOTS = ("src", "scripts")
SKIP_PARTS = {".venv", "__pycache__"}
# PEP 263 — a plain comment that merely mentions "coding" must not match.
ENCODING_LINE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")
TOP_LEVEL_DEF = ("def ", "async def ", "class ", "@")


def should_skip(path: Path) -> bool:
    """Whether `path` is outside the set of files that get a header."""
    parts = set(path.parts)
    return bool(parts & SKIP_PARTS) or "migrations/versions" in path.as_posix()


def _prefix_len(lines: list[str]) -> int:
    """Number of leading shebang/encoding lines the header must sit after."""
    keep = 0
    if lines and lines[0].startswith("#!"):
        keep = 1
    if len(lines) > keep and ENCODING_LINE.match(lines[keep]):
        keep += 1
    return keep


def _existing_header_end(lines: list[str], start: int) -> int | None:
    """End index of a header block (any version) at `start`, else None.

    A header is the run of `#` lines starting with the copyright line and
    containing the marker — matched by shape, not exact text, so an older
    wording is still recognised and replaced.
    """
    if start >= len(lines) or not lines[start].startswith("# Copyright (c)"):
        return None
    end = start
    while end < len(lines) and lines[end].startswith("#"):
        end += 1
    return end if MARKER in "".join(lines[start:end]) else None


def add_header(text: str) -> str:
    """Return `text` with the header after any shebang/encoding lines."""
    lines = text.splitlines(keepends=True)
    keep = _prefix_len(lines)
    rest = "".join(lines[keep:])
    # black wants two blank lines between a comment block and a top-level
    # def/class (one is enough before a docstring or import).
    separator = "\n\n" if rest.startswith(TOP_LEVEL_DEF) else "\n"
    return "".join(lines[:keep]) + HEADER + separator + rest


def apply_header(text: str) -> tuple[str, str | None]:
    """Return `(new_text, action)`; action is "added", "updated", or None."""
    lines = text.splitlines(keepends=True)
    keep = _prefix_len(lines)
    end = _existing_header_end(lines, keep)
    if end is not None:
        if "".join(lines[keep:end]) == HEADER:
            return text, None
        new = "".join(lines[:keep]) + HEADER + "".join(lines[end:])
        return new, "updated"
    if MARKER in text:
        return text, None
    return add_header(text), "added"


def main() -> int:
    """Add/update (or with `--check`, report) headers; return exit code."""
    check = "--check" in sys.argv
    pending: list[tuple[Path, str]] = []
    for root in ROOTS:
        for path in sorted(Path(root).rglob("*.py")):
            if should_skip(path):
                continue
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            new_text, action = apply_header(text)
            if action is None:
                continue
            pending.append((path, action))
            if not check:
                path.write_text(new_text, encoding="utf-8")
    labels = {"added": "missing", "updated": "outdated"}
    for path, action in pending:
        print(f"{labels[action] if check else action}: {path}")
    return 1 if (check and pending) else 0


if __name__ == "__main__":
    sys.exit(main())
