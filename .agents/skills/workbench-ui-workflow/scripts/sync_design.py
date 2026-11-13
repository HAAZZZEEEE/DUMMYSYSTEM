#!/usr/bin/env python3
"""Render Interface Design's native file from the canonical Workbench spec."""
import argparse
import hashlib
from pathlib import Path


def render(source: bytes) -> bytes:
    digest = hashlib.sha256(source).hexdigest()
    header = (
        "<!-- Generated from ../DESIGN.md; do not edit independently.\n"
        f"Source SHA-256: {digest}\n"
        "Update the canonical spec after an accepted decision, then run sync_design.py. -->\n\n"
    )
    return header.encode() + source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    app = args.app_root.resolve()
    source = app / "DESIGN.md"
    target = app / ".interface-design/system.md"
    expected = render(source.read_bytes())
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Design projection differs; inspect changes before syncing.\n")
        print("Design projection matches canonical DESIGN.md.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(expected)
        print(f"Updated {target}")


if __name__ == "__main__":
    main()
