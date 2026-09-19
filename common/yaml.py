from __future__ import annotations
import yaml
from pathlib import Path, PosixPath, WindowsPath

def path_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', str(data))

yaml.SafeDumper.add_representer(PosixPath, path_representer)
yaml.SafeDumper.add_representer(WindowsPath, path_representer)
