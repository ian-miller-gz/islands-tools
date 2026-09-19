from __future__ import annotations
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import common.log as logging
from env import Tree

from . import config as CONFIG
from .config import RECORD_SEPARATOR, toolchain

log = logging.initialize()


class Compiler:

  def __init__(self, make: "Make") -> None:
    self.make = make
    self.log = getattr(make, "log", None)
    self.output = getattr(make, "output", None)
    self.errored = getattr(make, "errored", False)
    self.root = getattr(make, "root", None)
    self.includes = getattr(make, "includes", set())
    self.include_paths = getattr(make, "include_paths", set())

  def _tools(self) -> dict:
    return getattr(self.make, "toolchain", None) or toolchain()

  def _system(self) -> list:
    return CONFIG.flags(
      "--cflags", CONFIG.packages(getattr(self.make, "system", None)))

  def compile(self, metadata: Tree | None = None, path: Path = Path("")):
    if self.make.errored:
      return
    metadata = metadata if metadata is not None else self.make.metadata
    self._drain(self._pending(metadata, path))

  def _pending(self, metadata: Tree, path: Path) -> list[tuple[Path, list]]:
    pending: list[tuple[Path, list]] = []
    for key, value in metadata.items():
      _, extension = os.path.splitext(key)
      if isinstance(value, dict):
        pending += self._pending(value, path / key)
      elif extension == ".cpp":
        file_path = self.make.root / path / key
        wip_path = self.make._object(path / Path(key))
        log.info(f"parsing metadata, key: {key}, path: {wip_path}")
        flags = self._flags(path / key)
        command = self._build_command(
          file_path, wip_path, flags + self._prefix(path / key, flags))
        pending.append((file_path, command))
    return pending

  def _drain(self, pending: list[tuple[Path, list]]) -> None:
    halt = Event()

    def work(entry: tuple[Path, list]) -> tuple[int, bytes] | None:
      if halt.is_set():
        return None
      returncode, output = self._run_compile_command(entry[1])
      if returncode != 0:
        halt.set()
      return returncode, output

    with ThreadPoolExecutor(max_workers=self._width()) as pool:
      results = list(pool.map(work, pending))
    for (file_path, _), result in zip(pending, results):
      if result is None:
        continue
      returncode, output = result
      if returncode != 0:
        log.error(f"Compilation error: {file_path}")
        log.error(output.decode("utf-8"))
        self.make.errored = True
        return
      self._write_compile_logs(output, None)

  def _width(self) -> int:
    configured = getattr(self.make, "workers", None)
    return max(1, int(configured or os.cpu_count() or 1))

  def _flags(self, path: Path) -> list:
    flags: list = []
    codegen = self._tools()["library_flags"]
    for library in getattr(self.make, "libraries", []):
      if path.is_relative_to(library["path"]):
        flags = [] if library.get("static") else list(codegen)
        break
    return flags + self._defines(path)

  def _prefix(self, path: Path, flags: list) -> list:
    options: list = []
    for entry in getattr(self.make, "precompiled", []):
      subtrees = entry.get("subtrees") or []
      if not any(path.is_relative_to(subtree) for subtree in subtrees):
        continue
      codegen = self._tools()["library_flags"]
      pic = bool(codegen) and flags[:len(codegen)] == codegen
      flavour = "pic" if pic else "plain"
      seat = self.make.precompiler.seat(Path(entry["header"]), flavour)
      options += ["-include", str(seat), "-Winvalid-pch"]
      if CONFIG.clang(self._tools()["compiler"]):
        continue
      options += ["-fpch-deps"]
    return options

  def _defines(self, path: Path) -> list:
    targets = list(getattr(self.make, "libraries", [])) + list(
      getattr(self.make, "builds", []))
    matches = [
      target for target in targets
      if target.get("defines") and path.is_relative_to(target["path"])
    ]
    if not matches:
      return []
    deepest = max(matches, key=lambda target: len(Path(target["path"]).parts))
    return list(deepest["defines"])

  def _build_command(
    self, file_path: Path, wip_path: Path, flags: tuple | list = ()
  ) -> list:
    tools = self._tools()
    base = [tools["compiler"], *tools["standard"],
            *tools.get("compile_flags", []), str(file_path),
            "-c", "-MD", "-o", str(wip_path)]
    return (
      base
      + list(getattr(self.make, "flags", []))
      + list(flags)
      + self._system()
      + [
        arg
        for combined_arg in [["-isystem", str(root)] for root in self.make.roots]
        for arg in combined_arg
      ]
      + ["-I" + str(include) for include in self.make.include_paths]
    )

  def _run_compile_command(self, command: list) -> tuple[int, bytes]:
    log.debug(f"Piping > STDOUT, STDERR:\n{command}")
    process = subprocess.Popen(
      command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output, _ = process.communicate()
    return process.returncode, output

  def _write_compile_logs(self, stdout: bytes | None, stderr: bytes | None) -> None:
    self.make.output["compile"]["out"] += (
      (RECORD_SEPARATOR + stdout + b"\n") if stdout else b"")
    self.make.output["compile"]["err"] += (
      (RECORD_SEPARATOR + stderr + b"\n") if stderr else b"")
