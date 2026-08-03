#!/usr/bin/env python3
"""Validate the standalone HACS repository layout."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "h3x_predictive_dispatch"
REQUIRED_MANIFEST_KEYS = {
    "domain",
    "documentation",
    "issue_tracker",
    "codeowners",
    "name",
    "version",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    custom_components = ROOT / "custom_components"
    integrations = [
        path
        for path in custom_components.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    ]
    if [path.name for path in integrations] != [DOMAIN]:
        raise AssertionError(
            "HACS integration repos must contain exactly "
            f"custom_components/{DOMAIN}"
        )

    manifest_path = custom_components / DOMAIN / "manifest.json"
    manifest = load_json(manifest_path)
    missing = REQUIRED_MANIFEST_KEYS - set(manifest)
    if missing:
        raise AssertionError(f"manifest.json missing keys: {sorted(missing)}")
    if manifest["domain"] != DOMAIN:
        raise AssertionError(f"manifest domain must be {DOMAIN}")
    if str(manifest["version"]).endswith("-dev"):
        raise AssertionError("manifest version must be a release version")
    if "h3x-predictive-dispatch" not in manifest["documentation"]:
        raise AssertionError("manifest documentation points to the wrong repository")
    if "h3x-predictive-dispatch" not in manifest["issue_tracker"]:
        raise AssertionError("manifest issue tracker points to the wrong repository")

    hacs = load_json(ROOT / "hacs.json")
    if not hacs.get("render_readme"):
        raise AssertionError("hacs.json must render README.md")

    for path in (
        ROOT / "README.md",
        custom_components / DOMAIN / "strings.json",
        custom_components / DOMAIN / "translations" / "en.json",
    ):
        if not path.exists():
            raise AssertionError(f"missing required file: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
