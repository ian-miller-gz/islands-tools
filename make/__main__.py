from __future__ import annotations
import argparse
import sys

from make import Make


if __name__ == '__main__':
  parser = argparse.ArgumentParser(
    prog="make",
    description="Build the project per its make config.")
  parser.add_argument(
    "--configuration", metavar="NAME",
    help="overlay the named `configurations:` entry onto the bench tokens "
         "(in memory — nothing on disk changes; the matrix driver's channel)")
  arguments = parser.parse_args()
  make = Make(configuration=arguments.configuration)
  make.preprocess()
  make.precompile()
  make.compile()
  make.assemble()
  make.link()
  make.copy_output()
  make.promote()
  make.clear()
  sys.exit(1 if make.errored else 0)
