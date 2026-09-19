from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import yaml

import common.log as logging
import make.config as CONFIG
from env import ROOT_DIRECTORY, Tree

from .metadata import Metadata

log = logging.initialize()


STATIC = 0


def names(fragment: str, text: str) -> bool:
  parts = [part for part in fragment.split("/") if part]
  words = [word for word in text.split("/") if word]
  if not parts or len(parts) > len(words):
    return False
  return any(words[at:at + len(parts)] == parts
             for at in range(len(words) - len(parts) + 1))


def carries(value: str) -> bool:
  for at, letter in enumerate(value):
    if letter == ":" and (at + 1 == len(value) or value[at + 1].isspace()):
      return True
  return False


def flat(text: str) -> str:
  rendered = []
  for line in text.splitlines():
    bare = line.split("#", 1)[0]
    colon = bare.find(":")
    value = bare[colon + 1:].strip() if colon >= 0 else ""
    if not carries(value):
      rendered.append(bare)
      continue
    quoted = value.replace("\\", "\\\\").replace('"', '\\"')
    rendered.append(f'{bare[:colon]}: "{quoted}"')
  return "\n".join(rendered)


class Initializer:
  def initialize(self) -> None:
    global STATIC
    STATIC += 1
    log.info(f"Initializing make... {STATIC}")
    self.root: Path = ROOT_DIRECTORY
    log.info(f"\nMake project root:{self.root}")
    self.metadata = {}
    self.cache = {}
    self.files = []
    self.wips = set()
    self.includes = set()
    self.include_paths = set()
    self.objects = set()
    self.prints = {}
    self.times = {}
    self.stamp = time.time()
    self.errored = False
    self.system = self._system()
    self._provisioned()
    self.toolchain = self._toolchain()
    self.prebuilt, self.zones = self._prebuilt()
    self._generate_include_paths()
    self.output = {
      "compile": {"out": b"", "err": b""},
      "libraries": {},
      "builds": {},
    }
    os.makedirs(self.root / CONFIG.LOG_PATH, exist_ok=True)
    os.makedirs(self.root / CONFIG.BUILD_PATH, exist_ok=True)
    os.makedirs(self.root / CONFIG.BUILD_OUTPUT_PATH, exist_ok=True)
    self.flags = self._flags()
    self.workers = self._project_config().get("workers")
    self.precompiled = self._project_config().get("precompiled") or []
    self.zone = self._zone()
    self.mirror = CONFIG.BUILD_OBJECT_PATH / self.zone
    os.makedirs(self.root / self.mirror, exist_ok=True)
    log.info(f"Configuration zone: {self.zone}")
    self.fold = self._fold()
    self.libraries = self._libraries()
    self.builds = self._builds()
    self._parse_metadata()
    for library in self.libraries:
      self._parse_metadata(self.root / library["path"])
    for build in self.builds:
      self._parse_metadata(self.root / build["path"])
    self.roots = self._roots()
    self._read_cache()
    log.info("Complete 'Initializing make'!")

  def survey(self) -> None:
    self.root = ROOT_DIRECTORY
    self.includes = set()
    self.errored = False
    self.system = self._system()
    self._provisioned()
    self.toolchain = self._toolchain()
    self.prebuilt, self.zones = self._prebuilt()
    self._generate_include_paths()
    self.flags = self._flags()
    self._scan(self.root / CONFIG.SOURCE_PATH)
    for target in self._libraries() + self._builds():
      self._scan(self.root / target["path"])
    self.roots = self._roots()

  def _scan(self, subtree: Path) -> None:
    for directory, _, files in os.walk(subtree):
      directory = Path(os.path.normpath(directory))
      if not self._is_active_variant(directory):
        continue
      for file in files:
        if Path(file).suffix == ".hpp":
          self.includes.add(directory / file)

  def _system(self) -> dict | None:
    return CONFIG.system(self._tokens(self._project_config()))

  def _provisioned(self) -> None:
    if self.system is None:
      return
    for kind in ("--cflags", "--libs"):
      try:
        CONFIG.flags(kind, CONFIG.packages(self.system))
      except CONFIG.Refused as refusal:
        log.error(str(refusal))
        self.errored = True

  def _prebuilt(self) -> tuple[Path | None, set[Path]]:
    block = CONFIG.PREBUILT
    options = block.get("options") or {}
    zones = {Path(zone) for zone in options.values()}
    for entry in CONFIG.TOOLCHAINS.values():
      zones |= {Path(zone) for zone in ((entry or {}).get("prebuilt") or {}).values()}
    own = (getattr(self, "toolchain", None) or {}).get("prebuilt")
    if own:
      options = own
    if getattr(self, "system", None) is not None:
      log.info("Prebuilt zone: the distribution's (pkg-config)")
      return None, zones
    selected = self._tokens(self._project_config()).get(block.get("selector"))
    chosen = options.get(selected)
    if chosen:
      log.info(f"Prebuilt zone: {chosen}")
    return (Path(chosen) if chosen else None), zones

  def _generate_include_paths(self):
    self.include_paths: set[Path] = {
      self.root / CONFIG.GENERATED_PATH,
    }
    zone = getattr(self, "prebuilt", None)
    if zone:
      for root in sorted((self.root / zone).glob("*/include")):
        if root.is_dir() and self._is_active_variant(root):
          self.include_paths.add(root)
    for entry in self._project_config().get("includes") or []:
      root = self.root / entry
      if not self._is_active_variant(root):
        continue
      if not root.is_dir():
        log.warning(
          f"Include root missing: {entry} — is the submodule checked out?")
      self.include_paths.add(root)

  def _roots(self) -> list[Path]:
    declared = sorted(
      (self.root / subtree
       for subtree in self._project_config().get("roots") or []),
      key=lambda path: len(path.parts), reverse=True)
    roots: set[Path] = set()
    for header in self.includes:
      root = next(
        (subtree for subtree in declared if header.is_relative_to(subtree)),
        header.parent)
      roots.add(root)
    return sorted(roots)

  def _read_cache(self):
    if os.path.exists(self.root / self.mirror / CONFIG.BUILD_CACHE_NAME):
      cache = open(self.root / self.mirror / CONFIG.BUILD_CACHE_NAME, "r")
      self.cache: Tree = yaml.safe_load(cache) or {}
      cache.close()
    else:
      log.info("Cache does not exists. Creating new build.")

  def _parse_files(self, directory: Path, files: list[Path]) -> None:
    parts = (path := directory.relative_to(self.root)).parts
    head = self.metadata
    for part in parts:
      if head.get(part):
        head = head[part]
        continue
      head[part] = {}
      head = head[part]
    supported = (f for f in files if f.suffix in CONFIG.SUPPORTED_EXTENSIONS)
    for file_ in supported:
      if not self._is_active_variant(directory / file_):
        continue
      head[str(file_)] = Metadata(directory / file_).timestamp
      if file_.suffix == ".hpp":
        self.includes.add(directory / file_)
      if file_.suffix == ".cpp":
        self.objects.add(str(self._object(path / file_)))

  def _parse_metadata(self, metadata: Path | None = None) -> None:
    log.info("Parsing files...")
    metadata = metadata or (self.root / CONFIG.SOURCE_PATH)
    for directory, subdirectories, files in os.walk(metadata):
      directory = Path(os.path.normpath(directory))
      subpath = self.mirror / directory.relative_to(self.root)
      files = [Path(f) for f in files]
      os.makedirs(self.root / subpath, exist_ok=True)
      if not self._is_active_variant(directory):
        continue
      self._parse_files(directory, files)
    log.debug(
      f"Found the following headers {'\n\t'.join((str(i) for i in self.includes))}"
    )
    log.info("Complete 'Parsing files'!")

  def _object(self, path: Path) -> Path:
    return self.root / self.mirror / path.parent / f"wip.{path.stem}.o"

  def _project_config(self) -> Tree:
    cached = getattr(self, "_project_cfg", None)
    if cached is not None:
      return cached
    return self._resolve()

  def project(self) -> Tree:
    return self._project_config()

  def _resolve(self) -> Tree:
    config: Tree = {}
    path = self.root / CONFIG.PROJECT_CONFIG_PATH
    try:
      with open(path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    except Exception as error:
      log.warning(f"Could not read make config {path}: {error}")
    self._configure(config)
    self._overlay(config)
    self._vet(config)
    self._residents(config)
    self._project_cfg = config
    return config

  def _residents(self, config: Tree) -> None:
    for path in (self.root / entry for entry in CONFIG.OVERLAY_CONFIG_PATHS):
      try:
        with open(path, "r", encoding="utf-8") as file:
          overlay = yaml.safe_load(file) or {}
      except OSError:
        continue
      if not isinstance(overlay, dict):
        log.warning(f"Ignoring overlay config (not a mapping): {path}")
        continue
      for section in ("builds", "libraries"):
        entries = overlay.get(section) or []
        if entries:
          config.setdefault(section, []).extend(entries)
          log.info(f"Overlay config: +{len(entries)} {section} from {path}")

  def _configure(self, config: Tree) -> None:
    name = getattr(self, "configuration", None)
    if not name:
      return
    entries = config.get("configurations") or {}
    if name not in entries:
      log.error(f"Unknown configuration '{name}' (have: {sorted(entries)})")
      self.errored = True
      return
    tokens = self._tokens(config)
    vocabulary = self._spellings(config)
    for token, value in (entries[name] or {}).items():
      known = vocabulary.get(token)
      members = value if isinstance(value, list) else [value]
      strange = known is not None and any(one not in known for one in members)
      if token not in tokens or not members or strange:
        log.error(f"Configuration '{name}': unknown token '{token}: {value}'")
        self.errored = True
        continue
      if isinstance(value, list) and "SR_NONE" in value:
        log.error(
          f"Configuration '{name}': SR_NONE is exclusive — a set cannot"
          f" carry it ({token}: {value})")
        self.errored = True
        continue
      self._assign(config, token, value)
      self._origin(token, f"configuration '{name}'")
      log.info(f"Axis {token} = {value} (configuration '{name}')")

  @staticmethod
  def _spellings(config: Tree) -> dict:
    vocabulary = config.get("manifest") or {}
    known: dict = {}
    for axis in (vocabulary.get("axes") or {}).values():
      known[axis["token"]] = set((axis.get("values") or {}).values())
    for entry in (vocabulary.get("keys") or {}).values():
      values = set((entry.get("values") or {}).values())
      values.add(entry.get("absent"))
      known[entry["token"]] = values
    return known

  def _overlay(self, config: Tree) -> None:
    vocabulary = config.get("manifest") or {}
    selected = self._bundle(config)
    if selected is None:
      return
    bundle, static = selected
    self._declare(config, static, bundle)
    if not (vocabulary.get("axes") or vocabulary.get("keys")):
      return
    file = vocabulary.get("path") or "manifest.yaml"
    neutral = self._document(self.root / bundle / file)
    fold = self._folded(config, vocabulary, neutral, bundle)
    delta = self._delta(vocabulary, neutral, fold, bundle)
    document = self._merge(neutral, delta)
    section = self._section(document, vocabulary, bundle)
    stated = self._section(delta, vocabulary, bundle) if delta else {}
    origin = Path(bundle).name
    for key, value in section.items():
      axis = (vocabulary.get("axes") or {}).get(key)
      if key == (vocabulary.get("folds") or {}).get("axis"):
        value = fold
      spelled = self._spelled(axis, value)
      if axis is None or spelled is None:
        log.error(f"{bundle} manifest: unknown axis '{key}: {value}'")
        self.errored = True
        continue
      if isinstance(value, list) and "none" in value:
        log.error(
          f"{bundle} manifest: none is exclusive — a set cannot carry it"
          f" ({key}: {value})")
        self.errored = True
        continue
      self._assign(config, axis["token"], spelled)
      self._origin(
        axis["token"], f"{origin}'s {fold} fold" if key in stated else origin)
    self._adopt(config, vocabulary, document, bundle)
    self._provenance(config, vocabulary, section, document, bundle)

  def _folded(
    self, config: Tree, vocabulary: Tree, document: Tree, bundle: str
  ) -> str:
    axis = (vocabulary.get("folds") or {}).get("axis")
    composed = self._fold(config)
    if not axis:
      return composed
    stated = self._section(document, vocabulary, bundle).get(axis)
    if isinstance(stated, list) and stated:
      return composed if composed in stated else stated[0]
    return stated if isinstance(stated, str) else composed

  def _delta(
    self, vocabulary: Tree, document: Tree, fold: str, bundle: str
  ) -> Tree:
    folds = vocabulary.get("folds") or {}
    section = folds.get("section")
    deltas = document.get(section) if section else None
    if not isinstance(deltas, dict):
      return {}
    known = ((vocabulary.get("axes") or {}).get(folds.get("axis")) or {}).get(
      "values") or {}
    for name in deltas:
      if name in known:
        continue
      log.error(f"{bundle} manifest: '{section}:' names no platform '{name}'")
      self.errored = True
    stated = deltas.get(fold) or {}
    if stated:
      log.info(f"Manifest fold {fold}: {bundle} states {sorted(stated)}")
    return stated

  @staticmethod
  def _merge(base: Tree, delta: Tree) -> Tree:
    merged = dict(base)
    for key, value in (delta or {}).items():
      if isinstance(value, dict) and isinstance(merged.get(key), dict):
        merged[key] = Initializer._merge(merged[key], value)
      else:
        merged[key] = value
    return merged

  def _declare(self, config: Tree, static: Tree, bundle: str) -> None:
    declaration = static.get("bundle")
    if declaration is None:
      return
    group = declaration.get("group")
    directive = declaration.get("directive")
    if not group or not directive:
      log.error(f"statics bundle declaration needs group/directive: {declaration}")
      self.errored = True
      return
    config.setdefault("directives", {}).setdefault(group, {})[directive] = bundle

  def _document(self, path: Path) -> Tree:
    try:
      with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(flat(file.read())) or {}
    except OSError:
      return {}
    return data if isinstance(data, dict) else {}

  def _section(self, document: Tree, vocabulary: Tree, bundle: str) -> Tree:
    name = vocabulary.get("section")
    if not name:
      log.error("manifest vocabulary: no 'section:' names the mapping to read")
      self.errored = True
      return {}
    section = document.get(name) or {}
    if isinstance(section, dict):
      return section
    log.error(f"{bundle} manifest: '{name}:' is not a mapping")
    self.errored = True
    return {}

  def _adopt(
    self, config: Tree, vocabulary: Tree, document: Tree, bundle: str
  ) -> None:
    for key, entry in (vocabulary.get("keys") or {}).items():
      if key not in document:
        self._assign(config, entry["token"], entry.get("absent"))
        continue
      spelled = (entry.get("values") or {}).get(document[key])
      if spelled is None:
        log.error(f"{bundle} manifest: unknown key '{key}: {document[key]}'")
        self.errored = True
        continue
      self._assign(config, entry["token"], spelled)
      self._origin(entry["token"], Path(bundle).name)

  def _vet(self, config: Tree) -> None:
    vocabulary = config.get("manifest") or {}
    axes = vocabulary.get("axes") or {}
    spelled = self._composed(config, axes)
    for setting, values in (vocabulary.get("compatibility") or {}).items():
      for value, rule in (values or {}).items():
        if value not in spelled.get(setting, []):
          continue
        self._enforce(f"`{setting}: {value}`", rule or {}, spelled, axes)

  def _composed(self, config: Tree, axes: Tree) -> dict:
    tokens = self._tokens(config)
    spelled: dict = {}
    for key, axis in axes.items():
      inverse = {t: s for s, t in (axis.get("values") or {}).items()}
      value = tokens.get(axis["token"])
      members = value if isinstance(value, list) else [value]
      spelled[key] = [inverse[m] for m in members if m in inverse]
    return spelled

  def _enforce(
    self, clause: str, rule: Tree, spelled: dict, axes: Tree
  ) -> None:
    for key, admitted in (rule.get("admits") or {}).items():
      for one in spelled.get(key, []):
        if one in admitted:
          continue
        allowed = ", ".join(admitted)
        self._collide(axes, key, one, f"{clause} admits only `{key}: {allowed}`")
    for key, refused in (rule.get("refuses") or {}).items():
      for one in spelled.get(key, []):
        if one not in refused:
          continue
        self._collide(axes, key, one, f"{clause} refuses `{key}: {one}`")

  def _origin(self, token: str, source: str) -> None:
    self.__dict__.setdefault("origins", {})[token] = source

  def _collide(self, axes: Tree, key: str, spelling: str, rule: str) -> None:
    token = (axes.get(key) or {}).get("token")
    origin = getattr(self, "origins", {}).get(token, "the bench default")
    log.error(f"{origin} demands `{key}: {spelling}`; {rule} — refused")
    self.errored = True

  def _provenance(
    self, config: Tree, vocabulary: Tree, section: Tree, document: Tree,
    bundle: str
  ) -> None:
    tokens = self._tokens(config)
    for key, axis in (vocabulary.get("axes") or {}).items():
      source = f"{bundle} manifest" if key in section else "bench default"
      log.info(f"Axis {axis['token']} = {tokens.get(axis['token'])} ({source})")
    for key, entry in (vocabulary.get("keys") or {}).items():
      source = f"'{key}:' stated" if key in document else f"no '{key}:' key"
      log.info(
        f"Axis {entry['token']} = {tokens.get(entry['token'])}"
        f" ({bundle} manifest, {source})")

  def _fold(self, config: Tree | None = None) -> str:
    config = self._project_config() if config is None else config
    vocabulary = config.get("manifest") or {}
    axis = (vocabulary.get("folds") or {}).get("axis")
    if not axis:
      return ""
    spelled = self._composed(config, vocabulary.get("axes") or {})
    members = spelled.get(axis) or []
    return members[0] if members else ""

  def _bundle(self, config: Tree) -> tuple[str, Tree] | None:
    tokens = self._tokens(config)
    for static in config.get("statics") or []:
      selected = tokens.get(static.get("selector"))
      for subtree, value in (static.get("options") or {}).items():
        if selected == value:
          return subtree, static
    return None

  @staticmethod
  def _spelled(axis, value):
    spellings = (axis or {}).get("values") or {}
    if isinstance(value, list):
      mapped = [spellings.get(member) for member in value]
      return None if not mapped or None in mapped else mapped
    return spellings.get(value)

  @staticmethod
  def _assign(config: Tree, token: str, value) -> None:
    tokens = config.setdefault("tokens", {})
    for group in tokens.values():
      if isinstance(group, dict) and token in group:
        group[token] = value
        return
    tokens[token] = value

  def _toolchain(self) -> dict:
    config = self._project_config()
    tokens = self._tokens(config)
    block = config.get("toolchain") or {}
    selected = tokens.get(block.get("selector"))
    self.toolchain_name = (block.get("options") or {}).get(selected)
    return CONFIG.toolchain(self.toolchain_name, tokens)

  def _zone(self) -> str:
    config = self._project_config()
    parts = sorted(f"{k}={v}" for k, v in self._tokens(config).items())
    parts += sorted(
      f"{k}={v}" for k, v in self._flatten(config, "directives").items())
    parts += [str(flag) for flag in self.flags]
    if getattr(self, "toolchain_name", None):
      parts.append(f"toolchain={self.toolchain_name}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]

  def _libraries(self) -> list[Tree]:
    libraries: list[Tree] = []
    for entry in self._project_config().get("libraries") or []:
      name = entry.get("name")
      path = entry.get("path")
      if not name or not path:
        log.warning(f"Ignoring library entry without name/path: {entry}")
        continue
      libraries.append({
        "name": name,
        "path": Path(path),
        "destinations": entry.get("output_destinations") or [],
        "static": self._is_static(path),
        "archive": bool(entry.get("archive")),
        "defines": self._defines(entry),
      })
    delivery = (getattr(self, "toolchain", None) or {}).get("delivery")
    if delivery == "static":
      libraries = [one for one in libraries if one["static"] or one["archive"]]
    elif delivery == "shared":
      libraries = [one for one in libraries
                   if one["static"] or one["archive"] or self._ships(one)]
    return libraries

  def _ships(self, library: Tree) -> bool:
    config = self._project_config()
    vocabulary = config.get("manifest") or {}
    axis = (vocabulary.get("folds") or {}).get("axis")
    file = vocabulary.get("path")
    if not axis or not file:
      return False
    document = self._document(self.root / library["path"] / file)
    if not document:
      return False
    stated = self._section(document, vocabulary, str(library["path"])).get(axis)
    folds = stated if isinstance(stated, list) else [stated]
    return (getattr(self, "fold", None) or self._fold()) in folds

  def _builds(self) -> list[Tree]:
    builds: list[Tree] = []
    for entry in self._project_config().get("builds") or []:
      name = entry.get("name")
      path = entry.get("path")
      if not name or not path:
        log.warning(f"Ignoring build entry without name/path: {entry}")
        continue
      builds.append({
        "name": name,
        "path": Path(path),
        "links": [Path(link) for link in entry.get("links") or []],
        "destinations": entry.get("output_destinations") or [],
        "defines": self._defines(entry),
        "preloads": entry.get("preloads") or [],
        "main": entry.get("main"),
        "host": bool(entry.get("host")),
      })
    return builds

  def _defines(self, entry: Tree) -> list[str]:
    tokens = entry.get("tokens") or {}
    defines = [f"-D{name}={value}" for name, value in tokens.items()]
    for name, value in (entry.get("directives") or {}).items():
      if isinstance(value, bool):
        defines += [f"-D{name}=1"] if value else []
      elif isinstance(value, (int, float)):
        defines.append(f"-D{name}={value}")
      else:
        text = str(value)
        if not text.startswith(('"', "'")):
          text = f'"{text}"'
        defines.append(f"-D{name}={text}")
    return defines

  def _flags(self) -> list[str]:
    flags: list[str] = []
    config = self._project_config()
    tokens = self._tokens(config)
    for entry in config.get("flags") or []:
      selected = tokens.get(entry.get("selector"))
      options = entry.get("options") or {}
      for member in selected if isinstance(selected, list) else [selected]:
        flags.extend(options.get(member) or [])
    return flags

  @staticmethod
  def _tokens(config: Tree) -> dict:
    return Initializer._flatten(config, "tokens")

  @staticmethod
  def _flatten(config: Tree, mapping: str) -> dict:
    flat: dict = {}
    for name, value in (config.get(mapping) or {}).items():
      if isinstance(value, dict):
        flat.update(value)
      else:
        flat[name] = value
    return flat

  def _is_static(self, path: str) -> bool:
    text = str(path).replace("\\", "/")
    config = self._project_config()
    tokens = self._tokens(config)
    for static in config.get("statics") or []:
      selected = tokens.get(static.get("selector"))
      for subtree, value in (static.get("options") or {}).items():
        if subtree in text:
          return selected == value
    return False

  def _is_active_variant(self, path: Path) -> bool:
    text = str(path).replace("\\", "/")
    config = self._project_config()
    tokens = self._tokens(config)
    for variant in config.get("variants") or []:
      selected = tokens.get(variant.get("selector"))
      for subtree, value in (variant.get("options") or {}).items():
        if names(subtree, text):
          values = value if isinstance(value, list) else [value]
          chosen = selected if isinstance(selected, list) else [selected]
          return any(one in values for one in chosen)
    return True
