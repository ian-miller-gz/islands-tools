from __future__ import annotations
import functools
import os
import shlex
import subprocess
from pathlib import Path

import yaml

import common.log as logging
from env import ROOT_DIRECTORY, config

log = logging.initialize()

SOURCE_PATH   :Path = config.paths.source_path
BUILD_PATH    :Path = config.paths.build_path
BUILD_OUTPUT_PATH:Path = BUILD_PATH / 'outputs'
BUILD_OBJECT_PATH:Path = BUILD_PATH / 'objects'
BUILD_CACHE_NAME:str = 'cache.yaml'
PROJECT_CONFIG_PATH:Path = config.make.project_config_path
OVERLAY_CONFIG_PATHS:list[Path] = [
  Path(entry)
  for entry in config.make.overlay_config_paths]
GENERATED_PATH:Path = BUILD_PATH / 'include'
LIBRARY_PATH  :Path = config.paths.library_path
LIBRARY_PRUNES:list[Path] = [
  Path(entry)
  for entry in config.paths.library_prune]
LOG_PATH      :Path = config.paths.log_path / BUILD_PATH
SUPPORTED_EXTENSIONS:set[str] = \
  set(config.make.supported_extensions)
RECORD_SEPARATOR = chr(30).encode()


def _policy() -> dict:
  try:
    with open(ROOT_DIRECTORY / PROJECT_CONFIG_PATH, encoding='utf-8') as file:
      return yaml.safe_load(file) or {}
  except OSError:
    return {}


_POLICY = _policy()
COMPILER:str = _POLICY.get('compiler') or 'g++'
ARCHIVER:str = _POLICY.get('archiver') or 'ar'
STANDARD:list[str] = (
  [f"-std={_POLICY['standard']}"] if _POLICY.get('standard') else [])
LINK_FLAGS:list[str] = list(_POLICY.get('link_flags') or [])
LIBRARY_FLAGS:list[str] = list(_POLICY.get('library_flags') or [])
COMPILE_FLAGS:list[str] = list(_POLICY.get('compile_flags') or [])
LIBRARY_ARCHIVES:list[Path] = [
  Path(entry)
  for entry in (_POLICY.get('library_archives') or [])]
PREBUILT:dict = _POLICY.get('prebuilt') or {}
PREBUILT_MARK:str = '<prebuilt>'
SYSTEM:dict = _POLICY.get('system') or {}


def system(tokens: dict) -> dict | None:
  if not SYSTEM:
    return None
  if tokens.get(SYSTEM.get('selector')) != SYSTEM.get('value'):
    return None
  return SYSTEM.get('packages') or {}


def packages(table: dict | None) -> list[str]:
  names: list[str] = []
  for entry in (table or {}).values():
    names += entry if isinstance(entry, list) else [entry]
  return names


def flags(kind: str, names: list[str]) -> list[str]:
  return [argument for name in names for argument in _query(kind, name)]


class Refused(RuntimeError):
  pass


@functools.lru_cache(maxsize=None)
def _query(kind: str, name: str) -> tuple[str, ...]:
  command = [os.environ.get('PKG_CONFIG') or 'pkg-config', kind, name]
  try:
    process = subprocess.run(command, capture_output=True)
  except OSError as refusal:
    raise Refused(
      f"pkg-config is the system zone's only door: {refusal}") from refusal
  if process.returncode != 0:
    raise Refused(
      f"pkg-config refused {kind} for {name}: "
      f"{process.stderr.decode('utf-8', 'replace').strip()}")
  return tuple(shlex.split(process.stdout.decode('utf-8')))

@functools.lru_cache(maxsize=None)
def clang(compiler: str) -> bool:
  if "clang" in compiler or "emcc" in compiler:
    return True
  try:
    process = subprocess.run([compiler, "--version"], capture_output=True)
  except OSError:
    return False
  return b"clang" in process.stdout.split(b"\n", 1)[0]

TOOLCHAINS:dict = _POLICY.get('toolchains') or {}
STAGED:str = '.out'


def toolchain(name: str | None = None, tokens: dict | None = None) -> dict:
  resolved:dict = {
    'compiler': COMPILER,
    'archiver': ARCHIVER,
    'standard': list(STANDARD),
    'compile_flags': list(COMPILE_FLAGS),
    'link_flags': list(LINK_FLAGS),
    'library_flags': list(LIBRARY_FLAGS),
    'imports': [],
    'prebuilt': {},
    'delivery': 'dynamic',
    'engine': None,
    'output': {
      'kind': 'native', 'directory': None, 'binary': STAGED, 'library': '.so'},
  }
  block = (TOOLCHAINS.get(name) or {}) if name else {}
  for key in ('compiler', 'archiver'):
    if block.get(key):
      resolved[key] = block[key]
  if block.get('standard'):
    resolved['standard'] = [f"-std={block['standard']}"]
  for key in ('compile_flags', 'link_flags', 'library_flags', 'imports'):
    if key in block:
      resolved[key] = list(block[key] or [])
  resolved['prebuilt'] = dict(block.get('prebuilt') or {})
  if block.get('delivery'):
    resolved['delivery'] = delivery(block['delivery'], tokens or {})
  if block.get('engine'):
    resolved['engine'] = block['engine']
  output = block.get('output') or {}
  for key in ('kind', 'directory', 'binary', 'library'):
    if output.get(key):
      resolved['output'][key] = output[key]
  return resolved


def delivery(stated, tokens: dict) -> str:
  if not isinstance(stated, dict):
    return str(stated)
  options = stated.get('options') or {}
  chosen = options.get(tokens.get(stated.get('selector')))
  if chosen:
    return str(chosen)
  return str(next(iter(options.values()), 'dynamic'))
