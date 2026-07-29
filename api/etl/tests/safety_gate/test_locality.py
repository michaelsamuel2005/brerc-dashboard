import pandas as pd
import pytest

from etl.safety_gate.locality import (
    os_grid_square,
    add_grid_square,
    add_coarse_locality,
)

# --- os_grid_square tests ---

def test_os_grid_square_matches_known_tower_of_london_reference():
    # Confirms conversion against a known, verifiable reference point
    # (from the module's own docstring): easting=529090, northing=179645
    # -> "TQ 29090 79645" at full precision, truncated here to 10km ("TQ 2 7").
    # Expects "TQ27", else fails.
    result = os_grid_square(529090, 179645, square_size_m=10_000)
    assert result == "TQ27"


def test_os_grid_square_at_1km_precision():
    # Confirms 1km square truncation uses 2 digits per side.
    # Expects "TQ2979", else fails.
    result = os_grid_square(529090, 179645, square_size_m=1_000)
    assert result == "TQ2979"


def test_os_grid_square_at_100m_precision():
    # Confirms 100m square truncation uses 3 digits per side.
    # Expects "TQ290796", else fails.
    result = os_grid_square(529090, 179645, square_size_m=100)
    assert result == "TQ290796"


def test_os_grid_square_rejects_unsupported_square_size():
    # Confirms an unsupported square_size_m raises ValueError rather
    # than silently producing a wrong/misleading reference.
    # Expects ValueError, else fails.
    with pytest.raises(ValueError):
        os_grid_square(529090, 179645, square_size_m=500)


# --- add_grid_square tests ---

def test_add_grid_square_returns_reference_per_row():
    # Confirms add_grid_square produces one grid ref string per row.
    # Expects a non-null string for a row with valid coordinates, else fails.
    df = pd.DataFrame({
        "easting": [529090],
        "northing": [179645],
    })
    result = add_grid_square(df, "easting", "northing", square_size_m=10_000)
    assert result.iloc[0] == "TQ27"


def test_add_grid_square_returns_na_for_missing_coordinates():
    # Confirms rows with missing easting/northing get pd.NA rather than
    # crashing or silently producing a wrong reference.
    # Expects pd.NA, else fails.
    df = pd.DataFrame({
        "easting": [pd.NA],
        "northing": [179645],
    })
    result = add_grid_square(df, "easting", "northing", square_size_m=10_000)
    assert pd.isna(result.iloc[0])


def test_add_grid_square_preserves_row_count():
    # Confirms one output value per input row, including a mix of
    # valid and missing coordinates.
    # Expects 2 results for 2 input rows, else fails.
    df = pd.DataFrame({
        "easting": [529090, pd.NA],
        "northing": [179645, pd.NA],
    })
    result = add_grid_square(df, "easting", "northing", square_size_m=10_000)
    assert len(result) == 2


# --- add_coarse_locality tests ---

def test_add_coarse_locality_currently_raises_due_to_unfinished_unitary_authority():
    # KNOWN BUG: unitary_authority is set to `...` (Ellipsis) as an
    # unfinished placeholder, then string-concatenated with grid_square.
    # This currently raises TypeError on every call, not just unset data.
    # This test documents the current broken state — once
    # unitary_authority lookup is implemented, replace this test with
    # one that checks the real coarse_locality string.
    df = pd.DataFrame({
        "snapped_easting": [529090],
        "snapped_northing": [179645],
    })
    with pytest.raises(TypeError):
        add_coarse_locality(df)