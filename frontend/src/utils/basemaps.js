/**
 * Base maps. Every source is free, needs no API key, and serves open data:
 *  - Satellite: Sentinel-2 cloudless 2024 by EOX (modified Copernicus Sentinel data, CC BY-NC-SA 4.0)
 *  - Terrain / Streets / Villages / Dark: OpenStreetMap data (ODbL) rendered by
 *    OpenTopoMap (CC-BY-SA), the OSM Foundation and the Humanitarian OSM Team.
 * "Dark" is the standard OSM style with a CSS filter (see .tiles-dark), so it
 * needs no third-party dark-tile service.
 */

const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

export const BASEMAPS = [
  {
    id: 'satellite',
    label: 'Satellite',
    hint: 'Sentinel-2 cloudless 2024 · 10 m imagery',
    url: 'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg',
    attribution:
      '<a href="https://s2maps.eu" target="_blank" rel="noopener noreferrer">Sentinel-2 cloudless 2024</a> by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2024)',
    maxNativeZoom: 16,
    maxZoom: 19,
  },
  {
    id: 'terrain',
    label: 'Terrain',
    hint: 'Contours & hill shading · OpenTopoMap',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    subdomains: 'abc',
    attribution: `${OSM_ATTRIBUTION}, SRTM | Style: &copy; <a href="https://opentopomap.org" target="_blank" rel="noopener noreferrer">OpenTopoMap</a> (CC-BY-SA)`,
    maxNativeZoom: 17,
    maxZoom: 19,
  },
  {
    id: 'street',
    label: 'Streets',
    hint: 'Standard OpenStreetMap',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_ATTRIBUTION,
    maxNativeZoom: 19,
    maxZoom: 19,
  },
  {
    id: 'villages',
    label: 'Villages',
    hint: 'Humanitarian style · clear rural detail',
    url: 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
    subdomains: 'abc',
    attribution: `${OSM_ATTRIBUTION} | Style: <a href="https://www.hotosm.org/" target="_blank" rel="noopener noreferrer">Humanitarian OSM Team</a>`,
    maxNativeZoom: 19,
    maxZoom: 19,
  },
  {
    id: 'dark',
    label: 'Dark',
    hint: 'OpenStreetMap, dimmed for dark mode',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: OSM_ATTRIBUTION,
    className: 'tiles-dark',
    maxNativeZoom: 19,
    maxZoom: 19,
  },
];

export const DEFAULT_BASEMAP = { light: 'satellite', dark: 'dark' };

export function basemapById(id) {
  return BASEMAPS.find((b) => b.id === id) || BASEMAPS[0];
}
