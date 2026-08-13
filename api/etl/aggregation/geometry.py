"""Transforms British National Grid (EPSG:27700) grid cells into WGS84 WKT polygons."""
from pyproj import Transformer

_BNG_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def cell_polygon_wkt(sw_easting: float, sw_northing: float, cell_size_m: int) -> str:
    """
    WKT POLYGON in WGS84 for a grid cell whose SW corner is
    (sw_easting, sw_northing) in BNG, with side length cell_size_m.
    """
    corners_bng = [
        (sw_easting, sw_northing),
        (sw_easting + cell_size_m, sw_northing),
        (sw_easting + cell_size_m, sw_northing + cell_size_m),
        (sw_easting, sw_northing + cell_size_m),
        (sw_easting, sw_northing),  # close the ring
    ]
    corners_wgs84 = [_BNG_TO_WGS84.transform(e, n) for e, n in corners_bng]
    ring = ", ".join(f"{lon} {lat}" for lon, lat in corners_wgs84)
    return f"POLYGON(({ring}))"
