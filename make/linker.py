from __future__ import annotations

import os
import pprint
import subprocess

import common.log as logging
from env import Path

from . import config as CONFIG
from .config import (
  BUILD_OUTPUT_PATH,
  LIBRARY_ARCHIVES,
  PREBUILT_MARK,
  LIBRARY_PATH,
  LIBRARY_PRUNES,
  RECORD_SEPARATOR,
  STAGED,
  toolchain,
)

log = logging.initialize()

SUFFIXES = {"binary": STAGED, "library": ".so"}


class Linker:

  def __init__(self, make: Make) -> None:
    self.make = make
    self.root: Path = getattr(self.make, "root")

  def _tools(self) -> dict:
    return getattr(self.make, "toolchain", None) or toolchain()

  def link(self):
    if self.make.errored:
      return
    self.archives()
    self.engine()
    self.builds()
    self.libraries()

  def builds(self):
    for build in getattr(self.make, "builds", []):
      if self.make.errored:
        return
      self._build(build)

  def _build(self, build: dict) -> None:
    name = build["name"]
    objects = self._collect_objects(build["path"])
    if not objects:
      log.info(f"Build {name} is variant-inactive; skipping link")
      return
    if self._hosting(build):
      objects = self._hosted(build, objects)
    else:
      for link in build.get("links") or []:
        objects.extend(self._collect_objects(link))
    first = build is self.make.builds[0] and not self._sharing()
    folded = self._statics() if first else []
    objects.extend(folded)
    command = self._build_command(build, objects, bool(folded))
    returncode, output = self._run_link_command(command)
    if returncode != 0:
      log.error(f"Linkage error: {name}")
      log.error(output.decode("utf-8"))
      self.make.errored = True
    self._write_build_logs(name, command, output)

  def _sharing(self) -> bool:
    return self._tools().get("delivery") == "shared"

  def _hosting(self, build: dict) -> bool:
    return self._sharing() and bool(build.get("host"))

  def _hosted(self, build: dict, objects: list) -> list:
    if build is self.make.builds[0] and build.get("main"):
      objects = [one for one in objects if one == self._main(build)]
    for link in build.get("links") or []:
      if not self._covered(Path(link)):
        objects.extend(self._collect_objects(link))
    return objects

  def _main(self, build: dict) -> str:
    source = Path(build["path"]) / build["main"]
    return str(
      self.root / self.make.mirror / source.parent / f"wip.{source.stem}.o")

  def _covered(self, link: Path) -> bool:
    targets = {Path(one["path"]) for one in getattr(self.make, "libraries", [])}
    if link in targets:
      return False
    first = self.make.builds[0]
    held = [Path(one) for one in first.get("links") or []]
    if first.get("main"):
      held.append(Path(first["path"]))
    return any(link == one or link.is_relative_to(one) for one in held)

  def engine(self) -> None:
    if self.make.errored or not self._sharing():
      return
    first = self.make.builds[0]
    objects: list = []
    for link in first.get("links") or []:
      objects.extend(self._collect_objects(link))
    if first.get("main"):
      objects.extend(
        one for one in self._collect_objects(first["path"])
        if one != self._main(first))
    folded = self._statics()
    command = self._engine_command(sorted(set(objects)) + folded, bool(folded))
    returncode, output = self._run_link_command(command)
    if returncode != 0:
      log.error(f"Linkage error: {self.shared().name}")
      log.error(output.decode("utf-8"))
      self.make.errored = True
    self._write_library_logs(Path(self._tools()["engine"]), command, output)

  def shared(self) -> Path:
    return self.root / self.outputs() / (
      f"{self._tools()['engine']}{self._suffix('library')}")

  def implib(self) -> Path:
    return self.shared().with_name(f"lib{self.shared().name}.a")

  def _engine_command(self, objects: list, folded: bool = False) -> list:
    tools = self._tools()
    os.makedirs(self.shared().parent, exist_ok=True)
    archives = [
      str(self.root / archive)
      for archive in (self._archives() if folded else [])
      if (self.root / archive).exists()
    ]
    return [
      tools["compiler"], "-shared", "-o", str(self.shared()),
      f"-Wl,--out-implib,{self.implib()}", *tools["link_flags"], *objects,
      *archives, *self._libs(), *self._imports(),
    ]

  def _statics(self) -> list:
    objects = []
    for library in getattr(self.make, "libraries", []):
      if library.get("static"):
        objects.extend(self._collect_objects(library["path"]))
    return objects

  def outputs(self) -> Path:
    directory = self._tools()["output"].get("directory")
    if not directory:
      return Path(BUILD_OUTPUT_PATH)
    return Path(directory) / BUILD_OUTPUT_PATH.name

  def _build_command(
    self, build: dict, objects: list, folded: bool = False
  ) -> list:
    tools = self._tools()
    if tools["output"]["kind"] == "web":
      return self._web_command(build, objects, tools)
    output = self.binary(build)
    archives = [
      str(self.root / archive)
      for archive in (self._archives() if folded else [])
      if (self.root / archive).exists()
    ]
    return [
      tools["compiler"],
      "-o",
      str(output),
      *tools["link_flags"],
      *objects,
      *archives,
      *self._imported(build),
      *self._libs(),
      *self._imports(),
    ]

  def _imported(self, build: dict | None = None) -> list:
    if build is not None:
      return [str(self.implib())] if self._hosting(build) else []
    return [str(self.implib())] if self._sharing() else []

  def _suffix(self, kind: str) -> str:
    return self._tools()["output"].get(kind) or SUFFIXES[kind]

  def _imports(self) -> list:
    return ["-l" + name for name in self._tools().get("imports") or []]

  def _libs(self) -> list:
    table = getattr(self.make, "system", None)
    if table is not None:
      self._unrowed(table)
      return CONFIG.flags("--libs", CONFIG.packages(table))
    return [
      arg for lib in self._collect_libs() for arg in self._library_args(lib)]

  def _unrowed(self, table: dict) -> None:
    names: set[str] = set()
    for zone in getattr(self.make, "zones", set()):
      seat = self.root / zone
      if seat.is_dir():
        names |= {entry.name for entry in seat.iterdir()
                  if entry.is_dir() and self._active(entry)}
    for name in sorted(names - set(table)):
      log.warning(
        f"No system package for {name}: libs/<profile>/{name} leaves the"
        " host link line")

  def _library_args(self, lib: Path) -> tuple:
    seat = str(lib.parent)
    stem = "-l" + lib.name[3:].split(".")[0]
    if not self._shared(lib.name):
      return ("-L" + seat, stem)
    return ("-L" + seat, "-Wl,-rpath=" + seat, stem)

  @staticmethod
  def _shared(name: str) -> bool:
    return name.endswith((".so", ".dll")) or ".so." in name

  def _web_command(self, build: dict, objects: list, tools: dict) -> list:
    home = self.root / (tools["output"]["directory"] or "build/web")
    os.makedirs(home, exist_ok=True)
    preloads = [
      flag
      for preload in build.get("preloads") or []
      for flag in ("--preload-file", f"{preload}@/{preload}")
    ]
    return [
      tools["compiler"], "-o", str(home / f"{build['name']}.html"),
      *tools["link_flags"], *preloads, *objects,
    ]

  def _write_build_logs(self, name: str, command: list, stdout: bytes | None) -> None:
    record = self.make.output["builds"].setdefault(name, {"out": b""})
    record["command"] = pprint.pformat(command, indent=2).encode()
    record["out"] += (RECORD_SEPARATOR + stdout + b"\n") if stdout else b""

  def archives(self):
    for library in getattr(self.make, "libraries", []):
      if self.make.errored:
        return
      if library.get("archive") and not library.get("static"):
        self._archive(library)

  def libraries(self):
    for library in getattr(self.make, "libraries", []):
      if self.make.errored:
        return
      if library.get("static") or library.get("archive"):
        continue
      self._library(library)

  def binary(self, build: dict) -> Path:
    seat = self.root / self.outputs()
    os.makedirs(seat, exist_ok=True)
    return seat / f"{build['name']}{self._suffix('binary')}"

  def staged(self, path: Path, artifact: str) -> Path:
    seat = self.root / self.outputs() / path
    os.makedirs(seat, exist_ok=True)
    return seat / artifact

  def _archive(self, library: dict) -> None:
    name = library["name"]
    objects = self._collect_objects(library["path"])
    if not objects:
      log.warning(f"No objects for archive {name}; skipping")
      return
    output = self.staged(library["path"], f"lib{name}.a")
    if os.path.exists(output):
      os.remove(output)
    command = [self._tools()["archiver"], "rcs", str(output), *objects]
    returncode, out = self._run_link_command(command)
    if returncode != 0:
      log.error(f"Archive error: lib{name}.a")
      log.error(out.decode("utf-8"))
      self.make.errored = True
    self._write_library_logs(library["path"], command, out)

  def _library(self, library: dict) -> None:
    name = library["name"]
    objects = self._collect_objects(library["path"])
    if not objects:
      log.warning(f"No objects for library {name}; skipping link")
      return
    command = self._library_command(name, objects, library["path"])
    returncode, output = self._run_link_command(command)
    if returncode != 0:
      log.error(f"Linkage error: lib{name}{self._suffix('library')}")
      log.error(output.decode("utf-8"))
      self.make.errored = True
    self._write_library_logs(library["path"], command, output)

  def _collect_objects(self, path: Path) -> list:
    objects = []
    nested = self._nested(path)
    for directory, subdirectories, files in os.walk(
      self.root / self.make.mirror / path
    ):
      subdirectories[:] = [
        name for name in subdirectories if Path(directory) / name not in nested
      ]
      for file_ in files:
        if file_.endswith(".o") and str(Path(directory) / file_) in self.make.objects:
          objects.append(str(Path(directory) / file_))
    return sorted(objects)

  def _nested(self, path: Path) -> set:
    mirror = self.root / self.make.mirror
    owner = Path(path)
    targets = getattr(self.make, "libraries", []) + getattr(
      self.make, "builds", []
    )
    return {
      mirror / target["path"]
      for target in targets
      if Path(target["path"]) != owner
      and Path(target["path"]).is_relative_to(owner)
    }

  def _library_command(self, name: str, objects: list, path: Path) -> list:
    output = self.staged(path, f"lib{name}{self._suffix('library')}")
    archives = [
      str(self.root / archive)
      for archive in self._archives()
      if (self.root / archive).exists()
    ]
    return [self._tools()["compiler"], "-shared", "-o", str(output),
            *self._bundled(), *objects, *archives, *self._imported(),
            *self._marked(), *self._imports()]

  def _bundled(self) -> list:
    return list(self._tools()["link_flags"]) if self._sharing() else []

  def _write_library_logs(self, path: Path, command: list, stdout: bytes | None) -> None:
    key = str(path).replace(os.sep, ".")
    record = self.make.output["libraries"].setdefault(key, {"out": b""})
    record["command"] = pprint.pformat(command, indent=2).encode()
    record["out"] += (RECORD_SEPARATOR + stdout + b"\n") if stdout else b""

  def _marked(self) -> list:
    table = getattr(self.make, "system", None)
    if table is None:
      return []
    names: list[str] = []
    for archive in LIBRARY_ARCHIVES:
      spelled = Path(str(archive))
      if spelled.parts[0] != PREBUILT_MARK:
        continue
      row = table.get(spelled.parts[1])
      if not row:
        log.warning(
          f"No system package for {spelled.parts[1]}: {archive} leaves the"
          " bundle link line")
        continue
      names += row if isinstance(row, list) else [row]
    return CONFIG.flags("--libs", names)

  def _archives(self) -> list[Path]:
    zone = getattr(self.make, "prebuilt", None)
    resolved = []
    for archive in LIBRARY_ARCHIVES:
      spelled = str(archive)
      if PREBUILT_MARK in spelled:
        if not zone:
          continue
        spelled = spelled.replace(PREBUILT_MARK, str(zone))
      resolved.append(self._seated(Path(spelled)))
    return resolved

  def _seated(self, archive: Path) -> Path:
    outputs = self.outputs()
    if outputs == BUILD_OUTPUT_PATH or not archive.is_relative_to(
      BUILD_OUTPUT_PATH):
      return archive
    return outputs / archive.relative_to(BUILD_OUTPUT_PATH)

  def _active(self, path: Path) -> bool:
    gate = getattr(self.make, "_is_active_variant", None)
    return gate(path) if gate else True

  def _collect_libs(self) -> set:
    libs = set()
    prunes = {self.root / prune for prune in LIBRARY_PRUNES}
    zone = getattr(self.make, "prebuilt", None)
    for other in getattr(self.make, "zones", set()):
      if other != zone:
        prunes.add(self.root / other)
    for directory, subdirectories, files in os.walk(self.root / LIBRARY_PATH):
      subdirectories[:] = [
        name for name in subdirectories
        if Path(directory) / name not in prunes
        and self._active(Path(directory) / name)
      ]
      for file_ in files:
        if self._shared(file_) or file_.endswith(".a"):
          libs.add(Path(directory) / file_)
    return libs

  def _run_link_command(self, command: list) -> tuple[int, bytes]:
    process = subprocess.Popen(
      command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    output, _ = process.communicate()
    return process.returncode, output
