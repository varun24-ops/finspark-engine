from __future__ import annotations

"""Compatibility facade for parser imports.

The implementation lives in ``req_parser.py`` to preserve the user's local refactor
while keeping existing imports stable across the app and scripts.
"""

from req_parser import ParsedBRD, ServiceRequirement, parse_brd

__all__ = ["ParsedBRD", "ServiceRequirement", "parse_brd"]
