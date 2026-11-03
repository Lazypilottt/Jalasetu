import React, { useEffect, useRef, useState } from 'react';
import { Circle, GeoJSON, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import { searchPlaces } from '../api/catchmentApi';
import { INFRASTRUCTURE_CATEGORIES } from '../utils/settings';

/** Map colours per infrastructure category (also used by the legend swatches). */
export const CATEGORY_COLORS = {
  water: '#0ea5e9',
  waterway: '#38bdf8',
  building: '#f97316',
  facility: '#e11d48',
  road: '#a3a3a3',
  railway: '#78716c',
  settlement: '#f59e0b',
  well: '#06b6d4',
  manual: '#ef4444',
};

const CATEGORY_LABELS = Object.fromEntries(INFRASTRUCTURE_CATEGORIES.map((c) => [c.id, c.label]));

/* ---------- inside <MapContainer> ---------- */

/** Hands the Leaflet map instance to overlays rendered outside the container. */
export function MapInstanceBridge({ onReady }) {
  const map = useMap();
  useEffect(() => {
    onReady(map);
  }, [map, onReady]);
  return null;
}

export function ScaleBar() {
  const map = useMap();
  useEffect(() => {
    const control = L.control.scale({ position: 'bottomleft', imperial: false, maxWidth: 140 });
    control.addTo(map);
    return () => control.remove();
  }, [map]);
  return null;
}

export function CursorTracker({ onMove }) {
  useMapEvents({
    mousemove(event) {
      onMove({ lat: event.latlng.lat, lng: event.latlng.lng });
    },
    mouseout() {
      onMove(null);
    },
  });
  return null;
}

/** Mapped infrastructure (preview or result), no-build zones, and marked zones. */
export function InfrastructureLayer({ features, zones, manualZones, show }) {
  return (
    <>
      {show.zones && zones?.features?.length > 0 && (
        <GeoJSON
          key={`zones-${zones.features.length}-${zones.features.map((f) => f.properties?.area_m2).join('-')}`}
          data={zones}
          style={(feature) => ({
            color: '#ef4444',
            weight: 1.2,
            dashArray: '4 4',
            fillColor: '#ef4444',
            fillOpacity: 0.18,
            className: 'nobuild-zone',
          })}
          onEachFeature={(feature, layer) => {
            const p = feature.properties || {};
            layer.bindTooltip(
              `<strong>No-build: ${p.label || p.category}</strong><br/>${p.count} feature(s)` +
                (p.buffer_m != null ? ` · ${p.buffer_m} m buffer` : '') +
                `<br/>${Math.round(p.area_m2 || 0).toLocaleString()} m² masked`,
              { sticky: true, className: 'map-tooltip' }
            );
          }}
        />
      )}
      {show.infrastructure && features?.features?.length > 0 && (
        <GeoJSON
          key={`infra-${features.features.length}`}
          data={features}
          pointToLayer={(feature, latlng) =>
            L.circleMarker(latlng, {
              radius: 6,
              color: '#ffffff',
              weight: 1.5,
              fillColor: CATEGORY_COLORS[feature.properties?.category] || '#64748b',
              fillOpacity: 0.95,
            })
          }
          style={(feature) => {
            const color = CATEGORY_COLORS[feature.properties?.category] || '#64748b';
            const isLine = feature.geometry?.type === 'LineString';
            return { color, weight: isLine ? 3 : 1.2, fillColor: color, fillOpacity: isLine ? 0 : 0.35 };
          }}
          onEachFeature={(feature, layer) => {
            const p = feature.properties || {};
            layer.bindTooltip(`${p.name ? `<strong>${p.name}</strong><br/>` : ''}${CATEGORY_LABELS[p.category] || p.category}`, {
              sticky: true,
              className: 'map-tooltip',
            });
          }}
        />
      )}
      {show.manual &&
        manualZones.map((zone) => (
          <Circle
            key={zone.id}
            center={[zone.lat, zone.lon]}
            radius={zone.radius_m}
            pathOptions={{ color: '#ef4444', weight: 2, dashArray: '2 5', fillColor: '#ef4444', fillOpacity: 0.22 }}
          />
        ))}
    </>
  );
}

/* ---------- overlays outside <MapContainer> ---------- */

export function PlaceSearch({ map, onPick }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [status, setStatus] = useState('idle'); // idle | searching | empty | error
  const [open, setOpen] = useState(false);
  const controllerRef = useRef(null);

  useEffect(() => {
    if (query.trim().length < 3) {
      setResults([]);
      setStatus('idle');
      return undefined;
    }
    const timer = setTimeout(async () => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setStatus('searching');
      try {
        const found = await searchPlaces(query, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setResults(found);
        setStatus(found.length ? 'idle' : 'empty');
        setOpen(true);
      } catch {
        if (!controller.signal.aborted) setStatus('error');
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [query]);

  const pick = (place) => {
    setOpen(false);
    setQuery(place.name);
    map?.flyTo([place.latitude, place.longitude], 16, { duration: 1.1 });
    onPick?.(place);
  };

  return (
    <div className="map-search" role="search">
      <span className="map-search-icon" aria-hidden="true">⌕</span>
      <input
        type="search"
        className="map-search-input"
        placeholder="Search village, town or lat, lon"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && results[0]) pick(results[0]);
          if (e.key === 'Escape') setOpen(false);
        }}
        aria-label="Search for a place"
        aria-expanded={open}
        aria-controls="map-search-results"
      />
      {status === 'searching' && <span className="loading-spinner-sm map-search-spinner" aria-hidden="true" />}
      {open && (results.length > 0 || status === 'empty' || status === 'error') && (
        <ul className="map-search-results" id="map-search-results" role="listbox">
          {results.map((place) => (
            <li key={`${place.latitude},${place.longitude}`}>
              <button type="button" onClick={() => pick(place)} role="option" aria-selected="false">
                <span className="map-search-name">{place.name}</span>
                <span className="map-search-detail">{place.detail}</span>
              </button>
            </li>
          ))}
          {status === 'empty' && <li className="map-search-empty">No places found</li>}
          {status === 'error' && <li className="map-search-empty">Search unavailable — try coordinates</li>}
        </ul>
      )}
    </div>
  );
}

export function MapHud({ cursor, map, selectionRadiusM, clickMode }) {
  const [zoom, setZoom] = useState(map?.getZoom() ?? null);
  useEffect(() => {
    if (!map) return undefined;
    const update = () => setZoom(map.getZoom());
    update();
    map.on('zoomend', update);
    return () => map.off('zoomend', update);
  }, [map]);
  return (
    <div className="map-hud" aria-live="off">
      <span className="map-hud-item">
        <span className="map-hud-key">LAT</span>
        {cursor ? cursor.lat.toFixed(5) : '—'}
      </span>
      <span className="map-hud-item">
        <span className="map-hud-key">LON</span>
        {cursor ? cursor.lng.toFixed(5) : '—'}
      </span>
      <span className="map-hud-item">
        <span className="map-hud-key">Z</span>
        {zoom ?? '—'}
      </span>
      <span className={`map-hud-item map-hud-mode ${clickMode === 'zone' ? 'map-hud-mode-zone' : ''}`}>
        {clickMode === 'zone' ? 'CLICK · MARK NO-BUILD ZONE' : `CLICK · SELECT ${selectionRadiusM} m`}
      </span>
    </div>
  );
}

export function MapActionButtons({ map, isFullscreen, onToggleFullscreen, onLocate }) {
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState(null);

  const locate = () => {
    if (!navigator.geolocation) {
      setError('Location is not available in this browser');
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        map?.flyTo([pos.coords.latitude, pos.coords.longitude], 16, { duration: 1.1 });
        onLocate?.({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
      },
      () => {
        setLocating(false);
        setError('Location permission denied');
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  return (
    <div className="map-actions" role="toolbar" aria-label="Map actions">
      <button type="button" className="map-action-btn" onClick={locate} title="Go to my location" aria-label="Go to my location">
        {locating ? <span className="loading-spinner-sm" aria-hidden="true" /> : '◎'}
      </button>
      <button
        type="button"
        className="map-action-btn"
        onClick={onToggleFullscreen}
        title={isFullscreen ? 'Exit full screen' : 'Full-screen map'}
        aria-label={isFullscreen ? 'Exit full screen' : 'Full-screen map'}
        aria-pressed={isFullscreen}
      >
        {isFullscreen ? '⤡' : '⤢'}
      </button>
      {error && <span className="map-action-error" role="status">{error}</span>}
    </div>
  );
}

export const LAYER_OPTIONS = [
  { id: 'contours', label: 'Contours' },
  { id: 'catchment', label: 'Catchment' },
  { id: 'sites', label: 'Pond sites' },
  { id: 'zones', label: 'No-build zones' },
  { id: 'infrastructure', label: 'Mapped infrastructure' },
  { id: 'manual', label: 'Marked zones' },
];

export function LayerPanel({ layers, onChange }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`layer-panel ${open ? 'open' : ''}`}>
      <button type="button" className="map-action-btn layer-panel-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open} title="Overlay layers">
        ☰ <span className="layer-panel-label">Layers</span>
      </button>
      {open && (
        <ul className="layer-panel-list">
          {LAYER_OPTIONS.map((option) => (
            <li key={option.id}>
              <label>
                <input
                  type="checkbox"
                  checked={layers[option.id]}
                  onChange={(e) => onChange({ ...layers, [option.id]: e.target.checked })}
                />
                {option.label}
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
