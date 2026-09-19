
from __future__ import annotations
import os
import re
from pathlib import Path, PurePosixPath

INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.MULTILINE)
TOP = 10


def sources(root: Path, extensions: set[str]) -> list[str]:
  return sorted(
    path.relative_to(root).as_posix()
    for path in root.rglob("*")
    if path.is_file() and path.suffix in extensions)


def quoted(root: Path, relative: str) -> list[str]:
  text = (root / relative).read_text(encoding="utf-8", errors="replace")
  return INCLUDE.findall(text)


def resolve(relative: str, target: str, known: set[str]) -> str | None:
  home = PurePosixPath(relative).parent
  for candidate in (home / target, PurePosixPath(target)):
    resolved = os.path.normpath(str(candidate))
    if resolved in known:
      return resolved
  return None


def cluster(relative: str, rules: list[dict]) -> str | None:
  for rule in rules:
    if relative.startswith(rule["prefix"]):
      return rule["name"]
  return None


def extract(root: Path, rules: list[dict], extensions: set[str]) -> dict:
  files = sources(root, extensions)
  known = set(files)
  placed = {name: cluster(name, rules) for name in files}
  clusters = {name: placed[name] or name for name in files}
  edges: set[tuple[str, str]] = set()
  includers: dict[str, set[str]] = {name: set() for name in files}
  for name in files:
    for target in quoted(root, name):
      reached = resolve(name, target, known)
      if reached is None:
        continue
      includers[reached].add(name)
      if clusters[name] != clusters[reached]:
        edges.add((clusters[name], clusters[reached]))
  fanin = {name: len(seen) for name, seen in includers.items() if seen}
  return {
    "files": files,
    "clusters": clusters,
    "edges": sorted(edges),
    "fanin": fanin,
    "pairs": sorted({tuple(sorted(edge)) for edge in edges
                     if (edge[1], edge[0]) in edges}),
    "unplaced": sorted(name for name in files if placed[name] is None),
  }


def ranking(fanin: dict[str, int]) -> list[tuple[str, int]]:
  return sorted(fanin.items(), key=lambda entry: (-entry[1], entry[0]))


def report(subtree: str, graph: dict, rules: list[dict]) -> None:
  names = sorted(set(graph["clusters"].values()))
  print(f"graphs: {subtree} — {len(graph['files'])} files,"
        f" {len(names)} clusters, {len(graph['edges'])} edges")
  print("graphs: cluster edges")
  for source, target in graph["edges"]:
    print(f"  {source} -> {target}")
  print(f"graphs: fan-in (top {TOP})")
  for name, count in ranking(graph["fanin"])[:TOP]:
    print(f"  {count:4}  {name}")
  print("graphs: bidirectional pairs")
  if not graph["pairs"]:
    print("  none")
  for source, target in graph["pairs"]:
    print(f"  {source} <-> {target}")
  if rules and graph["unplaced"]:
    print(f"graphs: unplaced files ({len(graph['unplaced'])})")
    for name in graph["unplaced"]:
      print(f"  {name}")
