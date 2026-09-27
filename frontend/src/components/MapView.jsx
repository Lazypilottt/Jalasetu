import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, useMap, LayersControl, Circle, Marker, Popup, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import ResultsLayer, { computeCombinedResultsBounds, hasValidGeoJSONGeometry } from './ResultsLayer';

// Fix default Leaflet icon paths in Vite / Webpack asset bundling environments
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Generic geographic center of the Indian subcontinent (national scale overview)
const GENERIC_DEFAULT_CENTER = [20.5937, 78.9629];
const GENERIC_DEFAULT_ZOOM = 5;
const DEFAULT_FIT_BOUNDS_OPTIONS = Object.freeze({ padding: [50, 50], maxZoom: 17 });

/**
 * MapLegend Component
 *
 * Explains what each map color and layer shape represents:
 * - Recommended pond footprint polygon (warm amber/orange solid)
 * - Alternative candidate footprints polygons (muted slate dashed)
 * - Upstream catchment drainage area (translucent blue dashed)
 * - Site centroid location markers
 *
 * @param {Object} props
 * @param {Object} props.analysisData - CatchmentResponse object.
 * @param {boolean} [props.isOpen=true] - Expanded or collapsed state.
 * @param {Function} [props.onToggle] - Toggle callback.
 */
export function MapLegend({ analysisData, selectedArea = null, isOpen = true, onToggle }) {
  if (!analysisData) return null;

  const hasRecBoundary = hasValidGeoJSONGeometry(analysisData.recommended_site?.boundary_geojson);
  const hasAltBoundary = Boolean(
    analysisData.alternative_sites?.some((s) => hasValidGeoJSONGeometry(s?.boundary_geojson))
  );
  const hasCatchmentBoundary = hasValidGeoJSONGeometry(analysisData.catchment?.boundary_geojson);

  return (
    <div className="map-legend" role="complementary" aria-label="Map Legend">
      <div className="legend-header">
        <span className="legend-title">Map Layers</span>
        {typeof onToggle === 'function' && (
          <button
            type="button"
            className="legend-toggle-btn"
            onClick={onToggle}
            title={isOpen ? 'Collapse legend' : 'Expand legend'}
            aria-label={isOpen ? 'Collapse legend' : 'Expand legend'}
          >
            {isOpen ? '−' : '+'}
          </button>
        )}
      </div>

      {isOpen && (
        <div className="legend-section">
          {selectedArea && (
            <div className="legend-item">
              <div className="legend-swatch legend-swatch-selected-area"></div>
              <div className="legend-text-group">
                <span className="legend-item-label">Selected Land Area</span>
                <span className="legend-item-sub">Green circle used to prioritize sites</span>
              </div>
            </div>
          )}
          {/* 1. Recommended Pond Excavation Footprint Polygon */}
          {hasRecBoundary ? (
            <div className="legend-item">
              <div className="legend-swatch legend-swatch-rec-footprint"></div>
              <div className="legend-text-group">
                <span className="legend-item-label">Recommended Footprint</span>
                <span className="legend-item-sub">Solid amber/orange excavation zone</span>
              </div>
            </div>
          ) : (
            analysisData.recommended_site && (
              <div className="legend-item">
                <div className="legend-marker-preview legend-marker-rec">1</div>
                <div className="legend-text-group">
                  <span className="legend-item-label">Recommended Site (#1)</span>
                  <span className="legend-item-sub">Top pick location pin</span>
                </div>
              </div>
            )
          )}

          {/* 2. Alternative Sites Footprints Polygons */}
          {hasAltBoundary ? (
            <div className="legend-item">
              <div className="legend-swatch legend-swatch-alt-footprint"></div>
              <div className="legend-text-group">
                <span className="legend-item-label">Alternative Sites</span>
                <span className="legend-item-sub">Muted secondary candidate zones</span>
              </div>
            </div>
          ) : (
            analysisData.alternative_sites &&
            analysisData.alternative_sites.length > 0 && (
              <div className="legend-item">
                <div className="legend-marker-preview legend-marker-alt">#2</div>
                <div className="legend-text-group">
                  <span className="legend-item-label">Alternative Candidates</span>
                  <span className="legend-item-sub">Ranked secondary site pins</span>
                </div>
              </div>
            )
          )}

          {/* 3. Upstream Catchment Drainage Area Polygon */}
          {hasCatchmentBoundary && (
            <div className="legend-item">
              <div className="legend-swatch legend-swatch-catchment"></div>
              <div className="legend-text-group">
                <span className="legend-item-label">Catchment Basin</span>
                <span className="legend-item-sub">Blue upstream runoff drainage area</span>
              </div>
            </div>
          )}

          {/* 4. Centroid Markers Preview */}
          {(hasRecBoundary || hasAltBoundary || hasCatchmentBoundary) && (
            <div className="legend-item">
              <div className="legend-marker-preview legend-marker-rec">1</div>
              <div className="legend-text-group">
                <span className="legend-item-label">Location Pin Markers</span>
                <span className="legend-item-sub">Centroid pins with metrics popup</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MapResultSummary({ analysisData }) {
  const site = analysisData?.recommended_site;
  const catchment = analysisData?.catchment;
  if (!site && !catchment) return null;

  const formatNumber = (value, digits = 0) =>
    typeof value === 'number' && Number.isFinite(value)
      ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
      : 'Not available';

  return (
    <div className="map-result-summary" role="region" aria-label="Map result summary">
      <div className="map-result-summary-title">Analysis outputs</div>
      {site && (
        <div className="map-result-summary-item">
          <span>Suggested pond</span>
          <strong>
            {typeof site.latitude === 'number' ? site.latitude.toFixed(4) : 'N/A'},
            {' '}
            {typeof site.longitude === 'number' ? site.longitude.toFixed(4) : 'N/A'}
          </strong>
        </div>
      )}
      {catchment && (
        <div className="map-result-summary-item">
          <span>Catchment area</span>
          <strong>{formatNumber(catchment.area_hectares, 2)} ha</strong>
        </div>
      )}
      {site && (
        <div className="map-result-summary-item">
          <span>Expected water volume</span>
          <strong>{formatNumber(site.storage_capacity_m3 ?? catchment?.estimated_runoff_volume_m3)} m³</strong>
        </div>
      )}
      {catchment?.estimated_runoff_volume_m3 !== undefined && (
        <div className="map-result-summary-item map-result-summary-secondary">
          <span>Design storm runoff</span>
          <strong>{formatNumber(catchment.estimated_runoff_volume_m3)} m³</strong>
        </div>
      )}
    </div>
  );
}

/**
 * Normalizes bounds into standard Leaflet [[south, west], [north, east]] LatLngBounds format.
 *
 * @param {Array|Object} bounds - Bounding coordinates in various formats.
 * @returns {[[number, number], [number, number]] | null}
 */
export function normalizeBounds(bounds) {
  if (!bounds) return null;

  // Format 1: [[south, west], [north, east]]
  if (Array.isArray(bounds) && bounds.length === 2) {
    const [p1, p2] = bounds;
    if (Array.isArray(p1) && Array.isArray(p2) && p1.length >= 2 && p2.length >= 2) {
      const lat1 = Number(p1[0]);
      const lng1 = Number(p1[1]);
      const lat2 = Number(p2[0]);
      const lng2 = Number(p2[1]);

      if (!isNaN(lat1) && !isNaN(lng1) && !isNaN(lat2) && !isNaN(lng2)) {
        const south = Math.min(lat1, lat2);
        const north = Math.max(lat1, lat2);
        const west = Math.min(lng1, lng2);
        const east = Math.max(lng1, lng2);
        return [[south, west], [north, east]];
      }
    }
  }

  // Format 2: Flat array [south, west, north, east] or [minLon, minLat, maxLon, maxLat]
  if (Array.isArray(bounds) && bounds.length === 4) {
    const [a, b, c, d] = bounds.map(Number);
    if (!isNaN(a) && !isNaN(b) && !isNaN(c) && !isNaN(d)) {
      if (Math.abs(a) <= 90 && Math.abs(c) <= 90) {
        return [
          [Math.min(a, c), Math.min(b, d)],
          [Math.max(a, c), Math.max(b, d)],
        ];
      } else {
        return [
          [Math.min(b, d), Math.min(a, c)],
          [Math.max(b, d), Math.max(a, c)],
        ];
      }
    }
  }

  return null;
}

/**
 * Child component that automatically fits map view whenever bounds change.
 */
function MapBoundsController({ bounds, fitBoundsOptions = {} }) {
  const map = useMap();

  useEffect(() => {
    if (!map || !bounds) return;

    const normalized = normalizeBounds(bounds);
    if (normalized) {
      try {
        map.fitBounds(normalized, {
          padding: [50, 50],
          maxZoom: 17,
          animate: true,
          ...fitBoundsOptions,
        });
      } catch (err) {
        console.warn('[MapView] fitBounds error:', err);
      }
    }
  }, [map, bounds, fitBoundsOptions]);

  return null;
}

/**
 * Child component that smoothly flies the map view to a focused pond site.
 */
function MapFocusController({ focusedSite, zoom = 16 }) {
  const map = useMap();

  useEffect(() => {
    if (!map || !focusedSite) return;
    const { latitude, longitude } = focusedSite;
    if (typeof latitude === 'number' && typeof longitude === 'number') {
      try {
        map.flyTo([latitude, longitude], zoom, {
          duration: 1.2,
          easeLinearity: 0.25,
        });
      } catch (err) {
        console.warn('[MapView] flyTo site error:', err);
      }
    }
  }, [map, focusedSite, zoom]);

  return null;
}

// Sync base layer selection with Leaflet LayersControl events
function BaseLayerSync({ setSelectedBase }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const handler = (e) => {
      if (e && e.name) setSelectedBase(e.name);
    };
    map.on('baselayerchange', handler);
    return () => map.off('baselayerchange', handler);
  }, [map, setSelectedBase]);
  return null;
}

function AreaSelectionController({ radiusM, onSelect }) {
  useMapEvents({
    click(event) {
      onSelect({ latitude: event.latlng.lat, longitude: event.latlng.lng, radiusM });
    },
  });
  return null;
}

/**
 * MapView Component
 *
 * Renders an interactive Leaflet map with OpenStreetMap tiles as base.
 * Automatically renders ResultsLayer when analysisData is passed and dynamically fits
 * the view to the combined bounds of the catchment boundary polygon and all candidate markers.
 *
 * @param {Object} props
 * @param {Array} [props.bounds] - Explicit bounding box [[south, west], [north, east]] to fit view.
 * @param {Object} [props.analysisData] - CatchmentResponse object containing recommended_site, alternative_sites, and catchment.
 * @param {Object} [props.focusedSite] - Specific PondSiteSummary object to pan/focus to.
 * @param {Array<number>} [props.center] - Optional center coordinates [lat, lng].
 * @param {number} [props.zoom] - Optional zoom level.
 * @param {Array<number>} [props.defaultCenter] - Fallback generic center (defaults to national centroid).
 * @param {number} [props.defaultZoom] - Fallback generic zoom (defaults to 5).
 * @param {string} [props.placeholderMessage] - Empty state message when no data is present.
 * @param {boolean} [props.showPlaceholder] - Override to force show/hide placeholder overlay.
 * @param {boolean} [props.showLegend=true] - Show floating legend when analysis data is active.
 * @param {Object} [props.fitBoundsOptions] - Options passed to map.fitBounds().
 * @param {boolean} [props.scrollWheelZoom=true] - Enable scroll-wheel zoom.
 * @param {string} [props.className] - Additional CSS classes.
 * @param {React.ReactNode} [props.children] - Additional child map layers.
 */
export default function MapView({
  bounds = null,
  analysisData = null,
  focusedSite = null,
  center = null,
  zoom = null,
  defaultCenter = GENERIC_DEFAULT_CENTER,
  defaultZoom = GENERIC_DEFAULT_ZOOM,
  placeholderMessage = 'Upload a contour map to see analysis results here.',
  showPlaceholder,
  showLegend = true,
  fitBoundsOptions = DEFAULT_FIT_BOUNDS_OPTIONS,
  scrollWheelZoom = true,
  className = '',
  children = null,
  selectedArea = null,
  onAreaSelect = () => {},
  selectionRadiusM = 250,
}) {
  // 1. Dynamically compute combined bounding box from response data or explicit bounds
  const effectiveBounds = useMemo(() => {
    if (bounds) return bounds;
    if (selectedArea) {
      const radius = selectedArea.radiusM || selectedArea.radius_m || selectionRadiusM;
      const latDelta = radius / 111320;
      const lonDelta = radius / (111320 * Math.max(0.2, Math.cos((selectedArea.latitude * Math.PI) / 180)));
      const selectionBounds = [
        [selectedArea.latitude - latDelta, selectedArea.longitude - lonDelta],
        [selectedArea.latitude + latDelta, selectedArea.longitude + lonDelta],
      ];
      const resultBounds = analysisData ? computeCombinedResultsBounds(analysisData) : null;
      if (!resultBounds) return selectionBounds;
      return [
        [
          Math.min(selectionBounds[0][0], resultBounds[0][0]),
          Math.min(selectionBounds[0][1], resultBounds[0][1]),
        ],
        [
          Math.max(selectionBounds[1][0], resultBounds[1][0]),
          Math.max(selectionBounds[1][1], resultBounds[1][1]),
        ],
      ];
    }
    if (analysisData) {
      return computeCombinedResultsBounds(analysisData);
    }
    return null;
  }, [bounds, analysisData, selectedArea, selectionRadiusM]);

  // 2. Generic initial center and zoom
  const initialCenter = center || defaultCenter;
  const initialZoom = zoom !== null && zoom !== undefined ? zoom : defaultZoom;

  // Persist user's selected base layer (default to Satellite)
  const [selectedBase, setSelectedBase] = useState('Satellite');
  const [isLegendOpen, setIsLegendOpen] = useState(true);

  // 3. Determine if empty state placeholder overlay should be visible
  const hasAnalysisData = Boolean(
    analysisData?.recommended_site ||
      analysisData?.catchment?.boundary_geojson ||
      (analysisData?.alternative_sites && analysisData.alternative_sites.length > 0)
  );
  const hasData = Boolean(effectiveBounds || hasAnalysisData || children);
  const isPlaceholderVisible = showPlaceholder !== undefined ? showPlaceholder : !hasData;

  return (
    <div className={`map-view-container ${className}`}>
      {/* Map Header Overlay Badge */}
      <div className="map-overlay-badge">
        <span className="live-dot"></span>
        <span>Interactive GIS Map</span>
      </div>

      <div className="map-selection-hint" role="status">
        <span className="map-selection-hint-icon">⌖</span>
        <span>{selectedArea ? 'Click the map to move the selected area' : 'Click the map to select a 250 m area'}</span>
      </div>

      {hasAnalysisData && <MapResultSummary analysisData={analysisData} />}

      {/* Empty State Overlay */}
      {isPlaceholderVisible && (
        <div className="map-placeholder-overlay" role="status" aria-live="polite">
          <div className="map-placeholder-card">
            <span className="placeholder-icon" aria-hidden="true">MAP</span>
            <div className="placeholder-text-group">
              <span className="placeholder-title">Map Ready</span>
              <span className="placeholder-text">{placeholderMessage}</span>
            </div>
          </div>
        </div>
      )}

      {/* Floating Map Legend (Visible when analysis results are loaded) */}
      {showLegend && hasAnalysisData && (
        <MapLegend
          analysisData={analysisData}
          selectedArea={selectedArea}
          isOpen={isLegendOpen}
          onToggle={() => setIsLegendOpen((prev) => !prev)}
        />
      )}

      {/* Interactive Leaflet Map Container */}
      <MapContainer
        center={initialCenter}
        zoom={initialZoom}
        scrollWheelZoom={scrollWheelZoom}
        className="leaflet-map"
      >
        {/* Base layer control: Street, Satellite (default), Hybrid */}
        <BaseLayerSync setSelectedBase={setSelectedBase} />
        <AreaSelectionController radiusM={selectionRadiusM} onSelect={onAreaSelect} />
        <LayersControl position="bottomright">
          <LayersControl.BaseLayer checked={selectedBase === 'Satellite'} name="Satellite">
            <>
              <TileLayer
                attribution='Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                maxZoom={19}
              />
            </>
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer checked={selectedBase === 'Street'} name="Street">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
            />
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer checked={selectedBase === 'Hybrid'} name="Hybrid">
            <>
              <TileLayer
                attribution='Tiles &copy; Esri &mdash; Imagery'
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                maxZoom={19}
              />
              {/* Esri reference/labels overlay on top for hybrid */}
              <TileLayer
                url="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
                maxZoom={19}
                pointerEvents="none"
              />
            </>
          </LayersControl.BaseLayer>
        </LayersControl>

        {/* Dynamic Bounds Synchronization Controller */}
        {effectiveBounds && (
          <MapBoundsController
            bounds={effectiveBounds}
            fitBoundsOptions={fitBoundsOptions}
          />
        )}

        {/* Dynamic Map FlyTo Focus Controller */}
        {focusedSite && <MapFocusController focusedSite={focusedSite} />}

        {/* Built-in Results Layer for CatchmentResponse */}
        {analysisData && <ResultsLayer data={analysisData} />}

        {selectedArea && (
          <>
            <Circle
              center={[selectedArea.latitude, selectedArea.longitude]}
              radius={selectedArea.radiusM || selectedArea.radius_m || selectionRadiusM}
              pathOptions={{
                color: '#16a34a',
                weight: 2,
                dashArray: '8 6',
                fillColor: '#86efac',
                fillOpacity: 0.16,
              }}
            >
              <Popup>
                <strong>Selected analysis area</strong>
                <br />
                Click Analyze to prioritize pond sites in this area.
              </Popup>
            </Circle>
            <Marker position={[selectedArea.latitude, selectedArea.longitude]}>
              <Popup>Selected land centre</Popup>
            </Marker>
          </>
        )}

        {/* Extensible Children for custom markers/overlays */}
        {children}
      </MapContainer>
    </div>
  );
}
