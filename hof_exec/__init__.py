"""hof_exec — BR team HoF & Executives crawler + loader package.

Reusable spider that scrapes Basketball-Reference team ``/hof`` and
``/executives`` pages (offline HTML or live UC-Chrome), parses the data
into typed rows, and upserts them into ``team_hof`` / ``team_executives``.

The package is deliberately split so the *parse* layer can be unit-tested
offline (against already-captured HTML) with zero network and zero DB, while
the *fetch*/*load* layers isolate I/O and persistence.
"""

from __future__ import annotations

__all__ = ["config", "parse", "fetch", "load", "validate"]
