"""Ordnance Survey grid-reference / coordinate utilities.  TODO (build this).

Parse an OS grid ref to (easting, northing, precision_m); convert EPSG:27700 ->
EPSG:4326 with always_xy=True; generalise a point to its cell centre. The PostGIS
`en_to_gridref` in db/migrations/0004 mirrors this — keep them in step and covered
by scripts/test_gridref.py.

Learning Guide -> 02-database-and-the-gate.md (section 1).
Answer Key: brerc-public-dashboard/scripts/gridref.py
"""
from __future__ import annotations


def parse_gridref(gridref: str):
    """TODO: parse an OS grid reference to its SW corner + precision (metres)."""
    raise NotImplementedError("TODO: implement parse_gridref (Module 2)")


def en_to_gridref(easting: float, northing: float, resolution_m: int):
    """TODO: format the OS grid ref of the cell, no finer than resolution_m."""
    raise NotImplementedError("TODO: implement en_to_gridref (Module 2)")
