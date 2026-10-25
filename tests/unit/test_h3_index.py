"""
Unit tests for pipeline.spatial.h3_index module.
"""

import math
import pytest
from pipeline.spatial.h3_index import (
    coords_to_h3,
    latlng_to_h3,
    validate_resolution,
    validate_coordinates,
    h3_to_coords,
    is_valid_cell,
    get_cell_resolution,
    SUPPORTED_CANDIDATE_RESOLUTIONS,
    MIN_H3_RES,
    MAX_H3_RES
)

# Reference Chicago coordinate: The Loop (City Hall)
CHICAGO_LAT = 41.881832
CHICAGO_LON = -87.623177

# Reference O'Hare Terminal 1 centroid
OHARE_LAT = 41.982775009
OHARE_LON = -87.8773054


def test_validate_resolution():
    assert validate_resolution(7) == 7
    assert validate_resolution(8) == 8
    assert validate_resolution(9) == 9
    assert validate_resolution(0) == 0
    assert validate_resolution(15) == 15

    with pytest.raises(TypeError):
        validate_resolution(None)

    with pytest.raises(TypeError):
        validate_resolution("8")

    with pytest.raises(TypeError):
        validate_resolution(8.5)

    with pytest.raises(TypeError):
        validate_resolution(True)

    with pytest.raises(ValueError):
        validate_resolution(-1)

    with pytest.raises(ValueError):
        validate_resolution(16)


def test_validate_coordinates():
    lat, lon = validate_coordinates(CHICAGO_LAT, CHICAGO_LON)
    assert lat == CHICAGO_LAT
    assert lon == CHICAGO_LON

    # String numeric
    lat, lon = validate_coordinates("41.881832", "-87.623177")
    assert lat == CHICAGO_LAT
    assert lon == CHICAGO_LON

    # Null / empty
    with pytest.raises(TypeError):
        validate_coordinates(None, CHICAGO_LON)
    with pytest.raises(TypeError):
        validate_coordinates(CHICAGO_LAT, None)
    with pytest.raises(ValueError):
        validate_coordinates("", CHICAGO_LON)

    # Non-finite
    with pytest.raises(ValueError):
        validate_coordinates(float("nan"), CHICAGO_LON)
    with pytest.raises(ValueError):
        validate_coordinates(CHICAGO_LAT, float("inf"))

    # Out of WGS84 range
    with pytest.raises(ValueError):
        validate_coordinates(91.0, CHICAGO_LON)
    with pytest.raises(ValueError):
        validate_coordinates(-90.1, CHICAGO_LON)
    with pytest.raises(ValueError):
        validate_coordinates(CHICAGO_LAT, 180.1)
    with pytest.raises(ValueError):
        validate_coordinates(CHICAGO_LAT, -181.0)


def test_deterministic_output():
    for res in SUPPORTED_CANDIDATE_RESOLUTIONS:
        cell1 = coords_to_h3(CHICAGO_LAT, CHICAGO_LON, res)
        cell2 = coords_to_h3(CHICAGO_LAT, CHICAGO_LON, res)
        assert cell1 is not None
        assert cell1 == cell2
        assert get_cell_resolution(cell1) == res
        assert is_valid_cell(cell1) is True


def test_argument_order_verification():
    # If arguments were flipped (lon, lat), lat -87.62 would fail WGS84 validation
    # or map to an Antarctic coordinate instead of Chicago
    cell_correct = coords_to_h3(CHICAGO_LAT, CHICAGO_LON, 8)
    assert cell_correct is not None
    
    centroid_lat, centroid_lon = h3_to_coords(cell_correct)
    # Centroid must be within ~1 km of Chicago City Hall
    assert math.isclose(centroid_lat, CHICAGO_LAT, abs_tol=0.02)
    assert math.isclose(centroid_lon, CHICAGO_LON, abs_tol=0.02)


def test_safe_coords_to_h3_null_and_invalid_inputs():
    assert coords_to_h3(None, CHICAGO_LON, 8) is None
    assert coords_to_h3(CHICAGO_LAT, None, 8) is None
    assert coords_to_h3(None, None, 8) is None
    assert coords_to_h3("", "", 8) is None
    assert coords_to_h3("not_a_num", CHICAGO_LON, 8) is None
    assert coords_to_h3(CHICAGO_LAT, "not_a_num", 8) is None
    assert coords_to_h3(float("nan"), CHICAGO_LON, 8) is None
    assert coords_to_h3(CHICAGO_LAT, float("inf"), 8) is None
    assert coords_to_h3(100.0, CHICAGO_LON, 8) is None
    assert coords_to_h3(CHICAGO_LAT, -200.0, 8) is None


def test_strict_latlng_to_h3():
    cell = latlng_to_h3(CHICAGO_LAT, CHICAGO_LON, 8)
    assert isinstance(cell, str)
    assert len(cell) == 15
    assert get_cell_resolution(cell) == 8

    with pytest.raises(ValueError):
        latlng_to_h3(100.0, CHICAGO_LON, 8)


def test_ohare_border_records_indexing():
    # Verify the 326 O'Hare border coordinates (41.982775009, -87.8773054) index cleanly
    for res in (7, 8, 9):
        cell = coords_to_h3(OHARE_LAT, OHARE_LON, res)
        assert cell is not None
        assert is_valid_cell(cell) is True
        assert get_cell_resolution(cell) == res

