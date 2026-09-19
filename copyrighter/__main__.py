from __future__ import annotations
from . import copyrighter
import sys

def main(argv=None) -> int:
  if argv is None:
    argv = sys.argv[1:]
  return copyrighter.main(argv)

if __name__ == '__main__':
  sys.exit(main())
