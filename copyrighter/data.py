from __future__ import annotations
import os
import yaml
from common import NoSql
from env import config, ROOT_DIRECTORY


def _yaml_concat_constructor(loader, node):
    value = loader.construct_sequence(node)
    return "".join(str(item) for item in value)


def _Generate() -> NoSql:
  data = None
  path = ROOT_DIRECTORY / config.paths.data.header_path
  path = os.path.normpath(path)
  yaml.SafeLoader.add_constructor('!concat', _yaml_concat_constructor)
  with open(path) as file:
    data = NoSql(yaml.safe_load(file))
  assert isinstance(data, NoSql)
  return data


DATA = _Generate()
HEADER = DATA.header
IDENTIFIER = DATA.identifier
LANGUAGES = DATA.languages
FORMS = DATA.forms
SKIP = DATA.get('skip') or []
