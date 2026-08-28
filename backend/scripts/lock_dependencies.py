"""Render the existing plain pin lockfiles from pip's complete resolution reports.

See README for the two reproducible pip --dry-run --ignore-installed commands.
Reports stay under the ignored .venv directory; they can contain local paths.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def render(kind: str) -> str:
    lock = ROOT / f"requirements-{kind}.lock"
    existing = {
        normalize(line.split("==")[0]): line.split("==")[0]
        for line in lock.read_text().splitlines()
        if "==" in line
    }
    report: dict[str, Any] = json.loads((ROOT / f".venv/{kind}-resolution.json").read_text())
    if report["environment"]["python_version"] != "3.12":
        raise ValueError("Lock generation requires Python 3.12")
    pins = {}
    for item in report["install"]:
        metadata = item["metadata"]
        name = metadata["name"]
        if normalize(name) != "regops-api":
            pins[existing.get(normalize(name), name)] = metadata["version"]
    return "".join(f"{name}=={pins[name]}\n" for name in sorted(pins, key=str.lower))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {kind: render(kind) for kind in ("runtime", "dev")}
    if not set(outputs["runtime"].splitlines()) <= set(outputs["dev"].splitlines()):
        raise ValueError("Runtime/development pins disagree")
    for kind, text in outputs.items():
        path = ROOT / f"requirements-{kind}.lock"
        if args.check:
            if path.read_text() != text:
                sys.exit(f"Lock differs from resolution: {path.name}")
        else:
            path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
