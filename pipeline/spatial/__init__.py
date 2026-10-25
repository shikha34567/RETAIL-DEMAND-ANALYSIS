"""
RideIntel Spatial Module.
Provides H3 spatial indexing, resolution validation, and coordinate-to-cell mapping.
"""

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

from pipeline.spatial.zone_universe import (
    ZoneUniverseBuilder,
    ZONE_UNIVERSE_PARQUET_SCHEMA,
    SELECTED_OPERATIONAL_THRESHOLD,
    SELECTED_RULE_NAME
)

__all__ = [
    "coords_to_h3",
    "latlng_to_h3",
    "validate_resolution",
    "validate_coordinates",
    "h3_to_coords",
    "is_valid_cell",
    "get_cell_resolution",
    "SUPPORTED_CANDIDATE_RESOLUTIONS",
    "MIN_H3_RES",
    "MAX_H3_RES",
    "ZoneUniverseBuilder",
    "ZONE_UNIVERSE_PARQUET_SCHEMA",
    "SELECTED_OPERATIONAL_THRESHOLD",
    "SELECTED_RULE_NAME"
]

