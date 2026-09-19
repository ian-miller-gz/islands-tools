from __future__ import annotations
import argparse
import sys

from env import ROOT_DIRECTORY
from graphs import config, conformer, extractor, mermaid


def rules(section: dict | None) -> list[dict]:
  return (section or {}).get("clusters") or []


def extracted(subtree: str, section: dict | None) -> dict | None:
  root = ROOT_DIRECTORY / subtree
  if not root.is_dir():
    print(f"graphs: no such subtree: {subtree}")
    return None
  return extractor.extract(root, rules(section), config.extensions())


def extract(subtree: str, drawing: bool) -> int:
  section = config.section(subtree)
  graph = extracted(subtree, section)
  if graph is None:
    return 1
  if drawing:
    print(mermaid.draw(graph))
  else:
    extractor.report(subtree, graph, rules(section))
  return 0


def conform(subtree: str) -> int:
  section = config.section(subtree)
  if not (section or {}).get("declared"):
    print(f"graphs: {subtree} declares no graph in"
          f" {config.PROJECT_CONFIG_PATH} — conformance is opt-in per"
          f" subtree, never silently vacuous")
    return 1
  graph = extracted(subtree, section)
  if graph is None:
    return 1
  failures = conformer.conform(graph, section)
  for failure in failures:
    print(f"graphs: {failure}")
  print(f"graphs: conform {'FAIL' if failures else 'PASS'} {subtree}")
  return 1 if failures else 0


def main() -> int:
  parser = argparse.ArgumentParser(
    prog="graphs",
    description="The include graph of a subtree, extracted and conformed.")
  verbs = parser.add_subparsers(dest="verb", required=True)
  drawn = verbs.add_parser(
    "extract", help="print the subtree's cluster graph as it is")
  drawn.add_argument("subtree", help="the root-relative subtree to read")
  drawn.add_argument(
    "--mermaid", action="store_true",
    help="emit the flowchart instead of the report — the drawing a review "
         "or an order file carries")
  checked = verbs.add_parser(
    "conform", help="fail on an edge, a file, or a hub the design "
                    "does not declare")
  checked.add_argument("subtree", help="the root-relative subtree to read")
  arguments = parser.parse_args()
  if arguments.verb == "extract":
    return extract(arguments.subtree, arguments.mermaid)
  return conform(arguments.subtree)


if __name__ == "__main__":
  sys.exit(main())
