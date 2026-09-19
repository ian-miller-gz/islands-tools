from __future__ import annotations
import hashlib
import shutil
import subprocess
import time
from pathlib import Path

import yaml

import common.log as logging

from . import config as CONFIG
from .config import RECORD_SEPARATOR, toolchain

log = logging.initialize()

FLAVOURS: tuple[str, ...] = ("plain", "pic")


class Precompiler:

  def __init__(self, make) -> None:
    self.make = make

  def _tools(self) -> dict:
    return getattr(self.make, "toolchain", None) or toolchain()

  def _system(self) -> list[str]:
    return CONFIG.flags(
      "--cflags", CONFIG.packages(getattr(self.make, "system", None)))

  def _codegen(self, flavour: str) -> list[str]:
    if flavour == "pic":
      return list(self._tools()["library_flags"])
    return []

  def precompile(self) -> None:
    if self.make.errored:
      return
    for entry in getattr(self.make, "precompiled", []):
      header = Path(entry.get("header", ""))
      if not (self.make.root / header).exists():
        continue
      for flavour in self._flavours():
        self._realize(header, flavour)

  def seat(self, header: Path, flavour: str) -> Path:
    return (
      self.make.root / self.make.mirror / "precompiled" / flavour / header)

  def _flavours(self) -> list[str]:
    if any(not library.get("static") for library in self.make.libraries):
      return list(FLAVOURS)
    return ["plain"]


  def _realize(self, header: Path, flavour: str) -> None:
    seat = self.seat(header, flavour)
    output = seat.with_name(seat.name + ".gch")
    fingerprint = self._fingerprint(flavour)
    if self._fresh(seat, output, fingerprint):
      log.info(f"Precompiled header current: {output}")
      return
    seat.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(self.make.root / header, seat)
    log.info(f"Precompiling {header} ({flavour}) -> {output}")
    process = subprocess.run(
      self._command(seat, output, flavour), capture_output=True)
    if process.returncode != 0:
      output.unlink(missing_ok=True)
      self._meta(seat).unlink(missing_ok=True)
      log.warning(
        f"Precompile failed for {header} ({flavour}); compiling without it:\n"
        f"{process.stderr.decode('utf-8')}")
      self.make.output["compile"]["err"] += (
        RECORD_SEPARATOR + process.stderr + b"\n")
      return
    with open(self._meta(seat), "w") as file:
      yaml.safe_dump([time.time(), fingerprint], file)

  def _fresh(self, seat: Path, output: Path, fingerprint: str) -> bool:
    try:
      with open(self._meta(seat), "r", encoding="utf-8") as file:
        entry = yaml.safe_load(file)
    except OSError:
      return False
    if not isinstance(entry, list) or len(entry) != 2:
      return False
    stamp, printed = entry
    if printed != fingerprint or not output.exists():
      return False
    try:
      text = output.with_suffix(".d").read_text(encoding="utf-8")
    except OSError:
      return False
    _, _, names = text.replace("\\\n", " ").partition(":")
    return all(self.make._time(name) <= stamp for name in names.split())

  def _fingerprint(self, flavour: str) -> str:
    parts = [self._tools()["compiler"], *self._tools()["standard"]]
    parts += self._tools().get("compile_flags", [])
    parts += [str(flag) for flag in self.make.flags]
    parts += self._codegen(flavour)
    parts += self._system()
    parts += [str(root) for root in self.make.roots]
    parts += sorted(str(include) for include in self.make.include_paths)
    return hashlib.sha256(" ".join(parts).encode("utf-8")).hexdigest()

  def _command(self, seat: Path, output: Path, flavour: str) -> list[str]:
    return (
      [self._tools()["compiler"], *self._tools()["standard"]]
      + self._tools().get("compile_flags", [])
      + [str(flag) for flag in self.make.flags]
      + self._codegen(flavour)
      + self._system()
      + ["-x", "c++-header", str(seat), "-c", "-MD", "-o", str(output)]
      + [
        arg
        for combined in [["-isystem", str(root)] for root in self.make.roots]
        for arg in combined
      ]
      + ["-I" + str(include) for include in self.make.include_paths]
    )

  def _meta(self, seat: Path) -> Path:
    return seat.with_name(seat.name + ".yaml")
