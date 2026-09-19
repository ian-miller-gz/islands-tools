from __future__ import annotations

import os

class Path(str):

  def __add__(self, other: Path | str) -> Path:
    if self.endswith('/'): return Path(str(self) + str(other))
    return Path(os.path.normpath(str(self) + '/' + str(other)))

  @property
  def directory(self):
    return os.path.dirname(self)

  @property
  def filename(self):
    return os.path.split(self)[-1]


Tree = dict[str, 'dict | float | str | Path | Tree']
