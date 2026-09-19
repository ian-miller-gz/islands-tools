
from __future__ import annotations


def declared(section: dict) -> dict[str, set[str]]:
  return {source: set(targets or [])
          for source, targets in (section.get("declared") or {}).items()}


def edges(graph: dict, allowed: dict[str, set[str]]) -> list[str]:
  return [f"edge {source} -> {target} is not declared"
          for source, target in graph["edges"]
          if target not in allowed.get(source, set())]


def unplaced(graph: dict) -> list[str]:
  return [f"file {name} matches no cluster rule"
          for name in graph["unplaced"]]


def hubs(graph: dict, section: dict) -> list[str]:
  cap = section.get("fanin")
  if cap is None:
    return []
  spared = set(section.get("hubs") or [])
  return [f"file {name} has {count} includers (cap {cap})"
          for name, count in sorted(graph["fanin"].items())
          if count > cap and name not in spared]


def conform(graph: dict, section: dict) -> list[str]:
  return unplaced(graph) + edges(graph, declared(section)) + hubs(
    graph, section)
