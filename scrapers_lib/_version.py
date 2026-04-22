"""Single source of truth for the library version.

Leaf module — imports nothing from the package, so every other module
(including ones loaded during ``scrapers_lib/__init__.py`` evaluation,
like ``core.robots`` via ``core.scheduler``) can safely ``from
scrapers_lib._version import __version__`` without circular-import risk.

Keep in sync with the ``version`` field in ``pyproject.toml``.
"""

__version__ = "1.0.0"
