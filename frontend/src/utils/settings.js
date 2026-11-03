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
  design_rainfall_mm: null, // null = the location's recommended design storm
  curve_number: 75,
  max_pond_footprint_m2: 20000, // oversized flat regions are carved to this (2 ha)
  terrain_source: 'auto', // 'auto' | 'contours' | 'global_dem'
  avoid_infrastructure: true,
  exclusion_categories: null, // null = every category
  exclusion_buffer_scale: 1,
});

/** Mirrors CATEGORIES in app/services/infrastructure.py (buffers in metres). */
export const INFRASTRUCTURE_CATEGORIES = [
  { id: 'water', label: 'Lakes, tanks & ponds', buffer: 15 },
  { id: 'waterway', label: 'Rivers, streams & canals', buffer: 20 },
  { id: 'building', label: 'Buildings', buffer: 10 },
  { id: 'facility', label: 'Schools, hospitals & temples', buffer: 30 },
  { id: 'road', label: 'Roads', buffer: 8 },
  { id: 'railway', label: 'Railways', buffer: 15 },
  { id: 'settlement', label: 'Residential areas', buffer: 0 },
  { id: 'well', label: 'Wells & water points', buffer: 15 },
];
const ALL_CATEGORY_IDS = INFRASTRUCTURE_CATEGORIES.map((c) => c.id);

export function enabledCategories(settings) {
  return settings.exclusion_categories || ALL_CATEGORY_IDS;
}

export const TERRAIN_SOURCES = [
  { id: 'auto', label: 'Auto', hint: 'Contours where available, global DEM elsewhere' },
  { id: 'contours', label: 'Contours', hint: 'Uploaded or bundled contour map only' },
  { id: 'global_dem', label: 'Global DEM', hint: 'SRTM-derived ~30 m terrain anywhere' },
];

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

// Parameters a preset controls; hydrology, terrain source and infrastructure
// choices are left as the user set them.
const PRESET_KEYS = [
  'dem_resolution_m', 'ideal_slope_deg', 'max_slope_deg', 'weight_slope', 'weight_depression',
  'weight_twi', 'suitability_threshold', 'min_pond_area_m2', 'max_candidate_sites',
];
const PARAM_KEYS = Object.keys(DEFAULT_SETTINGS).filter((key) => key !== 'radiusM');

export function presetSettings(presetId, current = DEFAULT_SETTINGS) {
  const preset = PRESETS.find((p) => p.id === presetId);
  const reset = { ...current };
  PRESET_KEYS.forEach((key) => { reset[key] = DEFAULT_SETTINGS[key]; });
  return { ...reset, ...(preset?.values || {}) };
}

export function activePreset(settings) {
  return PRESETS.find((preset) => {
    const expected = presetSettings(preset.id, settings);
    return PRESET_KEYS.every((key) => expected[key] === settings[key]);
  })?.id || null;
}

export function settingsToParams(settings) {
  const params = {};
  PARAM_KEYS.forEach((key) => {
    const value = settings[key];
    if (value === null || value === undefined || value === '' || value === DEFAULT_SETTINGS[key]) return;
    if (key === 'exclusion_categories') {
      if (value.length !== ALL_CATEGORY_IDS.length) params[key] = value.join(',') || 'none';
      return;
    }
    params[key] = typeof value === 'boolean' ? String(value) : value;
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
  if (!(s.max_pond_footprint_m2 >= 100)) errors.push('Maximum pond footprint must be at least 100 m².');
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
        if (!(key in stored)) return;
        const fallback = DEFAULT_SETTINGS[key];
        const value = stored[key];
        const sameType = fallback === null
          ? value === null || typeof value === 'number' || Array.isArray(value)
          : value === null || typeof value === typeof fallback;
        if (sameType) merged[key] = value;
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

// Extent of the bundled demonstration contours (contours_1m.kml); mirrors
// BUNDLED_CONTOUR_BOUNDS in app/services/terrain_source.py.
const BUNDLED_BOUNDS = { minLon: 81.2814, minLat: 21.23982, maxLon: 81.31265, maxLat: 21.26358 };

export function inBundledContours(point) {
  return Boolean(point) &&
    point.longitude >= BUNDLED_BOUNDS.minLon && point.longitude <= BUNDLED_BOUNDS.maxLon &&
    point.latitude >= BUNDLED_BOUNDS.minLat && point.latitude <= BUNDLED_BOUNDS.maxLat;
}

/** Which terrain source the backend will use for this request (display only). */
export function terrainPlanFor(settings, uploadedFile, point) {
  if (settings.terrain_source === 'global_dem' && point) {
    return { id: 'global', label: 'Global DEM (SRTM-derived ~30 m)', hint: 'Forced by the terrain source setting.' };
  }
  if (uploadedFile) {
    return { id: 'upload', label: `Uploaded contours · ${uploadedFile.name}`, hint: 'Highest accuracy: your surveyed contour map.' };
  }
  if (!point) return null;
  if (settings.terrain_source === 'contours' || inBundledContours(point)) {
    return inBundledContours(point)
      ? { id: 'demo', label: 'Demo contour map (1 m)', hint: 'This point is inside the bundled contour survey.' }
      : { id: 'none', label: 'No contour map here', hint: 'Upload contours, or switch the source to Auto or Global DEM.' };
  }
  return { id: 'global', label: 'Global DEM (SRTM-derived ~30 m)', hint: 'No contour map covers this point; elevation tiles are used instead.' };
}
