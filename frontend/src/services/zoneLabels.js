/**
 * RideIntel Stable H3 Zone Labels and Centroids Catalog.
 *
 * Maps raw 64-bit hexadecimal H3 Resolution 8 cells to canonical,
 * stable friendly labels (e.g. 'Zone Z-042') derived from alphabetical
 * ranking across the 239 Chicago taxi catalog cells.
 *
 * Preserves the original H3 index in all operations while presenting
 * intuitive names to operators and users.
 */

import zoneCatalog from './zoneCatalog.json' with { type: 'json' };

/**
 * Returns the stable friendly label for a given H3 cell (e.g., 'Zone Z-042').
 * If the cell is not in the catalog, returns 'Zone [last 4 hex chars]'.
 */
export function getZoneLabel(h3Cell) {
  if (!h3Cell) return 'Unknown Zone';
  const entry = zoneCatalog[h3Cell];
  if (entry && entry.label) {
    return entry.label;
  }
  return `Zone ${h3Cell.slice(-4).toUpperCase()}`;
}

/**
 * Returns full metadata for an H3 cell including coordinates and resolution.
 */
export function getZoneDetails(h3Cell) {
  if (!h3Cell) return null;
  const entry = zoneCatalog[h3Cell];
  if (entry) {
    return {
      ...entry,
      coordinates: `${entry.lat.toFixed(4)}, ${entry.lng.toFixed(4)}`
    };
  }
  return {
    id: h3Cell,
    label: `Zone ${h3Cell.slice(-4).toUpperCase()}`,
    index: null,
    lat: null,
    lng: null,
    resolution: 8,
    coordinates: 'N/A'
  };
}

/**
 * Returns an array of all zones with their friendly labels, sorted by zone index.
 */
export function getAllZoneLabels() {
  return Object.values(zoneCatalog).sort((a, b) => a.index - b.index);
}

export default {
  getZoneLabel,
  getZoneDetails,
  getAllZoneLabels
};
