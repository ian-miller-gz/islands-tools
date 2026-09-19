from __future__ import annotations
from verify import runner


def cells(names: list[str], curated: list[str], narrowed: dict | None) -> list[str]:
  if names:
    return names
  if narrowed is None:
    return curated
  relevant = set(narrowed.get("matrix") or [])
  return [cell for cell in curated if cell in relevant]


def matrix(names: list[str], narrowed: dict | None, configuration: dict) -> int:
  stages = configuration.get("stages") or {}
  build, golds = stages.get("build"), stages.get("golds")
  selected = cells(names, configuration.get("matrix") or [], narrowed)
  if not selected:
    print("verify: matrix   SKIP (no selected configurations)")
    print("verify: PASS")
    return 0
  overlay = build.get("configuration")
  if not overlay:
    print("verify: matrix needs a `configuration:` key on the build stage")
    return 1
  print(f"verify: matrix -> {' '.join(selected)}")
  for cell in selected:
    command = build["command"] + overlay + [cell]
    if not runner.run(f"{cell}:build", command, build["directory"]):
      print(f"verify: FAIL ({cell} build)")
      return 1
    command = list(golds["command"])
    chosen = ((configuration.get("cells") or {}).get(cell) or {}).get("golds")
    if chosen is not None:
      if not chosen:
        print(f"verify: {cell}:golds SKIP (the cell declares no golds)")
        continue
      command += (golds.get("filters") or []) + chosen
    elif narrowed is not None:
      if not narrowed["golds"]:
        print(f"verify: {cell}:golds SKIP (no selected tests)")
        continue
      command += (golds.get("filters") or []) + narrowed["golds"]
    if not runner.run(f"{cell}:golds", command, golds["directory"]):
      print(f"verify: FAIL ({cell} golds)")
      return 1
  print("verify: PASS")
  return 0
