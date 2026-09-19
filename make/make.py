from __future__ import annotations
import hashlib
import os
import shutil
import time

from common.yaml import yaml

import common.log as logging
from env import Path, Tree

from .compiler import Compiler
from .initializer import Initializer
from .linker import Linker
from .precompiler import Precompiler

log = logging.initialize()

from . import config as CONFIG


class Make(Initializer):

  def __init__(self, configuration: str | None = None):
    self.configuration = configuration
    self.initialize()
    self.compiler = Compiler(self)
    self.linker = Linker(self)
    self.precompiler = Precompiler(self)

  def _tools(self) -> dict:
    return getattr(self, "toolchain", None) or CONFIG.toolchain()

  def assemble(self):
    pass

  def compile(self, metadata: Tree | None = None, path: Path = Path("")):
    return self.compiler.compile(metadata=metadata, path=path)

  def clear(self):
    log.info("Clearing working files...")
    self._write_logs()
    self.promote()
    if self.errored:
      log.warning("Build errored; cache not updated")
      return
    self._update_cache()
    self._write_cache()
    log.info("Complete 'Clearing working files'!")

  def link(self):
    return self.linker.link()

  def copy_output(self):
    if self.errored:
      log.warning("Build errored; skipping output copy")
      return

    output = self._tools()["output"]
    outputs = self.root / self.linker.outputs()
    if output["kind"] == "native":
      binary = output["binary"]
      delivered = "" if binary == CONFIG.STAGED else binary
      for build in getattr(self, "builds", []):
        src_binary = outputs / f"{build['name']}{binary}"
        self._copy_artifact(
          src_binary, f"{build['name']}{delivered}", build["destinations"])
      self._copy_engine(outputs)
    else:
      self._copy_page()

    for library in getattr(self, "libraries", []):
      if library.get("static"):
        continue
      suffix = ".a" if library.get("archive") else output["library"]
      name = f"lib{library['name']}{suffix}"
      src_library = outputs / library["path"] / name
      self._copy_artifact(src_library, name, library["destinations"])

  def _copy_engine(self, outputs: Path) -> None:
    if self._tools().get("delivery") != "shared":
      return
    builds = getattr(self, "builds", [])
    if not builds:
      return
    library = self.linker.shared().name
    self._copy_artifact(outputs / library, library, builds[0]["destinations"])

  def _copy_page(self) -> None:
    selected = self._bundle(self._project_config())
    if selected is None:
      return
    home = self.root / (self._tools()["output"]["directory"] or "")
    for build in getattr(self, "builds", []):
      if not build["destinations"]:
        continue
      for artifact in sorted(home.glob(f"{build['name']}.*")):
        self._copy_artifact(artifact, artifact.name, [selected[0]])

  def _home(self, directory: str) -> Path:
    home = self.root / directory
    fold = getattr(self, "fold", "")
    manifest = (self._project_config().get("manifest") or {}).get("path")
    if not fold or not manifest or not (home / manifest).exists():
      return home
    return home / fold

  def _copy_artifact(self, source, name: str, destinations: list) -> None:
    if not source.exists():
      log.warning(f"Artifact not found at {source}; skipping copy")
      return
    for dest_dir in destinations:
      home = self._home(dest_dir)
      dest_path = home / name
      try:
        os.makedirs(home, exist_ok=True)
        shutil.copy2(source, dest_path)
        log.info(f"Copied {source.name} to {dest_path}")
      except Exception as e:
        log.error(f"Failed to copy to {dest_path}: {e}")

  def precompile(self):
    return self.precompiler.precompile()

  def preprocess(self):
    if self.errored:
      log.error("Configuration refused; skipping preprocess")
      return
    self._python_preprocess()
    self.stamp = time.time()
    self._set_updated_files()

  def promote(self):
    pass

  def _python_preprocess(self):
    try:
      from .preprocessor import Preprocessor
      Preprocessor(self).generate()
    except Exception as e:
      log.error(f"Preprocessor failed: {e}")
      self.errored = True

  def _write_cache(self):
    log.info("Writing metadata cache...")
    with (
      open(self.root / self.mirror / CONFIG.BUILD_CACHE_NAME, "w") as file
    ):
      yaml.safe_dump(self.cache, file, indent=2)
    log.info("Complete 'Writing metadata cache'!")

  def _write_file(self, filename: str, data: bytes | None) -> None:
    if not data:
      return
    path = self.root / CONFIG.LOG_PATH / filename
    with open(path, "w") as file:
      file.write(data.decode("utf-8"))

  def _write_logs(self):
    self._write_file("compile.out.log", self.output["compile"]["out"])
    self._write_file("compile.err.log", self.output["compile"]["err"])
    for records in ("builds", "libraries"):
      for name, record in self.output.get(records, {}).items():
        self._write_file(f"link.{name}.out.log", record["out"])
        self._write_file(f"link.{name}.command.log", record.get("command"))

  def _set_updated_files(
    self, cache: Tree | None = None, metadata: Tree | None = None,
    path: Path = Path("")
  ):
    cache = cache if cache is not None else self.cache
    assert cache is not None
    metadata = metadata if metadata is not None else self.metadata

    def recur(key: str) -> bool:
      nonlocal cache
      return isinstance(metadata[key], dict) and isinstance(cache.get(key), dict)

    for key in list(metadata.keys()):
      if recur(key):
        log.debug(f"Pushing {key}")
        self._set_updated_files(
          cache=cache[key], metadata=metadata[key], path=path / key)
      elif cache.get(key) is None and isinstance(metadata[key], dict):
        cache[key] = metadata[key]
      elif self._fresh(cache.get(key), metadata[key], path / key):
        log.debug(f"Popping {key}")
        metadata.pop(key)
      else:
        log.info(f"Recompiling {key}: {metadata[key]}")

  def _fresh(self, entry, mtime: float, path: Path) -> bool:
    if not isinstance(entry, list) or len(entry) != 2:
      return False
    stamp, fingerprint = entry
    if mtime > stamp:
      return False
    if path.suffix != ".cpp":
      return True
    if fingerprint != self._fingerprint(path):
      return False
    dependencies = self._dependencies(path)
    if dependencies is None:
      return False
    return all(self._time(dependency) <= stamp for dependency in dependencies)

  def _fingerprint(self, path: Path) -> str:
    cached = self.prints.get(str(path))
    if cached is None:
      parts = [self._tools()["compiler"], *self._tools()["standard"]]
      parts += [str(flag) for flag in self.flags]
      flags = self.compiler._flags(path)
      parts += [str(flag) for flag in flags]
      parts += [str(flag) for flag in self.compiler._prefix(path, flags)]
      parts += [str(root) for root in self.roots]
      parts += sorted(str(include) for include in self.include_paths)
      cached = hashlib.sha256(" ".join(parts).encode("utf-8")).hexdigest()
      self.prints[str(path)] = cached
    return cached

  def _dependencies(self, path: Path) -> list[str] | None:
    record = self._object(path).with_suffix(".d")
    try:
      text = record.read_text(encoding="utf-8")
    except OSError:
      return None
    _, _, names = text.replace("\\\n", " ").partition(":")
    return names.split()

  def _time(self, path: str) -> float:
    cached = self.times.get(path)
    if cached is None:
      try:
        cached = os.path.getmtime(path)
      except OSError:
        cached = float("inf")
      self.times[path] = cached
    return cached

  def _update_cache(
    self, cache: Tree | None = None, metadata: Tree | None = None,
    path: Path = Path("")
  ):
    cache = cache if cache is not None else self.cache
    metadata = metadata if metadata is not None else self.metadata
    for key, value in metadata.items():
      if isinstance(value, dict):
        if isinstance(cache.get(key), dict):
          self._update_cache(
            metadata=metadata[key], cache=cache[key], path=path / key)
      else:
        file_ = path / key
        fingerprint = self._fingerprint(file_) if file_.suffix == ".cpp" else ""
        cache[key] = [self.stamp, fingerprint]
        log.info(f"Updating cache {key}".ljust(40, " ") + f"{self.stamp}")
