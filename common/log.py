from __future__ import annotations
import logging
import os
import time

import env as env

LEVEL = env.config.log.level

DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL


class CustomFormatter(logging.Formatter):
  violet = "\x1b[35m"
  blue = "\x1b[34m"
  yellow = "\x1b[33;20m"
  red = "\x1b[31;20m"
  bold_red = "\x1b[31;1m"
  reset = "\x1b[0m"
  italicize = "\033[3m"
  FORMAT = (
    f"%(levelname)-8s{reset} %(time)s "
    f"{italicize}%(pathname)s:%(lineno_formatted)s{reset} "
    f"%(message)s{reset}"
  )
  FORMATS = {
    logging.DEBUG: violet,
    logging.INFO: blue,
    logging.WARNING: yellow,
    logging.ERROR: red,
    logging.CRITICAL: bold_red,
  }

  def format(self, record):
    color = self.FORMATS[record.levelno]
    log_fmt = color + self.FORMAT
    formatter = logging.Formatter(log_fmt)
    record.pathname = os.path.normpath(record.pathname)
    record.pathname = record.pathname.strip(".py")
    record.time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))[2:]
    record.lineno_formatted = str(record.lineno).rjust(4, " ")
    output = formatter.format(record)
    output.replace("\x1f", color + "\033[2m", 1)
    output = output.replace("\n", "\n" + color + "\033[2m", 1)
    output = output.replace("\n", "\n\t ")
    return output


def initialize(level: int = logging.DEBUG) -> logging.Logger:
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.DEBUG)
  handler = logging.StreamHandler()
  handler.setLevel(LEVEL)
  handler.setFormatter(CustomFormatter())
  for stale in logger.handlers[:]:
    logger.removeHandler(stale)
  logger.addHandler(handler)
  logger.propagate = True
  return logger
