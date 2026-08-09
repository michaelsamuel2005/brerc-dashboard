import pytest
from unittest.mock import patch, call

from etl.aggregation.geometry import cell_polygon_wkt


# --- cell_polygon_wkt tests ---

@patch("etl.aggregation.geometry._BNG_TO_WGS84.transform")
def test_cell_polygon_wkt_calculates_correct_bng_corners(mock_transform):
    # Confirms the square's corners are calculated in the correct order:
    # SW, SE, NE, NW, and back to SW to close the ring.
    # Expects five exact coordinate calls to the transformer, else fails.
    
    # We don't care about the return value for this test, just the inputs
    mock_transform.return_value = (0.0, 0.0) 
    
    sw_easting = 1000
    sw_northing = 2000
    cell_size = 100
    
    cell_polygon_wkt(sw_easting, sw_northing, cell_size)
    
    expected_calls = [
        call(1000, 2000),  # SW
        call(1100, 2000),  # SE
        call(1100, 2100),  # NE
        call(1000, 2100),  # NW
        call(1000, 2000),  # SW (closes ring)
    ]
    
    mock_transform.assert_has_calls(expected_calls, any_order=False)
    assert mock_transform.call_count == 5


@patch("etl.aggregation.geometry._BNG_TO_WGS84.transform")
def test_cell_polygon_wkt_formats_wkt_string_correctly(mock_transform):
    # Confirms the transformed WGS84 coordinates are formatted into a valid WKT string.
    # Expects a specific POLYGON string with the exact mocked coordinates, else fails.
    
    # Provide dummy WGS84 coordinates (lon, lat) to simulate pyproj output
    mock_transform.side_effect = [
        (-2.00, 51.00), # SW
        (-1.99, 51.00), # SE
        (-1.99, 51.01), # NE
        (-2.00, 51.01), # NW
        (-2.00, 51.00), # SW (closed)
    ]
    
    # Inputs don't matter much here since we mocked the transformer output
    result = cell_polygon_wkt(sw_easting=1000, sw_northing=2000, cell_size_m=100)
    
    expected_wkt = "POLYGON((-2.0 51.0, -1.99 51.0, -1.99 51.01, -2.0 51.01, -2.0 51.0))"
    
    assert result == expected_wkt


@patch("etl.aggregation.geometry._BNG_TO_WGS84.transform")
def test_cell_polygon_wkt_closes_the_ring(mock_transform):
    # Confirms the first and last coordinates in the resulting WKT string are identical.
    # Expects the first pair of coordinates to perfectly match the last pair, else fails.
    
    mock_transform.side_effect = [
        (-2.5, 51.5), 
        (-2.4, 51.5), 
        (-2.4, 51.6), 
        (-2.5, 51.6), 
        (-2.5, 51.5), # Must match the first
    ]
    
    result = cell_polygon_wkt(1000, 2000, 100)
    
    # Strip "POLYGON((" and "))" then split by comma
    coordinate_pairs = result.replace("POLYGON((", "").replace("))", "").split(", ")
    
    assert coordinate_pairs[0] == coordinate_pairs[-1]