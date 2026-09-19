
from __future__ import annotations
import re

HEAD = "flowchart TD"


def identifiers(names: list[str]) -> dict[str, str]:
  taken: dict[str, str] = {}
  for name in names:
    identifier = re.sub(r"\W", "_", name)
    while identifier in taken.values():
      identifier += "_"
    taken[name] = identifier
  return taken


def draw(graph: dict) -> str:
  names = sorted(set(graph["clusters"].values()))
  taken = identifiers(names)
  lines = [HEAD]
  lines += [f'  {taken[name]}["{name}"]' for name in names]
  lines += [f"  {taken[source]} --> {taken[target]}"
            for source, target in graph["edges"]]
  return "\n".join(lines)
