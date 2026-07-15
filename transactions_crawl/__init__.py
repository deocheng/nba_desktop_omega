"""transactions_crawl — BR team transactions crawler + loader package.

Reusable 30-team spider that scrapes Basketball-Reference team
``/transactions`` pages (offline HTML or live UC-Chrome), parses each
``<li>`` into typed transaction rows, and upserts them into the existing
``transactions`` table — fixing the historical "concatenation bug" (old
crawler glued fragments together with an empty separator, e.g.
``'TheDetroit PistonssignedMichael Curryas a free agent.'``).

The package is deliberately split so the *parse* layer can be unit-tested
offline (against already-captured HTML) with zero network and zero DB, while
the *fetch*/*load* layers isolate I/O and persistence.
"""

from __future__ import annotations

__all__ = ["config", "parse", "fetch", "load", "validate"]
