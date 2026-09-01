import React, { useMemo } from 'react';
import { Marker, Popup, GeoJSON } from 'react-leaflet';
import L from 'leaflet';

/**
 * Creates custom styled Leaflet DivIcon for the #1 recommended pond site.
 *
 * @returns {L.DivIcon}
 */
export const createRecommendedPondIcon = () =>
  L.divIcon({
    className: 'custom-leaflet-div-icon',
    html: `
      <div class="custom-marker marker-recommended">
        <div class="marker-pin marker-pin-recommended">
          <div class="marker-pin-inner">
            <span class="marker-recommended-star">⭐</span>
          </div>
        </div>
        <div class="marker-badge-recommended">Top Pick #1</div>
      </div>
    `,
    iconSize: [60, 52],
    iconAnchor: [30, 48],
    popupAnchor: [0, -48],
  });

/**
 * Creates custom styled Leaflet DivIcon for ranked alternative pond sites.
 *
 * @param {number} rank - Siting rank (e.g. 2, 3).
 * @returns {L.DivIcon}
 */
export const createAlternativePondIcon = (rank = 2) =>
  L.divIcon({
    className: 'custom-leaflet-div-icon',
    html: `
      <div class="custom-marker marker-alternative">
        <div class="marker-pin marker-pin-alternative">
          <div class="marker-pin-inner">
            <span class="marker-rank-text">#${rank}</span>
          </div>
        </div>
      </div>
    `,
    iconSize: [32, 38],
    iconAnchor: [16, 34],
    popupAnchor: [0, -34],
  });

/**
 * Generates an intuitive plain-language suitability description.
 *
 * @param {number} score - Suitability score (0 - 100).
 * @param {number} [slope] - Ground slope in degrees.
 * @returns {string} Human-friendly explanation.
 */
export function getSuitabilityDescription(score, slope) {
  if (typeof score !== 'number') {
    return 'Evaluated terrain candidate for farm pond excavation.';
  }
  const slopeText = typeof slope === 'number' ? `gentle ${slope.toFixed(1)}° slope` : 'favorable slope';

  if (score >= 88) {
    return `Suitability: ${Math.round(score)}/100 — Optimal natural depression, ${slopeText}, and strong runoff accumulation.`;
  }
  if (score >= 70) {
    return `Suitability: ${Math.round(score)}/100 — High suitability with ${slopeText} and solid upstream catchment potential.`;
  }
  if (score >= 50) {
    return `Suitability: ${Math.round(score)}/100 — Moderate suitability, suitable for standard village pond excavation.`;
  }
  return `Suitability: ${Math.round(score)}/100 — Candidate site meeting baseline terrain criteria.`;
}

/**
 * Translates delineation method into non-technical plain-language badge.
 */
function getMethodDisplayLabel(method) {
  if (method === 'flow_accumulation') {
    return 'Full Flow Routing';
  }
  return 'Terrain Estimate';
}

/**
 * Helper to test if a GeoJSON object contains valid coordinates.
 *
 * @param {Object} geojson
 * @returns {boolean}
 */
export function hasValidGeoJSONGeometry(geojson) {
  if (!geojson || typeof geojson !== 'object') return false;
  if (Array.isArray(geojson.features)) {
    return geojson.features.some(
      (f) =>
        f?.geometry?.coordinates &&
        Array.isArray(f.geometry.coordinates) &&
        f.geometry.coordinates.length > 0
    );
  }
  if (geojson.coordinates && Array.isArray(geojson.coordinates) && geojson.coordinates.length > 0) {
    return true;
  }
  if (
    geojson.geometry?.coordinates &&
    Array.isArray(geojson.geometry.coordinates) &&
    geojson.geometry.coordinates.length > 0
  ) {
    return true;
  }
  return false;
}

/**
 * Calculates a dynamic bounding box covering all rendered site boundary polygons,
 * site centroid markers, and the catchment boundary combined.
 *
 * @param {Object} data - CatchmentResponse payload.
 * @returns {[[number, number], [number, number]] | null} Bounding box [[south, west], [north, east]].
 */
export function computeCombinedResultsBounds(data) {
  if (!data) return null;

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLng = Infinity;
  let maxLng = -Infinity;
  let count = 0;

  const addCoord = (lat, lng) => {
    if (typeof lat === 'number' && typeof lng === 'number' && !isNaN(lat) && !isNaN(lng)) {
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      minLng = Math.min(minLng, lng);
      maxLng = Math.max(maxLng, lng);
      count++;
    }
  };

  const addGeoJSON = (geojson) => {
    if (!geojson) return;
    const traverse = (coords) => {
      if (!Array.isArray(coords)) return;
      if (coords.length >= 2 && typeof coords[0] === 'number' && typeof coords[1] === 'number') {
        const [lng, lat] = coords;
        addCoord(lat, lng);
      } else {
        coords.forEach(traverse);
      }
    };

    if (Array.isArray(geojson.features)) {
      geojson.features.forEach((f) => {
        if (f?.geometry?.coordinates) traverse(f.geometry.coordinates);
      });
    } else if (geojson.coordinates) {
      traverse(geojson.coordinates);
    } else if (geojson.geometry?.coordinates) {
      traverse(geojson.geometry.coordinates);
    }
  };

  // 1. Recommended site centroid & boundary polygon
  if (data.recommended_site) {
    if (
      typeof data.recommended_site.latitude === 'number' &&
      typeof data.recommended_site.longitude === 'number'
    ) {
      addCoord(data.recommended_site.latitude, data.recommended_site.longitude);
    }
    if (hasValidGeoJSONGeometry(data.recommended_site.boundary_geojson)) {
      addGeoJSON(data.recommended_site.boundary_geojson);
    }
  }

  // 2. Alternative candidate sites centroids & boundary polygons
  if (Array.isArray(data.alternative_sites)) {
    data.alternative_sites.forEach((site) => {
      if (site) {
        if (typeof site.latitude === 'number' && typeof site.longitude === 'number') {
          addCoord(site.latitude, site.longitude);
        }
        if (hasValidGeoJSONGeometry(site.boundary_geojson)) {
          addGeoJSON(site.boundary_geojson);
        }
      }
    });
  }

  // 3. Catchment polygon geometry
  if (hasValidGeoJSONGeometry(data.catchment?.boundary_geojson)) {
    addGeoJSON(data.catchment.boundary_geojson);
  }

  if (count > 0 && isFinite(minLat) && isFinite(maxLat) && isFinite(minLng) && isFinite(maxLng)) {
    return [
      [minLat, minLng],
      [maxLat, maxLng],
    ];
  }

  return null;
}

/**
 * ResultsLayer Component
 *
 * Renders geospatial analysis results inside a React Leaflet MapContainer:
 *  - Translucent blue catchment drainage area polygon (dashed border)
 *  - Warm amber/orange filled boundary polygon for #1 recommended pond footprint (solid border)
 *  - Muted secondary boundary polygons for alternative candidate sites (lower opacity, dashed)
 *  - Green star pin marker for #1 recommended pond site with rich popup
 *  - Muted secondary pin markers for alternative candidate sites
 *
 * @param {Object} props
 * @param {Object} props.data - The CatchmentResponse object.
 */
export default function ResultsLayer({ data = null }) {
  if (!data) return null;

  const { recommended_site, alternative_sites = [], catchment } = data;

  const recommendedIcon = useMemo(() => createRecommendedPondIcon(), []);

  // Unique keys to force clean Leaflet layer re-mount when data updates
  const catchmentKey = useMemo(() => {
    if (!hasValidGeoJSONGeometry(catchment?.boundary_geojson)) return 'empty-catchment';
    return `catchment-${catchment.area_m2}-${catchment.average_slope_deg}`;
  }, [catchment]);

  const recommendedBoundaryKey = useMemo(() => {
    if (!hasValidGeoJSONGeometry(recommended_site?.boundary_geojson)) return 'empty-rec-boundary';
    return `rec-pond-boundary-${recommended_site.site_id || 'rec'}-${recommended_site.area_m2 || 'area'}`;
  }, [recommended_site]);

  return (
    <>
      {/* 1. Catchment Watershed Drainage Polygon Overlay (Translucent Blue) */}
      {hasValidGeoJSONGeometry(catchment?.boundary_geojson) && (
        <GeoJSON
          key={catchmentKey}
          data={catchment.boundary_geojson}
          style={{
            color: '#0284c7',
            weight: 2.5,
            opacity: 0.9,
            dashArray: '5, 5',
            fillColor: '#0ea5e9',
            fillOpacity: 0.22,
          }}
          onEachFeature={(feature, layer) => {
            const methodLabel = getMethodDisplayLabel(catchment.delineation_method);
            layer.bindPopup(`
              <div class="popup-card">
                <div class="popup-header">
                  <div class="popup-title-group">
                    <span class="popup-title-icon">🌊</span>
                    <span class="popup-title">Watershed Drainage Area</span>
                  </div>
                  <span class="popup-badge popup-badge-catchment">${methodLabel}</span>
                </div>
                <div class="popup-desc">
                  Upstream natural terrain area contributing rainwater runoff directly into the recommended pond location.
                </div>
                <div class="popup-stats-grid">
                  <div class="popup-stat">
                    <span class="popup-stat-label">Catchment Area</span>
                    <span class="popup-stat-val">${catchment.area_hectares ? catchment.area_hectares.toFixed(2) : 'N/A'} ha (${catchment.area_m2 ? catchment.area_m2.toLocaleString() : 'N/A'} m²)</span>
                  </div>
                  <div class="popup-stat">
                    <span class="popup-stat-label">Mean Basin Slope</span>
                    <span class="popup-stat-val">${typeof catchment.average_slope_deg === 'number' ? `${catchment.average_slope_deg.toFixed(1)}°` : 'N/A'}</span>
                  </div>
                  <div class="popup-stat">
                    <span class="popup-stat-label">Elevation Range</span>
                    <span class="popup-stat-val">${catchment.elevation_range_m?.min_m !== undefined ? catchment.elevation_range_m.min_m.toFixed(1) : 'N/A'}m – ${catchment.elevation_range_m?.max_m !== undefined ? catchment.elevation_range_m.max_m.toFixed(1) : 'N/A'}m</span>
                  </div>
                  <div class="popup-stat">
                    <span class="popup-stat-label">Total Relief</span>
                    <span class="popup-stat-val">${catchment.elevation_range_m?.relief_m !== undefined ? `${catchment.elevation_range_m.relief_m.toFixed(1)}m` : 'N/A'}</span>
                  </div>
                </div>
              </div>
            `);
          }}
        />
      )}

      {/* 2. Alternative Candidate Sites Boundary Polygons (Muted / Lower Opacity) */}
      {Array.isArray(alternative_sites) &&
        alternative_sites.map((site, idx) => {
          if (!hasValidGeoJSONGeometry(site?.boundary_geojson)) return null;
          const siteRank = site.rank || idx + 2;
          return (
            <GeoJSON
              key={`alt-boundary-${site.site_id || siteRank}-${site.area_m2 || idx}`}
              data={site.boundary_geojson}
              style={{
                color: '#64748b',
                weight: 1.5,
                opacity: 0.75,
                dashArray: '4, 4',
                fillColor: '#94a3b8',
                fillOpacity: 0.18,
              }}
              onEachFeature={(feature, layer) => {
                layer.bindPopup(`
                  <div class="popup-card">
                    <div class="popup-header">
                      <div class="popup-title-group">
                        <span class="popup-title-icon">📍</span>
                        <span class="popup-title">Alternative Footprint #${siteRank}</span>
                      </div>
                      <span class="popup-badge popup-badge-alternative">Candidate</span>
                    </div>
                    <div class="popup-desc">
                      Contiguous suitable terrain region for candidate #${siteRank} (${site.area_m2 ? site.area_m2.toLocaleString() : 'N/A'} m²).
                    </div>
                    <div class="popup-stats-grid">
                      <div class="popup-stat">
                        <span class="popup-stat-label">Footprint Area</span>
                        <span class="popup-stat-val">${site.area_m2 ? `${site.area_m2.toLocaleString()} m²` : 'N/A'}</span>
                      </div>
                      <div class="popup-stat">
                        <span class="popup-stat-label">Suitability</span>
                        <span class="popup-stat-val">${site.suitability_score !== undefined ? `${site.suitability_score}/100` : 'N/A'}</span>
                      </div>
                      <div class="popup-stat">
                        <span class="popup-stat-label">Mean Slope</span>
                        <span class="popup-stat-val">${typeof site.slope_deg === 'number' ? `${site.slope_deg.toFixed(1)}°` : 'N/A'}</span>
                      </div>
                      <div class="popup-stat">
                        <span class="popup-stat-label">Elevation</span>
                        <span class="popup-stat-val">${typeof site.elevation_m === 'number' ? `${site.elevation_m.toFixed(1)} m` : 'N/A'}</span>
                      </div>
                    </div>
                  </div>
                `);
              }}
            />
          );
        })}

      {/* 3. Top Recommended Pond Site Region Boundary Polygon (Solid Warm Amber / Orange) */}
      {hasValidGeoJSONGeometry(recommended_site?.boundary_geojson) && (
        <GeoJSON
          key={recommendedBoundaryKey}
          data={recommended_site.boundary_geojson}
          style={{
            color: '#d97706',
            weight: 3,
            opacity: 1.0,
            fillColor: '#f59e0b',
            fillOpacity: 0.42,
          }}
          onEachFeature={(feature, layer) => {
            layer.bindPopup(`
              <div class="popup-card">
                <div class="popup-header">
                  <div class="popup-title-group">
                    <span class="popup-title-icon">⭐</span>
                    <span class="popup-title">Recommended Pond Footprint</span>
                  </div>
                  <span class="popup-badge popup-badge-recommended">Top Pick #1</span>
                </div>
                <div class="popup-desc">
                  Optimal contiguous excavation footprint (${recommended_site.area_m2 ? recommended_site.area_m2.toLocaleString() : 'N/A'} m²) with suitability score ${recommended_site.suitability_score}/100.
                </div>
                <div class="popup-stats-grid">
                  <div class="popup-stat">
                    <span class="popup-stat-label">Pond Footprint</span>
                    <span class="popup-stat-val">${recommended_site.area_m2 ? `${recommended_site.area_m2.toLocaleString()} m²` : 'N/A'}</span>
                  </div>
                  <div class="popup-stat">
                    <span class="popup-stat-label">Suitability</span>
                    <span class="popup-stat-val">${recommended_site.suitability_score !== undefined ? `${recommended_site.suitability_score}/100` : 'N/A'}</span>
                  </div>
                  <div class="popup-stat">
                    <span class="popup-stat-label">Mean Slope</span>
                    <span class="popup-stat-val">${typeof recommended_site.slope_deg === 'number' ? `${recommended_site.slope_deg.toFixed(1)}°` : 'N/A'}</span>
                  </div>
                  <div class="popup-stat">
                    <span class="popup-stat-label">Ground Elevation</span>
                    <span class="popup-stat-val">${typeof recommended_site.elevation_m === 'number' ? `${recommended_site.elevation_m.toFixed(1)} m` : 'N/A'}</span>
                  </div>
                </div>
              </div>
            `);
          }}
        />
      )}

      {/* 4. Top Recommended Pond Excavation Site Marker Pin */}
      {recommended_site && typeof recommended_site.latitude === 'number' && typeof recommended_site.longitude === 'number' && (
        <Marker
          position={[recommended_site.latitude, recommended_site.longitude]}
          icon={recommendedIcon}
          zIndexOffset={1000}
        >
          <Popup>
            <div className="popup-card">
              <div className="popup-header">
                <div className="popup-title-group">
                  <span className="popup-title-icon">⭐</span>
                  <span className="popup-title">Recommended Pond Location</span>
                </div>
                <span className="popup-badge popup-badge-recommended">Top Pick #1</span>
              </div>

              <div className="popup-suitability">
                <span className="popup-score-num">{recommended_site.suitability_score}</span>
                <span className="popup-score-label">/ 100 Suitability</span>
              </div>

              <div className="popup-desc">
                {getSuitabilityDescription(recommended_site.suitability_score, recommended_site.slope_deg)}
              </div>

              <div className="popup-stats-grid">
                <div className="popup-stat">
                  <span className="popup-stat-label">Pond Footprint</span>
                  <span className="popup-stat-val">{recommended_site.area_m2 ? `${recommended_site.area_m2.toLocaleString()} m²` : 'N/A'}</span>
                </div>
                <div className="popup-stat">
                  <span className="popup-stat-label">Ground Elevation</span>
                  <span className="popup-stat-val">{typeof recommended_site.elevation_m === 'number' ? `${recommended_site.elevation_m.toFixed(1)} m` : 'N/A'}</span>
                </div>
                <div className="popup-stat">
                  <span className="popup-stat-label">Ground Slope</span>
                  <span className="popup-stat-val">${typeof recommended_site.slope_deg === 'number' ? `${recommended_site.slope_deg.toFixed(1)}°` : 'N/A'}</span>
                </div>
                <div className="popup-stat">
                  <span className="popup-stat-label">Coordinates</span>
                  <span className="popup-stat-val">${recommended_site.latitude.toFixed(4)}° N, ${recommended_site.longitude.toFixed(4)}° E</span>
                </div>
              </div>
            </div>
          </Popup>
        </Marker>
      )}

      {/* 5. Ranked Alternative Candidate Pond Sites Markers */}
      {Array.isArray(alternative_sites) &&
        alternative_sites.map((site, idx) => {
          if (!site || typeof site.latitude !== 'number' || typeof site.longitude !== 'number') return null;
          const siteRank = site.rank || idx + 2;
          return (
            <Marker
              key={site.site_id || `alt-${siteRank}-${site.latitude}`}
              position={[site.latitude, site.longitude]}
              icon={createAlternativePondIcon(siteRank)}
              zIndexOffset={500}
            >
              <Popup>
                <div className="popup-card">
                  <div className="popup-header">
                    <div className="popup-title-group">
                      <span className="popup-title-icon">📍</span>
                      <span className="popup-title">Candidate Location #{siteRank}</span>
                    </div>
                    <span className="popup-badge popup-badge-alternative">Alternative</span>
                  </div>

                  <div className="popup-suitability">
                    <span className="popup-score-num-alt">{site.suitability_score}</span>
                    <span className="popup-score-label">/ 100 Suitability</span>
                  </div>

                  <div className="popup-desc popup-desc-alt">
                    {getSuitabilityDescription(site.suitability_score, site.slope_deg)}
                  </div>

                  <div className="popup-stats-grid">
                    <div className="popup-stat">
                      <span className="popup-stat-label">Pond Footprint</span>
                      <span className="popup-stat-val">{site.area_m2 ? `${site.area_m2.toLocaleString()} m²` : 'N/A'}</span>
                    </div>
                    <div className="popup-stat">
                      <span className="popup-stat-label">Ground Elevation</span>
                      <span className="popup-stat-val">${typeof site.elevation_m === 'number' ? `${site.elevation_m.toFixed(1)} m` : 'N/A'}</span>
                    </div>
                    <div className="popup-stat">
                      <span className="popup-stat-label">Ground Slope</span>
                      <span className="popup-stat-val">${typeof site.slope_deg === 'number' ? `${site.slope_deg.toFixed(1)}°` : 'N/A'}</span>
                    </div>
                    <div className="popup-stat">
                      <span className="popup-stat-label">Coordinates</span>
                      <span className="popup-stat-val">${site.latitude.toFixed(4)}° N, ${site.longitude.toFixed(4)}° E</span>
                    </div>
                  </div>
                </div>
              </Popup>
            </Marker>
          );
        })}
    </>
  );
}
