import React from 'react';
import { INFRASTRUCTURE_CATEGORIES, TERRAIN_SOURCES, enabledCategories } from '../utils/settings';

/** Mirrors survey_radius_for() in app/services/exclusions.py. */
export function surveyRadiusFor(radiusM) {
  return radiusM + Math.max(150, 0.5 * radiusM);
}

function PreviewStatus({ preview, surveyRadius }) {
  if (preview.loading) {
    return (
      <div className="constraint-status constraint-status-loading" role="status">
        <span className="loading-spinner-sm" aria-hidden="true"></span>
        Checking OpenStreetMap within {Math.round(surveyRadius)} m…
      </div>
    );
  }
  if (preview.error) {
    return <div className="constraint-status constraint-status-warning" role="status">Preview failed: {preview.error}</div>;
  }
  const data = preview.data;
  if (!data) return null;
  if (data.status !== 'ok') {
    return (
      <div className="constraint-status constraint-status-warning" role="status">
        OpenStreetMap is not responding. The analysis will retry, and you can mark no-build zones by hand.
      </div>
    );
  }
  const total = Object.values(data.counts || {}).reduce((a, b) => a + b, 0);
  return (
    <div className="constraint-status" role="status">
      {total > 0
        ? `${total} mapped feature${total === 1 ? '' : 's'} within ${Math.round(data.radius_m)} m${data.cached ? ' (cached)' : ''}.`
        : `Nothing mapped within ${Math.round(data.radius_m)} m — OSM coverage may be incomplete; mark zones by hand.`}
    </div>
  );
}

/**
 * Site constraints: what the recommendation must avoid (OpenStreetMap
 * infrastructure by category, plus user-marked no-build zones) and which
 * terrain source the selected point will use.
 */
export default function SiteConstraintsPanel({
  settings,
  onSettingsChange,
  selectedArea,
  preview,
  terrainPlan,
  manualZones,
  onRemoveZone,
  onClearZones,
  markMode,
  onToggleMarkMode,
  zoneRadius,
  onZoneRadiusChange,
  disabled = false,
}) {
  const enabled = enabledCategories(settings);
  const counts = preview.data?.status === 'ok' ? preview.data.counts || {} : {};
  const surveyRadius = selectedArea ? surveyRadiusFor(selectedArea.radiusM) : null;

  const toggleCategory = (id) => {
    const next = enabled.includes(id) ? enabled.filter((c) => c !== id) : [...enabled, id];
    const all = next.length === INFRASTRUCTURE_CATEGORIES.length;
    onSettingsChange({ ...settings, exclusion_categories: all ? null : INFRASTRUCTURE_CATEGORIES.map((c) => c.id).filter((c) => next.includes(c)) });
  };

  return (
    <div className="panel constraints-panel" role="region" aria-label="Site constraints">
      <div className="panel-header">
        <div className="panel-title-group">
          <span className="panel-icon" aria-hidden="true">03</span>
          <div className="settings-heading">
            <h3 className="panel-title">Site constraints</h3>
            <span className="settings-summary">Keep ponds off existing infrastructure</span>
          </div>
        </div>
        <label className="switch" title="Avoid mapped infrastructure">
          <input
            type="checkbox"
            checked={settings.avoid_infrastructure}
            onChange={(e) => onSettingsChange({ ...settings, avoid_infrastructure: e.target.checked })}
            disabled={disabled}
          />
          <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
          <span className="sr-only">Avoid mapped infrastructure</span>
        </label>
      </div>

      <div className="panel-body constraints-body">
        {terrainPlan && (
          <div className={`terrain-plan terrain-plan-${terrainPlan.id}`}>
            <span className="terrain-plan-label">Terrain</span>
            <strong>{terrainPlan.label}</strong>
            <span className="terrain-plan-hint">{terrainPlan.hint}</span>
          </div>
        )}

        <div className="segmented segmented-compact" role="radiogroup" aria-label="Terrain source">
          {TERRAIN_SOURCES.map((source) => (
            <button
              key={source.id}
              type="button"
              role="radio"
              aria-checked={settings.terrain_source === source.id}
              className={`segmented-option ${settings.terrain_source === source.id ? 'active' : ''}`}
              onClick={() => onSettingsChange({ ...settings, terrain_source: source.id })}
              disabled={disabled}
              title={source.hint}
            >
              {source.label}
            </button>
          ))}
        </div>

        {settings.avoid_infrastructure ? (
          <>
            {selectedArea ? (
              <PreviewStatus preview={preview} surveyRadius={surveyRadius} />
            ) : (
              <div className="constraint-status">Select a point to preview nearby infrastructure.</div>
            )}

            <ul className="constraint-list">
              {INFRASTRUCTURE_CATEGORIES.map((category) => {
                const on = enabled.includes(category.id);
                const count = counts[category.id] || 0;
                return (
                  <li key={category.id}>
                    <label className={`constraint-chip ${on ? 'on' : ''}`}>
                      <input type="checkbox" checked={on} onChange={() => toggleCategory(category.id)} disabled={disabled} />
                      <span className={`constraint-swatch swatch-${category.id}`} aria-hidden="true" />
                      <span className="constraint-name">{category.label}</span>
                      <span className="constraint-meta">
                        {count > 0 && <span className="constraint-count">{count}</span>}
                        <span className="constraint-buffer">
                          {Math.round(category.buffer * settings.exclusion_buffer_scale)} m
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>

            <label className="settings-field settings-field-wide" htmlFor="buffer-scale">
              <span className="settings-field-label">
                Safety buffer <span className="settings-field-value">×{settings.exclusion_buffer_scale.toFixed(1)}</span>
              </span>
              <input
                id="buffer-scale"
                type="range"
                className="settings-range"
                min={0}
                max={3}
                step={0.25}
                value={settings.exclusion_buffer_scale}
                disabled={disabled}
                onChange={(e) => onSettingsChange({ ...settings, exclusion_buffer_scale: Number(e.target.value) })}
              />
            </label>
          </>
        ) : (
          <div className="constraint-status constraint-status-warning">
            Infrastructure avoidance is off: sites may overlap rivers, roads or buildings.
          </div>
        )}

        <div className="manual-zones">
          <div className="manual-zones-header">
            <span className="settings-group-title">Marked no-build zones</span>
            {manualZones.length > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={onClearZones} disabled={disabled}>
                Clear all
              </button>
            )}
          </div>
          <div className="manual-zones-controls">
            <button
              type="button"
              className={`btn btn-sm ${markMode ? 'btn-danger-solid' : 'btn-outline'}`}
              onClick={onToggleMarkMode}
              disabled={disabled}
              aria-pressed={markMode}
            >
              {markMode ? 'Done marking' : '+ Mark on map'}
            </button>
            <label className="manual-zone-radius">
              Radius
              <input
                type="number"
                className="settings-input"
                min={5}
                max={500}
                step={5}
                value={zoneRadius}
                onChange={(e) => onZoneRadiusChange(Math.max(5, Math.min(500, Number(e.target.value) || 25)))}
              />
              m
            </label>
          </div>
          {markMode && <p className="manual-zones-hint">Click the map to mark a well, school, field boundary or anything else to avoid.</p>}
          {manualZones.length > 0 && (
            <ul className="manual-zone-list">
              {manualZones.map((zone, index) => (
                <li key={zone.id}>
                  <span className="manual-zone-dot" aria-hidden="true" />
                  <span className="manual-zone-text">
                    Zone {index + 1} · {zone.radius_m} m · {zone.lat.toFixed(5)}, {zone.lon.toFixed(5)}
                  </span>
                  <button type="button" className="icon-btn" onClick={() => onRemoveZone(zone.id)} aria-label={`Remove zone ${index + 1}`} disabled={disabled}>
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
