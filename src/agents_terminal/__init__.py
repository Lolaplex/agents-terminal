"""Jailed terminal CLI for Cordis call_job mcp.terminal.

``list``, ``read``, ``grep``, and ``stat`` only observe the workspace root.
``write`` and ``edit`` change files inside the root. ``run`` executes argv.
All three are mutating. ``--help-json`` declares ``side_effects``.
"""

__version__ = "0.0.6"
