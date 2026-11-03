import React, { useState } from 'react';
import {
  DEFAULT_SETTINGS,
  LAND_COVER_CN,
  PRESETS,
  RADIUS_LIMITS,
  activePreset,
  presetSettings,
  validateSettings,
  weightShares,
} from '../utils/settings';

function NumberField({ id, label, value, onChange, min, max, step = 1, unit, hint, disabled }) {
  return (
    <label className="settings-field" htmlFor={id}>
      <span className="settings-field-label">
        {label}
        {unit && <span className="settings-field-unit">{unit}</span>}
      </span>
      <input
        id={id}
        type="number"
        className="settings-input"
        value={value ?? ''}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        placeholder={hint}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    </label>
  );
}

/**
 * Analysis settings: preset, selection radius, hydrology inputs, and the
 * advanced terrain/MCDM parameters the backend already accepts.
 *
 * @param {Object} props
 * @param {Object} props.settings - See DEFAULT_SETTINGS.
 * @param {(next: Object) => void} props.onChange
 * @param {boolean} [props.disabled]
 */
export default function AnalysisSettings({ settings, onChange, disabled = false }) {
  const [isOpen, setIsOpen] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const errors = validateSettings(settings);
  const preset = activePreset(settings);
  const shares = weightShares(settings);
  const set = (key) => (value) => onChange({ ...settings, [key]: value });
  const coverMatch = LAND_COVER_CN.find((c) => c.cn === settings.curve_number);

  return (
    <div className="panel settings-panel">
      <button
        type="button"
        className="panel-header settings-toggle"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
      >
        <div className="panel-title-group">
          <span className="panel-icon" aria-hidden="true">02</span>
          <div className="settings-heading">
            <h3 className="panel-title">Analysis settings</h3>
            <span className="settings-summary">
              {PRESETS.find((p) => p.id === preset)?.label || 'Custom'} · {settings.radiusM} m radius · CN {settings.curve_number}
              {settings.design_rainfall_mm ? ` · ${settings.design_rainfall_mm} mm storm` : ' · auto storm'}
            </span>
          </div>
        </div>
        <span className="settings-chevron" aria-hidden="true">{isOpen ? '▲' : '▼'}</span>
      </button>

      {isOpen && (
        <div className="panel-body settings-body">
          <div className="segmented" role="radiogroup" aria-label="Analysis preset">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={preset === p.id}
                className={`segmented-option ${preset === p.id ? 'active' : ''}`}
                onClick={() => onChange(presetSettings(p.id, settings))}
                disabled={disabled}
                title={p.hint}
              >
                <span>{p.label}</span>
                <span className="segmented-hint">{p.hint}</span>
              </button>
            ))}
          </div>

          <label className="settings-field settings-field-wide" htmlFor="radius-slider">
            <span className="settings-field-label">
              Selection radius <span className="settings-field-value">{settings.radiusM} m</span>
            </span>
            <input
              id="radius-slider"
              type="range"
              className="settings-range"
              min={RADIUS_LIMITS.min}
              max={RADIUS_LIMITS.max}
              step={RADIUS_LIMITS.step}
              value={settings.radiusM}
              disabled={disabled}
              onChange={(e) => onChange({ ...settings, radiusM: Number(e.target.value) })}
            />
            <span className="settings-field-hint">
              {(Math.PI * settings.radiusM ** 2 / 10000).toFixed(1)} ha searched for pond sites
            </span>
          </label>

          <div className="settings-group-title">Hydrology</div>
          <div className="settings-grid">
            <label className="settings-field" htmlFor="land-cover">
              <span className="settings-field-label">Land cover</span>
              <select
                id="land-cover"
                className="settings-input"
                value={coverMatch ? String(coverMatch.cn) : 'custom'}
                disabled={disabled}
                onChange={(e) => e.target.value !== 'custom' && set('curve_number')(Number(e.target.value))}
              >
                {LAND_COVER_CN.map((c) => (
                  <option key={c.cn} value={c.cn}>{c.label} (CN {c.cn})</option>
                ))}
                <option value="custom">Custom CN</option>
              </select>
            </label>
            <NumberField id="cn" label="Curve number" value={settings.curve_number} onChange={set('curve_number')} min={30} max={98} disabled={disabled} />
            <NumberField
              id="rain"
              label="Design storm"
              unit="mm / 24 h"
              value={settings.design_rainfall_mm}
              onChange={set('design_rainfall_mm')}
              min={1}
              max={1000}
              hint="Auto · location storm"
              disabled={disabled}
            />
            <NumberField id="depth" label="Pond depth" unit="m" value={settings.pond_design_depth_m} onChange={set('pond_design_depth_m')} min={0.5} max={10} step={0.5} disabled={disabled} />
          </div>

          <button type="button" className="settings-advanced-toggle" onClick={() => setShowAdvanced((v) => !v)} aria-expanded={showAdvanced}>
            {showAdvanced ? '▾' : '▸'} Terrain & ranking parameters
          </button>

          {showAdvanced && (
            <>
              <div className="settings-grid">
                <label className="settings-field" htmlFor="dem-res">
                  <span className="settings-field-label">DEM resolution</span>
                  <select
                    id="dem-res"
                    className="settings-input"
                    value={settings.dem_resolution_m ?? ''}
                    disabled={disabled}
                    onChange={(e) => set('dem_resolution_m')(e.target.value === '' ? null : Number(e.target.value))}
                  >
                    <option value="">Adaptive</option>
                    {[5, 10, 15, 20, 30].map((r) => (
                      <option key={r} value={r}>{r} m{r === 5 ? ' (slow, more memory)' : ''}</option>
                    ))}
                  </select>
                </label>
                <NumberField id="sites" label="Candidate sites" value={settings.max_candidate_sites} onChange={set('max_candidate_sites')} min={1} max={20} disabled={disabled} />
                <NumberField id="ideal" label="Ideal slope" unit="°" value={settings.ideal_slope_deg} onChange={set('ideal_slope_deg')} min={0} max={30} step={0.5} disabled={disabled} />
                <NumberField id="maxslope" label="Max slope" unit="°" value={settings.max_slope_deg} onChange={set('max_slope_deg')} min={0.5} max={45} step={0.5} disabled={disabled} />
                <NumberField id="threshold" label="Min suitability" unit="/100" value={settings.suitability_threshold} onChange={set('suitability_threshold')} min={0} max={100} disabled={disabled} />
                <NumberField id="minarea" label="Min footprint" unit="m²" value={settings.min_pond_area_m2} onChange={set('min_pond_area_m2')} min={10} max={100000} step={10} disabled={disabled} />
                <NumberField id="maxfootprint" label="Max footprint" unit="m²" value={settings.max_pond_footprint_m2} onChange={set('max_pond_footprint_m2')} min={100} max={500000} step={500} disabled={disabled} />
              </div>

              <div className="settings-group-title">Suitability weights</div>
              {[
                ['weight_slope', 'Gentle slope', shares.slope],
                ['weight_depression', 'Natural depression', shares.depression],
                ['weight_twi', 'Wetness (TWI)', shares.twi],
              ].map(([key, label, share]) => (
                <label key={key} className="settings-weight" htmlFor={key}>
                  <span className="settings-weight-label">{label}</span>
                  <input
                    id={key}
                    type="range"
                    className="settings-range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={settings[key]}
                    disabled={disabled}
                    onChange={(e) => set(key)(Number(e.target.value))}
                  />
                  <span className="settings-weight-share" title="Effective share after normalisation">
                    {Math.round(share * 100)}%
                  </span>
                </label>
              ))}
            </>
          )}

          {errors.length > 0 && (
            <ul className="settings-errors" role="alert">
              {errors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}

          <div className="settings-footer">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => onChange({ ...DEFAULT_SETTINGS })}
              disabled={disabled}
            >
              Reset to defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
