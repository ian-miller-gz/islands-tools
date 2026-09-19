from __future__ import annotations
import os
import yaml
from typing import Callable
from .common import Tree, Path


class NoSql(dict):

  def __init__(self, *args, **kwargs) -> None:
    super(NoSql, self).__init__(*args, **kwargs)
    self.__dict__ = self

  @staticmethod
  def cast(source: NoSql|dict, Type:type) -> dict:
    cast = lambda key, value: Type(value) if isinstance(value, dict) else value
    result = NoSql.traverse(source, onIndex=cast)
    return result

  @staticmethod
  def traverse(
      tree:dict,
      onLeaf:Callable=lambda key, value:value,
      onIndex:Callable=lambda key, value:value):
    items = list(tree.items())
    for key, value in items:
      if not isinstance(value, dict):
        tree[key] = onLeaf(key, value)
      else:
        NoSql.traverse(value,onLeaf=onLeaf, onIndex=onIndex)
        tree[key] = onIndex(key, value)
    return onIndex('', tree)
