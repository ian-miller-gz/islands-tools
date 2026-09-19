from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Optional
from env import ROOT_DIRECTORY
import common.log as logging
from .data import SKIP
from .processor import Processor


log: Any = logging.initialize()


class Copyrighter:

  def __init__(self, root: str = '', recursive: bool = True) -> None:
    self.root: Path = ROOT_DIRECTORY / root
    self.recursive: bool = recursive
    self.processor = Processor()
    log.info(f'Copyrighter initialized; src_root={self.root} recursive={self.recursive}')

  def _read(self, path: Path) -> Optional[str]:
    try:
      with open(path, 'r', encoding='utf-8') as file:
        return file.read()
    except OSError:
      log.debug(f'Failed to read file: {path}')
      return None

  def _write(self, absolute_path: str, content: str) -> bool:
    try:
      with open(absolute_path, 'w', encoding='utf-8') as file_handle:
        file_handle.write(content)
      return True
    except OSError:
      log.error('Failed to write file: %s', absolute_path, exc_info=True)
      return False

  def _process_entry(self, absolute_path: str) -> None:
    pass

  def run(self, directory: Path) -> None:
    if not os.path.isdir(directory):
      log.warning(f'Directory does not exist, skipping: {directory}')
      return
    log.debug(f'push {directory}')
    for entry in sorted(os.listdir(directory)):
      path = directory / entry
      if entry in SKIP:
        log.debug(f'Skipping directory: {entry}')
        continue
      if os.path.isfile(path):
        content = self.processor.process(path)
        if content and content != self._read(path):
          self._write(str(path), content)
          log.info(f'Header written: {path}')
      elif os.path.isdir(path) and self.recursive:
        log.info(f'Pushing {path}')
        self.run(path)
    log.debug('pop %s', directory)

def main(argv) -> int:
  if not argv:
    print('usage: python3 -m copyrighter <directories...> (root-relative)')
    return 1
  copyrighter = Copyrighter(recursive=True)
  for relative in argv:
    copyrighter.run(Path(ROOT_DIRECTORY / relative))
  return 0
