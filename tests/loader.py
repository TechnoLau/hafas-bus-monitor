"""Load the integration's pure Python modules without importing Home Assistant.

``custom_components.hafas_bus_monitor.__init__`` imports Home Assistant and
voluptuous, which are not needed for the HAFAS parser and routing tests.  This
loader creates a synthetic package and imports only the dependency-free
modules.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PACKAGE_NAME = "hafas_bus_monitor"
PACKAGE_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "hafas_bus_monitor"
)


def load_pure_modules() -> None:
    """Load const, util, api and routing under a synthetic package."""
    if f"{PACKAGE_NAME}.routing" in sys.modules:
        return

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules[PACKAGE_NAME] = package

    for module_name in ("const", "util", "api", "routing"):
        full_name = f"{PACKAGE_NAME}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            full_name, PACKAGE_DIR / f"{module_name}.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {full_name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
