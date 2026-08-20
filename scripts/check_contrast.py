#!/usr/bin/env python3
"""Check every theme's WCAG-AA text/background contrast.

Every text pair a theme renders must clear 4.5:1 (body text, text on
accent/selection, status on the backdrop, header on both gradient
stops, pressed/checked, and the button gradient stop). Derived states
are checked through the same resolvers the QSS uses.

The placeholder color (accent2) is reported as a WARNING: it is not
AA-required yet because 21 shipped themes predate it. It does not
affect the exit code.

Usage:
    python3 scripts/check_contrast.py                 # all themes
    python3 scripts/check_contrast.py --theme "Atom Blue"
    python3 scripts/check_contrast.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "packages" / "podracer_db" / "src"))

from podracer.themes import (  # noqa: E402
    HIDDEN_THEMES,
    THEMES,
    Theme,
    contrast_checks,
    placeholder_ratio,
    theme_by_name,
)

MIN_RATIO = 4.5


def all_themes() -> list[Theme]:
    """Visible themes plus the hidden system themes, both checked."""
    return THEMES + HIDDEN_THEMES


def check(theme: Theme) -> dict[str, object]:
    results = []
    for label, fg, bg, ratio in contrast_checks(theme):
        results.append({
            "pair": label,
            "foreground": fg,
            "background": bg,
            "ratio": round(ratio, 2),
            "pass": ratio >= MIN_RATIO,
        })
    placeholder = {
        "pair": "placeholder (accent2)",
        "foreground": theme.accent2,
        "background": theme.panel_bg,
        "ratio": round(placeholder_ratio(theme), 2),
        "pass": placeholder_ratio(theme) >= MIN_RATIO,
    }
    return {"theme": theme.name, "checks": results, "placeholder": placeholder}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", metavar="NAME",
                        help="check only this theme (by exact name)")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of a table")
    args = parser.parse_args()

    if args.theme:
        themes = [theme_by_name(args.theme)]
    else:
        themes = all_themes()

    reports = [check(t) for t in themes]
    failures = [r for r in reports if not all(c["pass"] for c in r["checks"])]
    warnings = [r for r in reports if not r["placeholder"]["pass"]]

    if args.json:
        print(json.dumps({
            "min_ratio": MIN_RATIO,
            "themes": reports,
            "aa_failures": [r["theme"] for r in failures],
            "placeholder_warnings": [r["theme"] for r in warnings],
        }, indent=2))
    else:
        for r in reports:
            status = "PASS" if all(c["pass"] for c in r["checks"]) else "FAIL"
            print(f"{r['theme']}: {status}")
            for c in r["checks"]:
                mark = "ok " if c["pass"] else "FAIL"
                print(f"    {mark} {c['pair']:<22} {c['ratio']:5.2f}:1  "
                      f"{c['foreground']} on {c['background']}")
            if not r["placeholder"]["pass"]:
                print(f"    warn placeholder (accent2) "
                      f"{r['placeholder']['ratio']:5.2f}:1  "
                      f"(not AA-required yet)")
        print()
        if failures:
            print(f"{len(failures)} theme(s) FAIL AA:")
            for r in failures:
                print(f"  - {r['theme']}")
            return 1
        summary = (f"All {len(reports)} theme(s) pass WCAG-AA.  "
                   f"{len(warnings)} theme(s) have sub-AA placeholder "
                   f"warning(s).")
        print(summary)
        return 0


if __name__ == "__main__":
    sys.exit(main())
