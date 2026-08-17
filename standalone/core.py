"""Import the HA-free core modules from the integration package.

``custom_components/estrannaise/__init__.py`` imports Home Assistant, so a
plain ``from custom_components.estrannaise import const`` would fail outside
HA. These three modules (``const``, ``database``, ``schedule``) depend on
nothing but the standard library and ``aiosqlite``, so we load them directly
into a synthetic package and skip the integration's ``__init__``.

This is what keeps the standalone app and the integration on one copy of the
pharmacokinetic model. There is no second implementation to drift.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

PACKAGE = "estrannaise_core"

# Loaded in dependency order: database and schedule both do `from .const import ...`.
MODULES = ("const", "database", "schedule")

DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "custom_components" / "estrannaise"


def core_source_dir() -> Path:
    """Where the integration's core modules live.

    Overridable with ESTRANNAISE_CORE so the container can place them anywhere.
    """
    return Path(os.environ.get("ESTRANNAISE_CORE", DEFAULT_SOURCE))


def load() -> types.ModuleType:
    """Load (once) and return the synthetic ``estrannaise_core`` package."""
    if PACKAGE in sys.modules:
        return sys.modules[PACKAGE]

    src = core_source_dir()
    missing = [m for m in MODULES if not (src / f"{m}.py").exists()]
    if missing:
        raise ImportError(
            f"Estrannaise core modules {missing} not found under {src}. "
            "Set ESTRANNAISE_CORE to the directory holding const.py."
        )

    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(src)]
    sys.modules[PACKAGE] = package

    try:
        for name in MODULES:
            spec = importlib.util.spec_from_file_location(
                f"{PACKAGE}.{name}", src / f"{name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            # Register before exec so relative imports between them resolve.
            sys.modules[f"{PACKAGE}.{name}"] = module
            spec.loader.exec_module(module)
            setattr(package, name, module)
    except Exception:
        # Don't leave a half-built package behind for the next caller.
        for name in MODULES:
            sys.modules.pop(f"{PACKAGE}.{name}", None)
        sys.modules.pop(PACKAGE, None)
        raise

    return package


_core = load()

const = _core.const
database = _core.database
schedule = _core.schedule
