"""Write the package version into the README banner (tests/test_help_008.py checks it).

Usage: python scripts/sync_readme_version.py   (run after setting the version in pyproject.toml)
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    # Keep the banner's column alignment: the replacement has the same width when lengths match.
    updated = re.sub(r"(NetConverter\s+)v\d+\.\d+\.\d+", lambda m: f"{m.group(1)}v{version}", text)
    if updated != text:
        readme.write_text(updated, encoding="utf-8")
    print(f"README.md banner: v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
