from __future__ import annotations
import getpass
import re
import subprocess
import time
from pathlib import Path

from env import ROOT_DIRECTORY
from make import api
from make.config import LOG_PATH, RECORD_SEPARATOR

ADDRESS = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:'\"]+)", re.IGNORECASE)


def logs() -> int:
  directory = ROOT_DIRECTORY / LOG_PATH
  records = sorted(
    directory.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
  if not records:
    print(f"verify: no build logs under {directory}")
    return 1
  for record in records:
    print(f"==== {record.name} ====")
    print(record.read_bytes().replace(RECORD_SEPARATOR, b"\n").decode("utf-8"))
  return 0


def command(configuration: str | None = None) -> list[str]:
  return api.compile_head(configuration) + ["-fsyntax-only"]


def head(configuration: str | None = None) -> int:
  for part in api.compile_head(configuration):
    print(part)
  return 0


def weights(table: list[dict]) -> bool:
  started = time.monotonic()
  head = api.preprocess_head()
  failures: list[str] = []
  for entry in table:
    result = subprocess.run(
      head + [str(ROOT_DIRECTORY / entry["header"])],
      capture_output=True, text=True, cwd=ROOT_DIRECTORY)
    lines = result.stdout.count("\n")
    if result.returncode != 0:
      failures.append(f"{entry['header']} failed to preprocess")
    elif lines > entry["lines"]:
      failures.append(
        f"{entry['header']} weighs {lines} preprocessed lines"
        f" (budget {entry['lines']})")
  elapsed = time.monotonic() - started
  verdict = "FAIL" if failures else "PASS"
  print(f"verify: weights  {verdict} {elapsed:7.1f}s")
  for failure in failures:
    print(f"verify: {failure}")
  return not failures


def violations(line: str, identity: list, forbidden: list, allowed: list) -> list[str]:
  found: list[str] = []
  for pattern, name in identity:
    if pattern.search(line):
      found.append(f"carries the baking {name}")
  for name, pattern in forbidden:
    if pattern.search(line):
      found.append(f"matches the forbidden pattern ({name})")
  hosts = ADDRESS.findall(line) + [m.group(1) for m in URL.finditer(line)]
  for host in hosts:
    if not any(pattern.search(host) for pattern in allowed):
      found.append(f"names an unreserved host ({host})")
  return found


def hygiene(table: dict) -> bool:
  started = time.monotonic()
  user, home = getpass.getuser(), str(Path.home())
  identity = [
    (re.compile(rf"\b{re.escape(user)}\b"), f"user name ({user})"),
    (re.compile(re.escape(home)), f"home directory ({home})")]
  forbidden = [(entry["name"], re.compile(entry["regex"]))
               for entry in table.get("forbidden") or []]
  allowed = [re.compile(entry) for entry in table.get("allowed_hosts") or []]
  failures: list[str] = []
  for root in table.get("roots") or []:
    for path in sorted((ROOT_DIRECTORY / root).rglob("*")):
      if path.suffix not in (table.get("extensions") or []):
        continue
      name = (path.relative_to(ROOT_DIRECTORY)
              if path.is_relative_to(ROOT_DIRECTORY) else path)
      lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
      for number, line in enumerate(lines, 1):
        for finding in violations(line, identity, forbidden, allowed):
          failures.append(f"{name}:{number} {finding}")
  elapsed = time.monotonic() - started
  verdict = "FAIL" if failures else "PASS"
  print(f"verify: hygiene  {verdict} {elapsed:7.1f}s")
  for failure in failures:
    print(f"verify: {failure}")
  return not failures


def syntax(file: str, configuration: str | None = None) -> int:
  try:
    head = command(configuration)
  except LookupError as refusal:
    print(f"verify: syntax FAIL {file} ({refusal})")
    return 1
  result = subprocess.run(head + [str(ROOT_DIRECTORY / file)], cwd=ROOT_DIRECTORY)
  cell = f" [{configuration}]" if configuration else ""
  print(f"verify: syntax {'PASS' if result.returncode == 0 else 'FAIL'} {file}{cell}")
  return result.returncode
