
from __future__ import annotations
from pathlib import Path

import yaml

from env import ROOT_DIRECTORY, config

PROJECT_CONFIG_PATH:Path = config.graphs.project_config_path
SUPPORTED_EXTENSIONS:set[str] = set(config.graphs.supported_extensions)


def project() -> dict:
  try:
    with open(ROOT_DIRECTORY / PROJECT_CONFIG_PATH, encoding="utf-8") as file:
      return yaml.safe_load(file) or {}
  except OSError:
    return {}


def section(subtree: str, loaded: dict | None = None) -> dict | None:
  if loaded is None:
    loaded = project()
  subtrees = loaded.get("subtrees") or {}
  return subtrees.get(subtree.rstrip("/"))


def extensions(loaded: dict | None = None) -> set[str]:
  if loaded is None:
    loaded = project()
  declared = loaded.get("extensions")
  return set(declared) if declared else set(SUPPORTED_EXTENSIONS)
