/**
 * TypeScript Type Definitions for Jalasetu Pond Catchment Analysis API.
 * Matches backend Pydantic models from app/models/schemas.py.
 */

export interface GeoJSONGeometry {
  type: string;
  coordinates: any[];
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: GeoJSONGeometry;
  properties?: Record<string, any>;
}

export interface GeoJSONFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

export interface InputSummary {
  num_contours: number;
  elevation_min: number;
  elevation_max: number;
  dem_resolution_m: number;
  utm_crs?: string | null;
}

export interface PondSiteSummary {
  site_id: string;
  rank: number;
  latitude: number;
  longitude: number;
  elevation_m: number;
  suitability_score: number;
  area_m2: number;
  slope_deg?: number | null;
  storage_capacity_m3?: number | null;
  cut_volume_m3?: number | null;
  storage_efficiency_ratio?: number | null;
  mean_twi?: number | null;
  composite_mcdm_score?: number | null;
  stage_storage_curve?: Array<{ depth_m: number; surface_area_m2: number; volume_m3: number }> | null;
  boundary_geojson?: GeoJSONFeatureCollection | null;
}

export interface ElevationRange {
  min_m: number;
  max_m: number;
  relief_m: number;
}

export interface CatchmentSummary {
  boundary_geojson?: GeoJSONFeatureCollection | null;
  area_m2: number;
  area_hectares: number;
  average_slope_deg: number;
  elevation_range_m: ElevationRange;
  delineation_method: string;
  catchment_to_pond_ratio?: number | null;
  hydrological_feasibility?: string | null;
  feasibility_explanation?: string | null;
  estimated_runoff_volume_m3?: number | null;
  design_rainfall_mm?: number | null;
  curve_number?: number | null;
  mean_ls_factor?: number | null;
  siltation_risk?: string | null;
  siltation_explanation?: string | null;
  water_filling_factor?: number | null;
}

export type CatchmentStatus = 'success' | 'no_suitable_site' | 'partial_success' | 'error';

export interface CatchmentResponse {
  status: CatchmentStatus;
  message?: string | null;
  input_summary?: InputSummary | null;
  recommended_site?: PondSiteSummary | null;
  alternative_sites: PondSiteSummary[];
  catchment?: CatchmentSummary | null;
  processing_notes: string[];
  terrain_source?: 'uploaded_contours' | 'bundled_contours' | 'global_dem' | null;
  infrastructure?: {
    status: 'ok' | 'unavailable' | 'disabled';
    source?: string | null;
    message?: string | null;
    survey_radius_m?: number | null;
    categories: string[];
    buffer_scale: number;
    counts: Record<string, number>;
    excluded_area_m2: number;
    zones_geojson?: GeoJSONFeatureCollection | null;
    features_geojson?: GeoJSONFeatureCollection | null;
  } | null;
  /** Distributed deployments only: where and how long each stage ran. */
  execution?: AnalysisExecution | null;
}

export interface StageRecord {
  stage: 'prepare' | 'analyze' | 'catchment' | 'climate';
  node: string;
  mode: 'remote' | 'local' | 'local-degraded';
  duration_ms: number;
  attempts: Array<{ node: string; outcome: string }>;
}

export interface AnalysisExecution {
  gateway: string;
  job_id?: string;
  total_ms: number;
  stages: StageRecord[];
}

export interface AnalysisProgress {
  job_id: string;
  state: 'queued' | 'running' | 'succeeded' | 'failed';
  stage: string | null;
  node: string | null;
  waiting_for_capacity: boolean;
  queue_position: number;
  stages: StageRecord[];
  poll_url?: string;
  error?: string;
  result?: CatchmentResponse;
}

export interface ClusterNode {
  name: string;
  role: 'edge' | 'stage-worker' | 'gateway' | string;
  local: boolean;
  reachable: boolean | null;
  stages: string[];
  affinity: string[];
  capacity: {
    accepting?: boolean;
    in_flight?: number;
    slots?: number;
    stage_reserve_mb?: number;
    memory?: { used_mb: number; budget_mb: number; headroom_mb: number; source: string };
  };
  storage: { used_mb: number | null; budget_mb: number; within_budget: boolean | null };
  latency_ms: number | null;
  pending: number;
  stages_run: number;
}

export interface ClusterStatus {
  cluster_status: 'ok' | 'degraded';
  nodes: ClusterNode[];
  jobs: { running: number; queued: number; max_active: number; max_queued: number };
  budgets: { memory_mb: number; storage_mb: number };
}

export interface ContourAnalysisParams {
  dem_resolution_m?: number;
  sample_spacing_m?: number;
  ideal_slope_deg?: number;
  max_slope_deg?: number;
  neighborhood_radius_m?: number;
  weight_slope?: number;
  weight_depression?: number;
  weight_twi?: number;
  suitability_threshold?: number;
  min_pond_area_m2?: number;
  max_pond_area_m2?: number;
  max_candidate_sites?: number;
  max_elongation_ratio?: number;
  min_pond_width_m?: number;
  pond_design_depth_m?: number;
  snap_radius_m?: number;
  use_pysheds?: boolean;
  design_rainfall_mm?: number;
  curve_number?: number;
  slope_threshold?: number;
  min_pond_area?: number;
  [key: string]: any;
}

export interface HealthResponse {
  status: string;
  message: string;
}

export class CatchmentApiError extends Error {
  status: number;
  message: string;
  raw?: any;
  constructor(status: number, message: string, raw?: any);
  toJSON(): { status: number; message: string };
}

export function analyzeContourFile(
  file: File | Blob,
  params?: ContourAnalysisParams,
  options?: Record<string, any>
): Promise<CatchmentResponse>;

export function analyzeContourMap(
  file: File | Blob,
  params?: ContourAnalysisParams,
  options?: Record<string, any>
): Promise<CatchmentResponse>;

export function buildAnalysisForm(file: File | Blob | null, params?: ContourAnalysisParams): FormData;

export function runAnalysis(
  file: File | Blob | null,
  params?: ContourAnalysisParams,
  options?: { onProgress?: (progress: AnalysisProgress) => void; signal?: AbortSignal }
): Promise<CatchmentResponse>;

/** Resolves to null on the single-node FastAPI backend. */
export function getClusterStatus(options?: { signal?: AbortSignal }): Promise<ClusterStatus | null>;

export interface InfrastructureLookup {
  status: 'ok' | 'unavailable';
  source?: string;
  message?: string;
  radius_m: number;
  counts: Record<string, number>;
  features: GeoJSONFeatureCollection;
  cached?: boolean;
}

export function getInfrastructure(
  latitude: number,
  longitude: number,
  radiusM: number,
  options?: { signal?: AbortSignal }
): Promise<InfrastructureLookup>;

export interface PlaceResult { name: string; detail: string; latitude: number; longitude: number }
export function searchPlaces(query: string, options?: { signal?: AbortSignal }): Promise<PlaceResult[]>;

export function getHealthStatus(): Promise<HealthResponse>;

export function getCatchmentSchema(): Promise<any>;

export function normalizeCatchmentError(error: any): CatchmentApiError;

export const API_BASE_URL: string;

declare const catchmentApi: {
  analyzeContourFile: typeof analyzeContourFile;
  analyzeContourMap: typeof analyzeContourMap;
  runAnalysis: typeof runAnalysis;
  buildAnalysisForm: typeof buildAnalysisForm;
  getClusterStatus: typeof getClusterStatus;
  getInfrastructure: typeof getInfrastructure;
  searchPlaces: typeof searchPlaces;
  getHealthStatus: typeof getHealthStatus;
  getCatchmentSchema: typeof getCatchmentSchema;
  normalizeCatchmentError: typeof normalizeCatchmentError;
  CatchmentApiError: typeof CatchmentApiError;
  API_BASE_URL: string;
};

export default catchmentApi;
