from __future__ import annotations
import copy
import os
from pathlib import Path
from common import NoSql, Tree


CONFIGS_DIRECTORY = os.environ.get('ISLANDS_CONFIGS', 'configs')


def rooted(candidate: Path) -> bool:
  return ((candidate / '.git').exists()
          or (candidate / CONFIGS_DIRECTORY / 'make.yaml').is_file())


def root() -> Path:
  path = Path.cwd().resolve()
  for candidate in (path, *path.parents):
    if rooted(candidate):
      return candidate
  return path


ROOT_DIRECTORY = root()

DEFAULTS: dict = {
  'log': {'level': 20},
  'make': {
    'project_config_path': f'{CONFIGS_DIRECTORY}/make.yaml',
    'overlay_config_paths': ['hosts/builds.yaml'],
    'supported_extensions': ['.cpp', '.hpp', '.c', '.h', '.hh', '.cxx'],
  },
  'verify': {
    'project_config_path': f'{CONFIGS_DIRECTORY}/verify.yaml',
    'overlay_config_paths': [f'{CONFIGS_DIRECTORY}/*/verify.yaml'],
  },
  'graphs': {
    'project_config_path': f'{CONFIGS_DIRECTORY}/graphs.yaml',
    'supported_extensions': ['.cpp', '.hpp', '.c', '.h', '.hh', '.cxx'],
  },
  'paths': {
    'source_path': 'src',
    'build_path': 'build',
    'log_path': 'logs',
    'library_path': 'libs',
    'library_prune': ['libs/sdk'],
    'data': {'header_path': f'{CONFIGS_DIRECTORY}/header.yaml'},
  },
}


class Config(NoSql):
  is_path_key = lambda key: key.endswith('_path')

  @staticmethod
  def Generate(config:dict|None=None) -> Config:
    if config is None: config = Config(copy.deepcopy(DEFAULTS))
    Config.cast(config, Config)
    cast_leaf = lambda key, value: Path(value) if Config.is_path_key(key) else value
    Config.traverse(config, onLeaf=cast_leaf)
    return Config(config)


config: Config | Tree = Config.Generate()
