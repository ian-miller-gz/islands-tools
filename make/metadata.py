from __future__ import annotations
import os
from env import Path


class Metadata:

  def __init__(self, path:Path):

    self.path = path
    self.timestamp = os.path.getmtime(path)

  def __repr__(self) -> str:
    return f'{self.__class__}{self.timestamp}|{self.path.name}'

  def __str__(self) -> str:
    return self.__repr__()
