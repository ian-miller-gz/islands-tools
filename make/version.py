from __future__ import annotations
import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
KEY = "tools"


def stated() -> str:
  found = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.M)
  return found.group(1) if found else "0.0.0"


def required(config: dict) -> str | None:
  wanted = config.get(KEY)
  return None if wanted is None else str(wanted)


def require(config: dict) -> None:
  wanted = required(config)
  if wanted is None or wanted == stated():
    return
  raise SystemExit(
    f"make: configs/make.yaml requires islands-tools {wanted}, this checkout "
    f"carries {stated()} - move the submodules/islands-tools pin, or the "
    f"requirement, before building")
