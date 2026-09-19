from __future__ import annotations
import subprocess
import sys
import time

import yaml

from env import ROOT_DIRECTORY, config

TAIL = 40


def merge(base: dict, overlay: dict) -> None:
  for key, value in overlay.items():
    if isinstance(value, dict) and isinstance(base.get(key), dict):
      merge(base[key], value)
    elif isinstance(value, list) and isinstance(base.get(key), list):
      base[key].extend(value)
    else:
      base[key] = value


def configuration() -> dict:
  path = ROOT_DIRECTORY / config.verify.project_config_path
  with open(path, "r", encoding="utf-8") as file:
    loaded = yaml.safe_load(file) or {}
  for pattern in config.verify.overlay_config_paths:
    for found in sorted(ROOT_DIRECTORY.glob(pattern)):
      if found == path:
        continue
      with open(found, "r", encoding="utf-8") as file:
        merge(loaded, yaml.safe_load(file) or {})
  return loaded


def selection(changes: list[str], table: list[dict]) -> dict | None:
  roots: set[str] = set()
  filters: set[str] = set()
  cells: set[str] = set()
  for change in changes:
    entries = [entry for entry in table if change.startswith(entry["prefix"])]
    if not entries:
      return None
    for entry in entries:
      roots.update(entry.get("pytest") or [])
      filters.update(entry.get("golds") or [])
      cells.update(entry.get("matrix") or [])
  return {"pytest": sorted(roots), "golds": sorted(filters),
          "matrix": sorted(cells)}


def changes() -> list[str] | None:
  files: list[str] = []
  for arguments in (
    ["git", "diff", "--name-only", "HEAD"],
    ["git", "ls-files", "--others", "--exclude-standard"],
  ):
    result = subprocess.run(
      arguments, cwd=ROOT_DIRECTORY, capture_output=True, text=True)
    if result.returncode != 0:
      return None
    files += result.stdout.split()
  return files


def run(name: str, command: list[str], directory: str) -> bool:
  if command and command[0] == "python3":
    command = [sys.executable] + command[1:]
  started = time.monotonic()
  result = subprocess.run(
    command, cwd=ROOT_DIRECTORY / directory,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
  elapsed = time.monotonic() - started
  verdict = "PASS" if result.returncode == 0 else "FAIL"
  print(f"verify: {name:<8} {verdict} {elapsed:7.1f}s")
  if result.returncode != 0:
    print("\n".join(result.stdout.splitlines()[-TAIL:]))
  return result.returncode == 0
