# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Package version lookup.

This module has no imports from the rest of RadSim, so it is safe
to import from anywhere (cli, output, __init__) without cycles.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

# The PyPI distribution is named "radsimcli"; the import package is "radsim".
DIST_NAME = "radsimcli"

__version__ = "1.5.1"


def get_radsim_version() -> str:
    """Return the installed package version.

    Falls back to the source version when RadSim runs from a
    checkout that was never pip-installed (no package metadata).
    """
    try:
        return installed_version(DIST_NAME)
    except PackageNotFoundError:
        return __version__
