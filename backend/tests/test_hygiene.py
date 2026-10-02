"""Guards against shell/heredoc mishaps that silently corrupt regexes: stray control characters in source files."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".venv", "__pycache__", "data"}


class SourceHygieneTests(unittest.TestCase):
    def test_no_stray_control_characters_in_python_or_yaml(self):
        bad = []
        for path in ROOT.rglob("*"):
            if path.suffix not in (".py", ".yaml", ".md") or SKIP & set(path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            if any(ord(c) < 9 or 13 < ord(c) < 32 for c in text):   # a backspace here was once a mangled "\b"
                bad.append(str(path.relative_to(ROOT)))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
