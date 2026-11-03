/**
 * Analysis settings: defaults mirror DEFAULT_PIPELINE_PARAMS in
 * app/services/pipeline.py. Only values that differ from the defaults are sent,
 * so the backend stays the source of truth for anything left untouched.
 */

export const DEFAULT_SETTINGS = Object.freeze({
  radiusM: 250,
  dem_resolution_m: null, // null = adaptive
  ideal_slope_deg: 3,
  max_slope_deg: 8,
  weight_slope: 0.35,
  weight_depression: 0.35,
  weight_twi: 0.3,
  suitability_threshold: 60,
  min_pond_area_m2: 200,
  max_candidate_sites: 5,
  pond_design_depth_m: 2,
  design_rainfall_mm: null, // null = backend default (100 mm)
  curve_number: 75,
});

export const PRESETS = [
  { id: 'quick', label: 'Quick', hint: '20 m DEM, 3 sites', values: { dem_resolution_m: 20, max_candidate_sites: 3 } },
  { id: 'balanced', label: 'Balanced', hint: 'Adaptive DEM, 5 sites', values: {} },
  { id: 'detailed', label: 'Detailed', hint: '10 m DEM, 8 sites', values: { dem_resolution_m: 10, max_candidate_sites: 8 } },
];

/** SCS-CN values for hydrologic soil group B, the common Deccan/Chhattisgarh case. */
export const LAND_COVER_CN = [
  { label: 'Cultivated fields', cn: 75 },
  { label: 'Pasture / grassland', cn: 69 },
  { label: 'Open forest', cn: 60 },
  { label: 'Barren / rocky', cn: 86 },
  { label: 'Village / built-up', cn: 90 },
];

export const RADIUS_LIMITS = { min: 50, max: 1000, step: 10 };

const PARAM_KEYS = Object.keys(DEFAULT_SETTINGS).filter((key) => key !== 'radiusM');

export function presetSettings(presetId, current = DEFAULT_SETTINGS) {
  const preset = PRESETS.find((p) => p.id === presetId);
  const reset = { ...DEFAULT_SETTINGS, radiusM: current.radiusM, design_rainfall_mm: current.design_rainfall_mm, curve_number: current.curve_number };
  return { ...reset, ...(preset?.values || {}) };
}

export function activePreset(settings) {
  return PRESETS.find((preset) => {
    const expected = presetSettings(preset.id, settings);
    return PARAM_KEYS.every((key) => expected[key] === settings[key]);
  })?.id || null;
}

export function settingsToParams(settings) {
  const params = {};
  PARAM_KEYS.forEach((key) => {
    const value = settings[key];
    if (value !== null && value !== undefined && value !== '' && value !== DEFAULT_SETTINGS[key]) {
      params[key] = value;
    }
  });
  return params;
}

export function validateSettings(s) {
  const errors = [];
  if (!(s.max_slope_deg > s.ideal_slope_deg)) errors.push('Maximum slope must be greater than the ideal slope.');
  if (s.weight_slope + s.weight_depression + s.weight_twi <= 0) errors.push('At least one suitability weight must be above zero.');
  if (s.curve_number < 30 || s.curve_number > 98) errors.push('Curve number must be between 30 and 98.');
  if (s.max_candidate_sites < 1 || s.max_candidate_sites > 20) errors.push('Candidate sites must be between 1 and 20.');
  if (s.design_rainfall_mm !== null && !(s.design_rainfall_mm > 0)) errors.push('Design rainfall must be positive.');
  return errors;
}

/** Normalized weight shares, as the backend applies them. */
export function weightShares(s) {
  const total = s.weight_slope + s.weight_depression + s.weight_twi;
  if (total <= 0) return { slope: 0, depression: 0, twi: 0 };
  return {
    slope: s.weight_slope / total,
    depression: s.weight_depression / total,
    twi: s.weight_twi / total,
  };
}

const STORAGE_KEY = 'jalasetu.settings.v1';

export function loadSettings() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    if (stored && typeof stored === 'object') {
      const merged = { ...DEFAULT_SETTINGS };
      Object.keys(DEFAULT_SETTINGS).forEach((key) => {
        if (key in stored && (typeof stored[key] === 'number' || stored[key] === null)) merged[key] = stored[key];
      });
      return merged;
    }
  } catch {
    // fall through to defaults
  }
  return { ...DEFAULT_SETTINGS };
}

export function saveSettings(settings) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Settings persistence is a convenience only.
  }
}
