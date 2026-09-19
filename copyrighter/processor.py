from __future__ import annotations
from pathlib import Path
import os
import re
from env import ROOT_DIRECTORY
from common import log as logging
from  .data import DATA, FORMS, HEADER


log = logging.initialize()


class Processor:

  def __init__(self, header:str=HEADER, root:Path=ROOT_DIRECTORY) -> None:
    self.header = header
    self.root = root
    self.language_map = {}
    self.supported_extensions = set()
    self.data = DATA
    self._initialize_data()

  def _initialize_data(self):
    languages = self.data.languages
    for language, value in languages.items():
      for extension in value['extensions']:
        self.language_map[extension] = language
    assert self.language_map

  def _form(self, path: Path, language: str) -> dict:
    rules = self.data['languages'][language]
    try:
      relative = Path(path).resolve().relative_to(Path(self.root).resolve())
    except ValueError:
      return rules
    for name, prefixes in FORMS.items():
      if any(relative.is_relative_to(prefix) for prefix in prefixes):
        return rules.get('forms', {}).get(name, rules)
    return rules

  def _regex(self, content: str, rules: dict) -> str:
    for pattern, repl, count in rules['regex']:
      content = re.sub(
        pattern,
        repl,
        content,
        count=count,
        flags=re.DOTALL | re.MULTILINE)
    for  pattern, matcher, count in rules['move']:
      matches = re.findall(matcher, content, flags=re.DOTALL | re.MULTILINE)
      for match in reversed(matches):
        content = re.sub(match, '', content, count=count, flags=re.DOTALL | re.MULTILINE)
        content = re.sub(pattern, match, content, count=count)
    return content

  def process(self, path: Path) -> str:
    language = self.language_map.get(extension:=os.path.splitext(path)[1])
    if language is None:
      log.info(f'Extension not supported: {extension}. Skipping {path}')
      return ''
    with open(path, 'r', encoding='utf-8') as file:
      content = file.read()
    content = self._regex(content, self._form(path, language))
    return content
