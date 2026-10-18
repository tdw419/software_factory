"""software_factory — a standalone autonomous builder lane.

Distilled from the geometry_os compositor lane (2026-10): change-gated ticks,
ticket queue with claims, receipts with proof-limiting sections, an
append-only operator decision log with GO/abort pairing, byte-exact GO
phrases for disruptive operations, and a mechanical observer that is a
second checker independent of the builder.

Zero runtime dependencies. Python >= 3.10 stdlib only.
"""

__version__ = "0.3.0"
