"""
RideIntel H3 Spatial Indexing Helper.

Provides deterministic H3 hexagonal indexing for geographic coordinates.
Uses the modern H3 Python v4 API (h3.latlng_to_cell).
Dependency: h3>=4.0.0 (verified on h3==4.5.0).
"""

import math
from typing import Any, Optional, Tuple, List, Dict
import h3

# Constants
MIN_H3_RES: int = 0
MAX_H3_RES: int = 15
SUPPORTED_CANDIDATE_RESOLUTIONS: Tuple[int, ...] = (7, 8, 9)
H3_DEPENDENCY: str = "h3>=4.0.0"

# Chicago approximate WGS84 geographic envelope (for descriptive bounds checks)
CHICAGO_BBOX = {
    "min_lat": 41.60,
    "max_lat": 42.10,
    "min_lon": -88.00,
    "max_lon": -87.50
}


def validate_resolution(resolution: Any) -> int:
    """
    Validates that resolution is an integer between 0 and 15 inclusive.
    Raises TypeError if not an int.
    Raises ValueError if outside [0, 15].
    """
    if resolution is None:
        raise TypeError("H3 resolution must be an integer, not None.")
    if not isinstance(resolution, int) or isinstance(resolution, bool):
        raise TypeError(f"H3 resolution must be an integer, got {type(resolution).__name__}.")
    if not (MIN_H3_RES <= resolution <= MAX_H3_RES):
        raise ValueError(f"H3 resolution must be between {MIN_H3_RES} and {MAX_H3_RES}, got {resolution}.")
    return resolution


def validate_coordinates(lat: Any, lon: Any) -> Tuple[float, float]:
    """
    Validates that latitude and longitude can be parsed as finite WGS84 floats.
    -90.0 <= lat <= 90.0
    -180.0 <= lon <= 180.0
    Raises TypeError or ValueError on invalid inputs.
    """
    if lat is None or lon is None:
        raise TypeError("Coordinates cannot be None.")
    if lat == "" or lon == "":
        raise ValueError("Coordinates cannot be empty strings.")
    
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Could not convert coordinates to float: ({lat}, {lon})") from e

    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        raise ValueError(f"Coordinates must be finite numbers, got ({lat_f}, {lon_f}).")

    if not (-90.0 <= lat_f <= 90.0):
        raise ValueError(f"Latitude must be in [-90.0, 90.0], got {lat_f}.")
    if not (-180.0 <= lon_f <= 180.0):
        raise ValueError(f"Longitude must be in [-180.0, 180.0], got {lon_f}.")

    return lat_f, lon_f


def coords_to_h3(lat: Any, lon: Any, resolution: int) -> Optional[str]:
    """
    Safely converts (lat, lon) coordinates to an H3 cell index string at the given resolution.
    Returns None if:
      - lat or lon is None, empty string, or cannot be parsed as float
      - lat or lon is NaN, infinite, or out of WGS84 bounds
    Raises ValueError / TypeError if resolution is invalid.
    """
    res = validate_resolution(resolution)
    try:
        lat_f, lon_f = validate_coordinates(lat, lon)
    except (ValueError, TypeError):
        return None

    # h3.latlng_to_cell accepts (lat, lon, res) in H3 v4 API
    return h3.latlng_to_cell(lat_f, lon_f, res)


def latlng_to_h3(lat: float, lon: float, resolution: int) -> str:
    """
    Strict conversion of (lat, lon) to an H3 cell index string.
    Raises ValueError / TypeError if inputs are invalid.
    """
    res = validate_resolution(resolution)
    lat_f, lon_f = validate_coordinates(lat, lon)
    return h3.latlng_to_cell(lat_f, lon_f, res)


def h3_to_coords(cell: str) -> Tuple[float, float]:
    """
    Returns the (latitude, longitude) centroid of an H3 cell index.
    Raises ValueError if cell is invalid.
    """
    if not isinstance(cell, str) or not cell:
        raise ValueError(f"Cell must be a non-empty string, got {cell!r}.")
    if not h3.is_valid_cell(cell):
        raise ValueError(f"Invalid H3 cell index: {cell!r}.")
    return h3.cell_to_latlng(cell)


def is_valid_cell(cell: str) -> bool:
    """
    Returns True if cell is a valid H3 cell index string.
    """
    if not isinstance(cell, str) or not cell:
        return False
    try:
        return h3.is_valid_cell(cell)
    except Exception:
        return False


def get_cell_resolution(cell: str) -> int:
    """
    Returns the integer resolution (0-15) of an H3 cell index.
    Raises ValueError if cell is invalid.
    """
    if not is_valid_cell(cell):
        raise ValueError(f"Invalid H3 cell index: {cell!r}.")
    return h3.get_resolution(cell)

