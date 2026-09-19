from __future__ import annotations
import argparse
import sys

from verify import diagnostics, matrix, runner


def narrow(changed: bool, configuration: dict) -> dict | None:
  narrowed = None
  if changed:
    files = runner.changes()
    if files is not None:
      narrowed = runner.selection(files, configuration.get("changed") or [])
    if narrowed is None:
      print("verify: cross-cutting or unreadable diff; running the full suite")
    else:
      print(f"verify: changed -> pytest {narrowed['pytest'] or '[]'}"
            f" golds {narrowed['golds'] or '[]'}")
  return narrowed


def verify(changed: bool) -> int:
  configuration = runner.configuration()
  stages = configuration.get("stages") or {}
  narrowed = narrow(changed, configuration)

  if not diagnostics.weights(configuration.get("weights") or []):
    print("verify: FAIL (weights)")
    return 1

  if not diagnostics.hygiene(configuration.get("hygiene") or {}):
    print("verify: FAIL (hygiene)")
    return 1

  build = stages.get("build")
  if build and not runner.run("build", build["command"], build["directory"]):
    print("verify: FAIL (build)")
    return 1

  tests = stages.get("pytest")
  if tests:
    roots = narrowed["pytest"] if narrowed is not None else tests.get("roots") or []
    if roots:
      if not runner.run("pytest", tests["command"] + roots, tests["directory"]):
        print("verify: FAIL (pytest)")
        return 1
    else:
      print("verify: pytest   SKIP (no selected roots)")

  golds = stages.get("golds")
  if golds:
    command = list(golds["command"])
    if narrowed is not None:
      if not narrowed["golds"]:
        print("verify: golds    SKIP (no selected tests)")
        print("verify: PASS")
        return 0
      command += (golds.get("filters") or []) + narrowed["golds"]
    if not runner.run("golds", command, golds["directory"]):
      print("verify: FAIL (golds)")
      return 1

  print("verify: PASS")
  return 0


def main() -> int:
  parser = argparse.ArgumentParser(
    prog="verify",
    description="Build, pytest roots, and gold suite as one command.")
  parser.add_argument(
    "--changed", action="store_true",
    help="narrow the test stages by the working diff (build always runs; "
         "an empty diff tests nothing, an unmatched path runs everything)")
  parser.add_argument(
    "--matrix", nargs="*", metavar="NAME",
    help="build and gold-test the named configurations (default: the "
         "curated matrix list) instead of the plain run; composes with "
         "--changed, which also narrows the cell list")
  parser.add_argument(
    "--hygiene", action="store_true",
    help="run the gold-hygiene gate alone (update.sh's bake-time call)")
  parser.add_argument(
    "--logs", action="store_true",
    help="print the build logs, newest first, record separators translated")
  parser.add_argument(
    "--syntax", metavar="FILE",
    help="syntax-check one translation unit with the project's include flags")
  parser.add_argument(
    "--configuration", metavar="CELL",
    help="compose --syntax/--command under a named configurations: cell — "
         "its toolchain's compiler and flags, its tokens rendered ahead of "
         "the bench's generated headers (a cross platform's twin is "
         "compile-checked before any link exists)")
  parser.add_argument(
    "--command", action="store_true",
    help="print the project compile command head, one part per line — the "
         "declared channel a sibling tool composes its own compile passes "
         "from")
  arguments = parser.parse_args()
  if arguments.command:
    return diagnostics.head(arguments.configuration)
  if arguments.hygiene:
    configuration = runner.configuration()
    return 0 if diagnostics.hygiene(configuration.get("hygiene") or {}) else 1
  if arguments.logs:
    return diagnostics.logs()
  if arguments.syntax:
    return diagnostics.syntax(arguments.syntax, arguments.configuration)
  if arguments.matrix is not None:
    configuration = runner.configuration()
    narrowed = narrow(arguments.changed, configuration)
    return matrix.matrix(arguments.matrix, narrowed, configuration)
  return verify(arguments.changed)


if __name__ == "__main__":
  sys.exit(main())
