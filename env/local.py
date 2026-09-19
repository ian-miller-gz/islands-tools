from __future__ import annotations
from .config import config


def Set_Log_Level(cls, level:int|float) -> None:
  config.log.level = level
