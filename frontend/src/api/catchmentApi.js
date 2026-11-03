/**
 * API client module for Jalasetu Pond Catchment Analysis.
 *
 * Provides functions to interact with the backend FastAPI services:
 *  - analyzeContourFile: Uploads contour maps (.kml/.kmz) and retrieves terrain/catchment analysis.
 *  - getHealthStatus: Operational health check of the backend.
 *  - getCatchmentSchema: Retrieves the OpenAPI schema metadata and sample payloads.
 *
 * @module api/catchmentApi
 */

import axios from 'axios';

// ============================================================================
// TypeScript / JSDoc Type Definitions (Matching backend app/models/schemas.py)
// ============================================================================

/**
 * Standard GeoJSON Geometry definition.
 * @typedef {Object} GeoJSONGeometry
 * @property {string} type - Geometry type (e.g. 'Polygon', 'MultiPolygon', 'Point', 'LineString')
 * @property {Array<any>} coordinates - GeoJSON coordinate array in EPSG:4326 [Longitude, Latitude]
 */

/**
 * Standard GeoJSON Feature definition.
 * @typedef {Object} GeoJSONFeature
 * @property {'Feature'} type - GeoJSON type ('Feature')
 * @property {GeoJSONGeometry} geometry - Feature geometry object
 * @property {Record<string, any>} [properties] - Feature attributes and metadata
 */

/**
 * Standard GeoJSON FeatureCollection definition.
 * @typedef {Object} GeoJSONFeatureCollection
 * @property {'FeatureCollection'} type - GeoJSON type ('FeatureCollection')
 * @property {GeoJSONFeature[]} features - Array of GeoJSON Features
 */

/**
 * Summary metadata of parsed contour lines and interpolated DEM.
 * @typedef {Object} InputSummary
 * @property {number} num_contours - Total number of contour features extracted from KML/KMZ
 * @property {number} elevation_min - Minimum elevation found in contour lines (meters)
 * @property {number} elevation_max - Maximum elevation found in contour lines (meters)
 * @property {number} dem_resolution_m - Interpolated DEM raster cell resolution (meters/pixel)
 * @property {string|null} [utm_crs] - Auto-detected local UTM Projected CRS (e.g. 'EPSG:32643')
 */

/**
 * Attributes and coordinates for an identified candidate farm pond excavation site.
 * @typedef {Object} PondSiteSummary
 * @property {string} site_id - Unique identifier for the candidate site (e.g. 'site_1')
 * @property {number} rank - Suitability rank (1 = highest recommended site)
 * @property {number} latitude - Centroid Latitude in WGS84 decimal degrees
 * @property {number} longitude - Centroid Longitude in WGS84 decimal degrees
 * @property {number} elevation_m - Average ground elevation at pond site (meters)
 * @property {number} suitability_score - Composite terrain suitability score (0 - 100)
 * @property {number} area_m2 - Contiguous excavation footprint area (square meters)
 * @property {number|null} [slope_deg] - Average ground slope at site (degrees)
 */

/**
 * Elevation relief metrics across the delineated catchment basin.
 * @typedef {Object} ElevationRange
 * @property {number} min_m - Lowest elevation point in catchment (meters)
 * @property {number} max_m - Highest ridge elevation in catchment (meters)
 * @property {number} relief_m - Total basin elevation relief span (max - min) (meters)
 */

/**
 * Delineated upstream catchment / watershed metrics and boundary geometry.
 * @typedef {Object} CatchmentSummary
 * @property {GeoJSONFeatureCollection|null} [boundary_geojson] - Catchment boundary polygon in standard WGS84 GeoJSON FeatureCollection format
 * @property {number} area_m2 - Catchment contributing drainage area (square meters)
 * @property {number} area_hectares - Catchment contributing drainage area (hectares)
 * @property {number} average_slope_deg - Mean ground slope across the catchment (degrees)
 * @property {ElevationRange} elevation_range_m - Elevation range within the catchment
 * @property {string} delineation_method - Hydrological routing engine used ('flow_accumulation' or 'basin_approximation')
 */

/**
 * Master response payload for contour terrain analysis and pond catchment delineation.
 * @typedef {Object} CatchmentResponse
 * @property {'success'|'no_suitable_site'|'partial_success'|'error'} status - Execution status
 * @property {string|null} [message] - Summary explanation of analysis results
 * @property {InputSummary|null} [input_summary] - Summary of parsed contour inputs and DEM metadata
 * @property {PondSiteSummary|null} [recommended_site] - Top-ranked recommended pond site (#1)
 * @property {PondSiteSummary[]} alternative_sites - Ranked alternative candidate pond sites
 * @property {CatchmentSummary|null} [catchment] - Delineated upstream catchment contributing to recommended pond site
 * @property {string[]} processing_notes - Execution logs, parameter choices, skipped features, and warnings
 */

/**
 * Optional tuning parameters for the terrain and catchment pipeline.
 * @typedef {Object} ContourAnalysisParams
 * @property {number} [dem_resolution_m] - DEM raster grid resolution in meters (e.g. 5.0m). Auto-derived if omitted.
 * @property {number} [sample_spacing_m] - Contour sampling interval in meters. Defaults to resolution / 2.
 * @property {number} [ideal_slope_deg] - Ideal maximum ground slope in degrees for pond excavation (defaults to 3.0°).
 * @property {number} [max_slope_deg] - Upper allowable ground slope limit in degrees (defaults to 8.0°).
 * @property {number} [neighborhood_radius_m] - Neighborhood filter radius in meters for local depression detection.
 * @property {number} [weight_slope] - Relative weight for slope criterion in composite suitability score (0-1).
 * @property {number} [weight_depression] - Relative weight for local depression criterion in composite suitability score (0-1).
 * @property {number} [suitability_threshold] - Minimum suitability score threshold (0-100) for candidate pond sites.
 * @property {number} [min_pond_area_m2] - Minimum contiguous footprint in square meters for a viable pond.
 * @property {number} [max_pond_area_m2] - Optional maximum allowable pond footprint in square meters.
 * @property {number} [max_candidate_sites] - Maximum number of ranked candidate pond sites to return.
 * @property {number} [selected_latitude] - Centre latitude selected on the map.
 * @property {number} [selected_longitude] - Centre longitude selected on the map.
 * @property {number} [selected_radius_m] - Radius of the selected analysis area.
 * @property {number} [snap_radius_m] - Search radius in meters to snap pour point to stream channel.
 * @property {boolean} [use_pysheds] - Attempt pysheds hydrological flow accumulation first (falls back to native D8).
 * @property {number} [slope_threshold] - Alias for suitability_threshold.
 * @property {number} [min_pond_area] - Alias for min_pond_area_m2.
 */

/**
 * Normalized API error object thrown on failure.
 * @typedef {Object} ApiErrorObject
 * @property {number} status - HTTP status code (e.g. 400, 422, 500) or 0 for network/unreachable errors.
 * @property {string} message - Normalized user-facing error message.
 * @property {any} [raw] - Original response data or underlying error object.
 */

// ============================================================================
// Custom Error Class
// ============================================================================

/**
 * Normalized API Error for Catchment API operations.
 */
export class CatchmentApiError extends Error {
  /**
   * @param {number} status - HTTP status code (or 0 for network/connection failure)
   * @param {string} message - Human-readable error message
   * @param {any} [raw] - Optional raw response or underlying error
   */
  constructor(status, message, raw = null) {
    super(message);
    this.name = 'CatchmentApiError';
    this.status = status;
    this.message = message;
    this.raw = raw;

    // Ensure status and message are directly accessible and enumerable
    Object.defineProperty(this, 'status', { value: status, enumerable: true, writable: true });
    Object.defineProperty(this, 'message', { value: message, enumerable: true, writable: true });
  }

  toJSON() {
    return {
      status: this.status,
      message: this.message,
    };
  }
}

// ============================================================================
// Configuration & Client Setup
// ============================================================================

/**
 * Base URL configured via Vite environment variable VITE_API_BASE_URL.
 * Falls back to localhost:8000 in development.
 */
export const API_BASE_URL = (
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL !== undefined)
    ? import.meta.env.VITE_API_BASE_URL
    : 'http://127.0.0.1:8000'
).replace(/\/+$/, '');

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180000, // 3 minutes timeout for compute-heavy spatial operations
});

/**
 * Map of friendly parameter alias names to their backend schema parameter names.
 */
const PARAM_ALIASES = {
  min_pond_area: 'min_pond_area_m2',
  max_pond_area: 'max_pond_area_m2',
  slope_threshold: 'suitability_threshold',
  resolution: 'dem_resolution_m',
  dem_resolution: 'dem_resolution_m',
};

// ============================================================================
// Error Normalization Helper
// ============================================================================

/**
 * Normalizes any caught error into a consistent { status: number, message: string } CatchmentApiError.
 * Distinguishes network / server-unreachable errors (status 0) from HTTP response errors (400/500).
 *
 * @param {any} error - The caught AxiosError or generic Error.
 * @returns {CatchmentApiError}
 */
export function normalizeCatchmentError(error) {
  if (error instanceof CatchmentApiError) {
    return error;
  }

  // 1. HTTP Error Response from Backend (4xx, 5xx)
  if (error && error.response) {
    const status = typeof error.response.status === 'number' ? error.response.status : 500;
    const data = error.response.data;
    let extractedMessage = '';

    if (data) {
      if (typeof data === 'string' && data.trim().length > 0) {
        extractedMessage = data.trim();
      } else if (typeof data.detail === 'string' && data.detail.trim().length > 0) {
        extractedMessage = data.detail.trim();
      } else if (Array.isArray(data.detail) && data.detail.length > 0) {
        // FastAPI / Pydantic validation error array: [{ loc: [...], msg: "...", type: "..." }]
        extractedMessage = data.detail
          .map((item) => {
            if (typeof item === 'string') return item;
            if (item && item.msg) {
              const field = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : '';
              return field ? `${field}: ${item.msg}` : item.msg;
            }
            return JSON.stringify(item);
          })
          .join('; ');
      } else if (typeof data.message === 'string' && data.message.trim().length > 0) {
        extractedMessage = data.message.trim();
      } else if (typeof data.error === 'string' && data.error.trim().length > 0) {
        extractedMessage = data.error.trim();
      }
    }

    if (!extractedMessage) {
      extractedMessage = 'Something went wrong analyzing the file';
    }

    return new CatchmentApiError(status, extractedMessage, data);
  }

  // 2. Network Errors & Server Unreachable (Status 0)
  if (
    error &&
    (error.request ||
      error.code === 'ERR_NETWORK' ||
      error.code === 'ECONNABORTED' ||
      error.message?.includes('Network Error') ||
      error.message?.includes('Failed to fetch'))
  ) {
    const isTimeout =
      error.code === 'ECONNABORTED' ||
      (typeof error.message === 'string' && error.message.toLowerCase().includes('timeout'));

    const message = isTimeout
      ? 'Terrain analysis request timed out. The server took too long to respond.'
      : 'Server is unreachable. Please verify your network connection and ensure the backend server is running.';

    return new CatchmentApiError(0, message, error);
  }

  // 3. Fallback generic error
  const fallbackStatus = typeof error?.status === 'number' ? error.status : 0;
  const fallbackMessage =
    (typeof error?.message === 'string' && error.message.trim().length > 0
      ? error.message
      : null) || 'Something went wrong analyzing the file';

  return new CatchmentApiError(fallbackStatus, fallbackMessage, error);
}

// ============================================================================
// API Service Methods
// ============================================================================

/**
 * Uploads a contour map (.kml / .kmz) and executes terrain analysis and catchment delineation.
 *
 * @param {File|Blob} file - The KML or KMZ contour map file.
 * @param {ContourAnalysisParams} [params={}] - Optional parameter overrides. Only explicitly provided keys are appended.
 * @param {Object} [options={}] - Optional Axios request options (e.g. onUploadProgress, signal).
 * @returns {Promise<CatchmentResponse>} Parsed CatchmentResponse payload.
 * @throws {CatchmentApiError} Normalized error object: { status: number, message: string }.
 */
export async function analyzeContourFile(file, params = {}, options = {}) {
  const formData = buildAnalysisForm(file, params);

  try {
    const response = await apiClient.post('/analyzeContour', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      ...options,
    });

    return response.data;
  } catch (error) {
    throw normalizeCatchmentError(error);
  }
}

/**
 * Builds the multipart body shared by the synchronous and job-based endpoints.
 * Only explicitly provided keys are appended so backend defaults still apply.
 *
 * @param {File|Blob|null} file
 * @param {ContourAnalysisParams} params
 * @returns {FormData}
 * @throws {CatchmentApiError} When there is neither a file nor a selected area.
 */
export function buildAnalysisForm(file, params = {}) {
  const hasSelectedArea =
    params &&
    Number.isFinite(Number(params.selected_latitude)) &&
    Number.isFinite(Number(params.selected_longitude)) &&
    Number.isFinite(Number(params.selected_radius_m));

  if (!file && !hasSelectedArea) {
    throw new CatchmentApiError(400, 'Please select a valid .kml or .kmz contour file to analyze.');
  }

  const formData = new FormData();
  if (file) {
    formData.append('file', file);
  }

  if (params && typeof params === 'object') {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        const mappedKey = PARAM_ALIASES[key] || key;

        // If an alias key was used and the official key was already provided, skip duplicate
        if (mappedKey !== key && params[mappedKey] !== undefined && params[mappedKey] !== null && params[mappedKey] !== '') {
          return;
        }

        formData.append(mappedKey, value);
      }
    });
  }
  return formData;
}

/**
 * Progress snapshot reported while a distributed analysis job runs.
 * @typedef {Object} AnalysisProgress
 * @property {'queued'|'running'|'succeeded'|'failed'} state
 * @property {string|null} stage - Current stage: prepare | analyze | catchment | climate
 * @property {string|null} node - Cluster node running the current stage
 * @property {boolean} waiting_for_capacity - Every node is busy; the stage is waiting
 * @property {number} queue_position - 1-based position while queued
 * @property {Array<{stage: string, node: string, mode: string, duration_ms: number}>} stages
 */

const JOB_POLL_INTERVAL_MS = 700;
const JOB_TIMEOUT_MS = 6 * 60 * 1000;
let jobsEndpointAvailable = null; // null = not probed yet

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new CatchmentApiError(0, 'Analysis was cancelled.'));
    }, { once: true });
  });

/**
 * Runs an analysis through the distributed job queue, reporting stage progress.
 * Falls back to the synchronous /analyzeContour endpoint when the backend is
 * the single-node FastAPI app (no /v1/jobs route).
 *
 * @param {File|Blob|null} file
 * @param {ContourAnalysisParams} [params={}]
 * @param {{ onProgress?: (p: AnalysisProgress) => void, signal?: AbortSignal }} [options={}]
 * @returns {Promise<CatchmentResponse>}
 * @throws {CatchmentApiError}
 */
export async function runAnalysis(file, params = {}, { onProgress, signal } = {}) {
  if (jobsEndpointAvailable === false) {
    return analyzeContourFile(file, params, { signal });
  }

  const formData = buildAnalysisForm(file, params);
  let job;
  try {
    const response = await apiClient.post('/v1/jobs', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal,
    });
    job = response.data;
    jobsEndpointAvailable = true;
  } catch (error) {
    const status = error?.response?.status;
    if (status === 404 || status === 405) {
      jobsEndpointAvailable = false;
      return analyzeContourFile(file, params, { signal });
    }
    throw normalizeCatchmentError(error);
  }

  onProgress?.(job);
  const deadline = Date.now() + JOB_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await sleep(JOB_POLL_INTERVAL_MS, signal);
    let current;
    try {
      current = (await apiClient.get(job.poll_url || `/v1/jobs/${job.job_id}`, { signal, timeout: 15000 })).data;
    } catch (error) {
      // A dropped poll is not a failed job; retry until the deadline.
      if (error?.response?.status === 404) {
        throw new CatchmentApiError(404, 'The analysis job expired on the server. Please run it again.');
      }
      if (signal?.aborted) throw new CatchmentApiError(0, 'Analysis was cancelled.');
      continue;
    }
    onProgress?.(current);
    if (current.state === 'succeeded') return current.result;
    if (current.state === 'failed') {
      throw new CatchmentApiError(422, current.error || 'The analysis failed on the server.', current);
    }
  }
  throw new CatchmentApiError(0, 'Terrain analysis request timed out. The server took too long to respond.');
}

/**
 * Live per-node capacity of the distributed deployment.
 * Resolves to null when the backend is the single-node FastAPI app.
 *
 * @param {{ signal?: AbortSignal }} [options={}]
 * @returns {Promise<Object|null>}
 */
export async function getClusterStatus({ signal } = {}) {
  try {
    const response = await apiClient.get('/v1/cluster', { signal, timeout: 8000 });
    return response.data && Array.isArray(response.data.nodes) ? response.data : null;
  } catch (error) {
    if (error?.response?.status === 404) return null;
    throw normalizeCatchmentError(error);
  }
}

/**
 * Operational health check endpoint.
 *
 * @returns {Promise<{ status: string, message: string }>}
 * @throws {CatchmentApiError}
 */
export async function getHealthStatus() {
  try {
    const response = await apiClient.get('/health');
    return response.data;
  } catch (error) {
    throw normalizeCatchmentError(error);
  }
}

/**
 * Fetches OpenAPI CatchmentResponse schema documentation and example payload.
 *
 * @returns {Promise<Object>}
 * @throws {CatchmentApiError}
 */
export async function getCatchmentSchema() {
  try {
    const response = await apiClient.get('/analyzeContour/schema');
    return response.data;
  } catch (error) {
    throw normalizeCatchmentError(error);
  }
}

/**
 * Fetches location precipitation metrics and seasonal monsoon distribution.
 *
 * @param {number} latitude
 * @param {number} longitude
 * @returns {Promise<Object>}
 * @throws {CatchmentApiError}
 */
export async function getRainfallData(latitude, longitude) {
  try {
    const response = await apiClient.get('/v1/rainfall', {
      params: { lat: latitude, lon: longitude },
    });
    return response.data;
  } catch (error) {
    throw normalizeCatchmentError(error);
  }
}

/**
 * Mapped infrastructure a pond must avoid (rivers, tanks, buildings, schools,
 * roads, wells) around a point, from OpenStreetMap via the backend.
 * Resolves with status 'unavailable' when the lookup fails upstream.
 *
 * @param {number} latitude
 * @param {number} longitude
 * @param {number} radiusM
 * @param {{ signal?: AbortSignal }} [options={}]
 * @returns {Promise<{status: string, message?: string, counts: Object, features: Object}>}
 */
export async function getInfrastructure(latitude, longitude, radiusM, { signal } = {}) {
  try {
    const response = await apiClient.get('/v1/infrastructure', {
      params: { lat: latitude, lon: longitude, radius_m: Math.round(radiusM) },
      signal,
      timeout: 60000,
    });
    return response.data;
  } catch (error) {
    throw normalizeCatchmentError(error);
  }
}

const NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search';

/**
 * Place search (villages, towns, landmarks) via OpenStreetMap Nominatim.
 * Callers debounce input; Nominatim allows about one request per second.
 *
 * @param {string} query
 * @param {{ signal?: AbortSignal }} [options={}]
 * @returns {Promise<Array<{ name: string, detail: string, latitude: number, longitude: number }>>}
 */
export async function searchPlaces(query, { signal } = {}) {
  const coords = query.trim().match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
  if (coords) {
    const latitude = Number(coords[1]);
    const longitude = Number(coords[2]);
    if (Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180) {
      return [{ name: `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`, detail: 'Coordinates', latitude, longitude }];
    }
  }
  try {
    const response = await axios.get(NOMINATIM_URL, {
      params: { q: query, format: 'jsonv2', limit: 6, 'accept-language': 'en' },
      signal,
      timeout: 10000,
    });
    return (response.data || []).map((item) => ({
      name: item.name || item.display_name.split(',')[0],
      detail: item.display_name,
      latitude: Number(item.lat),
      longitude: Number(item.lon),
    }));
  } catch (error) {
    throw normalizeCatchmentError(error);
  }
}

/**
 * Backward-compatibility alias for analyzeContourFile.
 */
export const analyzeContourMap = analyzeContourFile;

export default {
  analyzeContourFile,
  analyzeContourMap,
  runAnalysis,
  buildAnalysisForm,
  getClusterStatus,
  getInfrastructure,
  searchPlaces,
  getHealthStatus,
  getCatchmentSchema,
  getRainfallData,
  normalizeCatchmentError,
  CatchmentApiError,
  API_BASE_URL,
  apiClient,
};
