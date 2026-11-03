/**
 * Client-side exports of a CatchmentResponse: full JSON, GIS-ready GeoJSON,
 * and a candidate-site CSV for spreadsheets.
 */

const CSV_COLUMNS = [
  ['rank', 'Rank'],
  ['site_id', 'Site ID'],
  ['latitude', 'Latitude'],
  ['longitude', 'Longitude'],
  ['suitability_score', 'Suitability (0-100)'],
  ['composite_mcdm_score', 'MCDM score'],
  ['area_m2', 'Footprint (m2)'],
  ['storage_capacity_m3', 'Storage (m3)'],
  ['cut_volume_m3', 'Cut volume (m3)'],
  ['storage_efficiency_ratio', 'Storage/cut ratio'],
  ['slope_deg', 'Slope (deg)'],
  ['elevation_m', 'Elevation (m)'],
  ['mean_twi', 'Mean TWI'],
];

export function allSites(result) {
  return [result?.recommended_site, ...(result?.alternative_sites || [])].filter(Boolean);
}

function csvCell(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function sitesToCsv(result) {
  const header = CSV_COLUMNS.map(([, label]) => label).join(',');
  const rows = allSites(result).map((site) => CSV_COLUMNS.map(([key]) => csvCell(site[key])).join(','));
  return [header, ...rows].join('\n') + '\n';
}

function featuresOf(geojson) {
  if (!geojson) return [];
  if (geojson.type === 'FeatureCollection') return geojson.features || [];
  if (geojson.type === 'Feature') return [geojson];
  if (geojson.type && geojson.coordinates) return [{ type: 'Feature', geometry: geojson, properties: {} }];
  return [];
}

/** One FeatureCollection: site points, pond footprints, catchment, selection. */
export function resultToGeoJSON(result) {
  const features = [];
  allSites(result).forEach((site) => {
    const props = { layer: site.rank === 1 ? 'recommended_site' : 'alternative_site' };
    CSV_COLUMNS.forEach(([key]) => {
      if (site[key] !== undefined) props[key] = site[key];
    });
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [site.longitude, site.latitude] },
      properties: props,
    });
    featuresOf(site.boundary_geojson).forEach((f) =>
      features.push({ ...f, properties: { ...(f.properties || {}), layer: 'pond_footprint', site_id: site.site_id, rank: site.rank } })
    );
  });
  const catchment = result?.catchment;
  featuresOf(catchment?.boundary_geojson).forEach((f) =>
    features.push({
      ...f,
      properties: {
        ...(f.properties || {}),
        layer: 'catchment',
        area_hectares: catchment.area_hectares,
        estimated_runoff_volume_m3: catchment.estimated_runoff_volume_m3,
        design_rainfall_mm: catchment.design_rainfall_mm,
        curve_number: catchment.curve_number,
      },
    })
  );
  const area = result?.selected_area;
  if (area) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [area.longitude, area.latitude] },
      properties: { layer: 'selected_area_centre', radius_m: area.radius_m },
    });
  }
  return { type: 'FeatureCollection', features };
}

export function exportFileStem(result) {
  const site = result?.recommended_site;
  const where = site ? `${site.latitude.toFixed(4)}_${site.longitude.toFixed(4)}` : 'analysis';
  const date = new Date().toISOString().slice(0, 10);
  return `jalasetu_${where}_${date}`;
}

export function downloadText(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
