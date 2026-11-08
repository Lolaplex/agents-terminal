"""Jailed terminal CLI for Cordis call_job mcp.terminal.

``list``, ``read``, ``grep``, and ``stat`` only observe the workspace root.
``write`` and ``edit`` change files inside the root. ``run`` executes argv.
All three are mutating. ``--help-json`` declares ``side_effects``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agents-terminal")
except PackageNotFoundError:  # a source checkout that was never installed
    __version__ = "0.0.0+source"
