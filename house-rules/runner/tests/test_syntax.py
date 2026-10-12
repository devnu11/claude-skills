"""Function sites: kinds, parameters, decorators."""

import ast

from house_rules.syntax import Kind, walk_functions

TEXT = """
def free(a, /, b, *rest, c, **more): pass
class Shape:
    def method(self, a): pass
    @staticmethod
    def static(a): pass
    @classmethod
    def build(cls, a): pass
    @property
    def area(self): pass
    @area.setter
    def area(self, value): pass
    @functools.cache
    def cached(self): pass
    def broken(): pass
"""


def test_kinds_and_parameters() -> None:
    sites = {site.qualname + ":" + site.kind: [a.arg for a in site.parameters]
             for site in walk_functions(ast.parse(TEXT))}  # fmt: skip
    assert sites == {
        "free:function": ["a", "b", "c", "rest", "more"],
        "Shape.method:method": ["a"],
        "Shape.static:staticmethod": ["a"],
        "Shape.build:classmethod": ["a"],
        "Shape.area:property": [],
        "Shape.area:accessor": ["value"],
        "Shape.cached:method": [],
        "Shape.broken:method": [],
    }


def test_decorator_names_and_receiver() -> None:
    sites = list(walk_functions(ast.parse(TEXT)))
    assert {site.name: sorted(site.decorators) for site in sites}["cached"] == ["cache"]
    assert [site.receiver for site in sites if site.name == "broken"] == [""]
    assert Kind.METHOD == "method"
