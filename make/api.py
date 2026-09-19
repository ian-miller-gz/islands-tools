from __future__ import annotations
import make.config as CONFIG
from env import ROOT_DIRECTORY
from make.initializer import Initializer
from make.preprocessor import Preprocessor

SYNTAX_PATH = CONFIG.BUILD_PATH / "syntax"


def compile_head(configuration: str | None = None) -> list[str]:
  initializer = Initializer()
  initializer.configuration = configuration
  initializer.survey()
  if initializer.errored:
    raise LookupError(f"configuration '{configuration}' refused to compose")
  tools = initializer.toolchain
  head = [tools["compiler"], *tools["standard"], *tools["compile_flags"]]
  head += [str(flag) for flag in initializer.flags]
  head += CONFIG.flags("--cflags", CONFIG.packages(initializer.system))
  for root in initializer.roots:
    head += ["-isystem", str(root)]
  if configuration:
    head += ["-I" + str(_rendered(initializer, configuration))]
  head += ["-I" + str(include) for include in sorted(initializer.include_paths)]
  return head


def _rendered(initializer: Initializer, configuration: str):
  home = ROOT_DIRECTORY / SYNTAX_PATH / configuration
  preprocessor = Preprocessor(initializer)
  preprocessor.header_path = home / "generated" / "preprocessor.hpp"
  preprocessor.generate()
  return home


def preprocess_head() -> list[str]:
  return compile_head() + ["-E", "-x", "c++"]


def zone() -> str:
  initializer = Initializer()
  initializer.root = ROOT_DIRECTORY
  initializer.flags = initializer._flags()
  initializer.toolchain = initializer._toolchain()
  return initializer._zone()
