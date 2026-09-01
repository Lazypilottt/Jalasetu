# Jalasetu REST API Documentation

The **Jalasetu API** provides automated geospatial services for analyzing topographic contour maps (.kml / .kmz), building continuous Digital Elevation Models (DEMs), ranking optimal candidate farm pond excavation sites, and delineating upstream rainwater catchment drainage basins.

---

## 1. Overview & Base URL

- **Development Server**: `http://127.0.0.1:8000`
- **Interactive Swagger UI**: `http://127.0.0.1:8000/docs`
- **ReDoc UI**: `http://127.0.0.1:8000/redoc`
- **OpenAPI JSON Spec**: `http://127.0.0.1:8000/openapi.json`
- **Response Format**: `application/json` (UTF-8)
- **Coordinate Reference Systems**:
  - All input/output geographic coordinates (latitude, longitude, GeoJSON) use **WGS84 (EPSG:4326)**.
  - Intermediate raster computations use auto-calculated local **UTM Projected CRS** (e.g. `EPSG:32643`, `EPSG:32644`).

---

## 2. Endpoints Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/analyzeContour` | Upload contour file (.kml / .kmz), analyze terrain, select candidate pond sites with boundary polygons, and delineate catchment. |
| `GET` | `/analyzeContour/schema` | Retrieve the OpenAPI JSON Schema for the `CatchmentResponse` model and an example payload. |
| `GET` | `/health` | Health and readiness check endpoint. |

---

## 3. Endpoints Detail

### 3.1 POST `/analyzeContour`

Accepts a topographic contour map file (`multipart/form-data`) along with optional tuning parameters. Executes DEM interpolation, terrain analysis, candidate pond site ranking (including full boundary polygon vectorization), and upstream catchment delineation.

#### Request Headers
- `Content-Type: multipart/form-data`

#### Form Parameters

| Parameter | Type | Required | Default | Bounds | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `file` | `File` | **Yes** | — | — | Topographic contour map file in **`.kml`** or **`.kmz`** format containing elevation contour lines. |
| `dem_resolution_m` | `float` | No | *Auto* | `0.5` – `100.0` | Spatial resolution of the interpolated DEM raster in meters/pixel. Derived adaptively from contour density if omitted. |
| `sample_spacing_m` | `float` | No | *Auto* | `0.5` – `100.0` | Sampling interval in meters along contour polylines for vertex extraction. Defaults to `dem_resolution_m / 2`. |
| `ideal_slope_deg` | `float` | No | `3.0` | `0.0` – `45.0` | Ideal maximum terrain slope in degrees. Slopes below this receive 100% suitability score for excavation ease. |
| `max_slope_deg` | `float` | No | `8.0` | `1.0` – `60.0` | Maximum permissible slope in degrees. Slopes above this threshold receive 0% suitability score. |
| `neighborhood_radius_m` | `float` | No | *Auto* | `5.0` – `500.0` | Neighborhood window radius in meters for computing Topographic Position Index (TPI) and local terrain depression index. |
| `weight_slope` | `float` | No | `0.5` | `0.0` – `1.0` | Weight for the slope factor in composite suitability scoring. |
| `weight_depression` | `float` | No | `0.5` | `0.0` – `1.0` | Weight for the depression/low-point factor in composite suitability scoring. |
| `suitability_threshold` | `float` | No | `60.0` | `0.0` – `100.0` | Minimum composite suitability score (0–100) required for a cell to qualify as viable pond excavation terrain. |
| `min_pond_area_m2` | `float` | No | `200.0` | `10.0` – `1,000,000.0` | Minimum contiguous footprint area in square meters required for a viable pond site candidate. |
| `max_pond_area_m2` | `float` | No | *None* | `50.0` – `10,000,000.0` | Optional maximum allowable pond footprint in square meters. |
| `max_candidate_sites` | `int` | No | `5` | `1` – `20` | Maximum number of ranked candidate pond sites returned in the response. |
| `max_elongation_ratio` | `float` | No | `3.5` | `1.0` – `50.0` | Maximum allowable major-to-minor axis elongation ratio to filter out linear channels, roads, and corridors. |
| `min_pond_width_m` | `float` | No | *Auto* | `1.0` – `500.0` | Minimum usable footprint width in meters (inscribed circle diameter). |
| `snap_radius_m` | `float` | No | `25.0` | `0.0` – `200.0` | Search radius in meters to snap the site pour point to the highest local flow accumulation stream cell. |
| `use_pysheds` | `bool` | No | `true` | — | Whether to attempt Pysheds D8 flow routing first before native topological BFS fallback. |

---

#### Response Payload (`CatchmentResponse`)

```typescript
interface CatchmentResponse {
  status: "success" | "no_suitable_site" | "partial_success" | "error";
  message?: string;
  input_summary?: InputSummary;
  recommended_site?: PondSiteSummary;
  alternative_sites: PondSiteSummary[];
  catchment?: CatchmentSummary;
  processing_notes: string[];
}
```

##### Response Fields Breakdown

- **`status`** (`string`): Overall outcome of the pipeline:
  - `"success"`: Both pond siting and catchment delineation succeeded.
  - `"no_suitable_site"`: Terrain analyzed successfully, but no regions met the minimum suitability/area criteria.
  - `"partial_success"`: Pond sites were identified, but catchment delineation could not be completed.
  - `"error"`: An error occurred during file parsing or DEM generation.
- **`message`** (`string`, optional): Human-readable summary of the execution outcome.
- **`input_summary`** (`object`, optional):
  - `num_contours` (`int`): Total count of contour polyline features parsed.
  - `elevation_min` (`float`): Minimum elevation value found (meters).
  - `elevation_max` (`float`): Maximum elevation value found (meters).
  - `dem_resolution_m` (`float`): Raster cell resolution used for the DEM (meters).
  - `utm_crs` (`string`, optional): Local UTM projected coordinate system (e.g. `"EPSG:32643"`).
- **`recommended_site`** (`PondSiteSummary`, optional): The top-ranked (#1) recommended pond excavation site.
- **`alternative_sites`** (`PondSiteSummary[]`): List of ranked runner-up candidate pond sites.
- **`catchment`** (`CatchmentSummary`, optional): Delineated upstream drainage basin contributing to the recommended pond site.
- **`processing_notes`** (`string[]`): Step-by-step processing log, parameter choices, and warnings.

---

#### `PondSiteSummary` Object Structure

Each candidate pond site (both `recommended_site` and entries in `alternative_sites`) contains:

| Field | Type | Description |
| :--- | :--- | :--- |
| `site_id` | `string` | Unique site identifier (e.g. `"site_1"`, `"site_2"`). |
| `rank` | `int` | Suitability ranking (`1` is the highest recommended location). |
| `latitude` | `float` | Centroid Latitude in WGS84 decimal degrees (e.g. `21.255362`). |
| `longitude` | `float` | Centroid Longitude in WGS84 decimal degrees (e.g. `81.281455`). |
| `elevation_m` | `float` | Average ground surface elevation at the pond site (meters). |
| `suitability_score` | `float` | Composite terrain suitability score between `0.0` and `100.0`. |
| `area_m2` | `float` | Contiguous excavation footprint area in square meters. |
| `slope_deg` | `float` (optional) | Average slope within the site footprint (degrees). |
| `boundary_geojson` | `object` (optional) | **Suitability region boundary polygon** in standard WGS84 (EPSG:4326) GeoJSON `FeatureCollection` format. Used by frontend map renderers to highlight the exact excavation footprint. |

##### Example `boundary_geojson` in `PondSiteSummary`:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [81.28095, 21.25482],
            [81.28198, 21.25482],
            [81.28198, 21.25590],
            [81.28095, 21.25590],
            [81.28095, 21.25482]
          ]
        ]
      },
      "properties": {
        "site_id": "site_1",
        "rank": 1,
        "area_m2": 1600.0,
        "mean_suitability_score": 100.0
      }
    }
  ]
}
```

---

#### `CatchmentSummary` Object Structure

| Field | Type | Description |
| :--- | :--- | :--- |
| `boundary_geojson` | `object` (optional) | Upstream watershed catchment polygon in standard WGS84 GeoJSON `FeatureCollection` format. |
| `area_m2` | `float` | Contributing drainage area in square meters. |
| `area_hectares` | `float` | Contributing drainage area in hectares (`1 ha = 10,000 m²`). |
| `average_slope_deg` | `float` | Average terrain slope across the contributing catchment basin (degrees). |
| `elevation_range_m` | `object` | Basin relief stats: `min_m`, `max_m`, and `relief_m` (`max_m - min_m`). |
| `delineation_method` | `string` | Hydrological routing method used: `"flow_accumulation"` (Pysheds) or `"basin_approximation"` (Native D8 BFS). |

---

### 3.2 GET `/analyzeContour/schema`

Returns the complete OpenAPI JSON schema for `CatchmentResponse` and default pipeline configuration parameters.

#### Response Example
```json
{
  "status": "ok",
  "model": "CatchmentResponse",
  "schema": { ... },
  "default_parameters": { ... },
  "example_response": { ... }
}
```

---

### 3.3 GET `/health`

Performs an operational health check.

#### Response
```json
{
  "status": "ok",
  "message": "Pond Catchment API is running"
}
```

---

## 4. Example Requests & Responses

### 4.1 cURL Request

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour" \
  -H "Accept: application/json" \
  -F "file=@contours_1m.kml" \
  -F "dem_resolution_m=10.0" \
  -F "ideal_slope_deg=3.0" \
  -F "max_slope_deg=8.0" \
  -F "suitability_threshold=60.0" \
  -F "min_pond_area_m2=200.0"
```

### 4.2 Python (`requests`) Request

```python
import requests

url = "http://127.0.0.1:8000/analyzeContour"
files = {"file": open("contours_1m.kml", "rb")}
data = {
    "dem_resolution_m": 10.0,
    "ideal_slope_deg": 3.0,
    "max_slope_deg": 8.0,
    "suitability_threshold": 60.0,
    "min_pond_area_m2": 200.0,
}

response = requests.post(url, files=files, data=data)
result = response.json()

print(f"Status: {result['status']}")
if result.get("recommended_site"):
    top = result["recommended_site"]
    print(f"Top Site #{top['rank']} ({top['site_id']}): Score={top['suitability_score']}, Area={top['area_m2']} m²")
    print(f"Centroid: ({top['latitude']}, {top['longitude']})")
    print(f"Boundary Polygon Features: {len(top['boundary_geojson']['features'])}")

if result.get("catchment"):
    catch = result["catchment"]
    print(f"Catchment Area: {catch['area_hectares']} ha ({catch['area_m2']} m²)")
```

### 4.3 JavaScript / TypeScript (`fetch`) Request

```typescript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('dem_resolution_m', '10.0');
formData.append('suitability_threshold', '60.0');

const response = await fetch('http://127.0.0.1:8000/analyzeContour', {
  method: 'POST',
  body: formData,
});

const data = await response.json();
console.log('Recommended Site:', data.recommended_site);
console.log('Site Boundary Polygon:', data.recommended_site?.boundary_geojson);
```

### 4.4 Example JSON Response

```json
{
  "status": "success",
  "message": "Contour analysis and pond catchment delineation completed successfully.",
  "input_summary": {
    "num_contours": 2711,
    "elevation_min": 30.0,
    "elevation_max": 298.0,
    "dem_resolution_m": 10.0,
    "utm_crs": "EPSG:32644"
  },
  "recommended_site": {
    "site_id": "site_1",
    "rank": 1,
    "latitude": 21.255362,
    "longitude": 81.281455,
    "elevation_m": 30.0,
    "suitability_score": 100.0,
    "area_m2": 1600.0,
    "slope_deg": 0.14,
    "boundary_geojson": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": {
            "type": "Polygon",
            "coordinates": [
              [
                [81.28095, 21.25482],
                [81.28198, 21.25482],
                [81.28198, 21.25590],
                [81.28095, 21.25590],
                [81.28095, 21.25482]
              ]
            ]
          },
          "properties": {
            "site_id": "site_1",
            "rank": 1,
            "area_m2": 1600.0,
            "mean_suitability_score": 100.0
          }
        }
      ]
    }
  },
  "alternative_sites": [
    {
      "site_id": "site_2",
      "rank": 2,
      "latitude": 21.257102,
      "longitude": 81.283415,
      "elevation_m": 32.5,
      "suitability_score": 94.8,
      "area_m2": 1200.0,
      "slope_deg": 0.85,
      "boundary_geojson": {
        "type": "FeatureCollection",
        "features": [
          {
            "type": "Feature",
            "geometry": {
              "type": "Polygon",
              "coordinates": [
                [
                  [81.28290, 21.25650],
                  [81.28390, 21.25650],
                  [81.28390, 21.25770],
                  [81.28290, 21.25770],
                  [81.28290, 21.25650]
                ]
              ]
            },
            "properties": {
              "site_id": "site_2",
              "rank": 2,
              "area_m2": 1200.0,
              "mean_suitability_score": 94.8
            }
          }
        ]
      }
    }
  ],
  "catchment": {
    "boundary_geojson": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": {
            "type": "Polygon",
            "coordinates": [
              [
                [81.27500, 21.24800],
                [81.28500, 21.24800],
                [81.28500, 21.26000],
                [81.27500, 21.26000],
                [81.27500, 21.24800]
              ]
            ]
          },
          "properties": {
            "delineation_method": "basin_approximation",
            "area_m2": 1400.0,
            "area_ha": 0.14
          }
        }
      ]
    },
    "area_m2": 1400.0,
    "area_hectares": 0.14,
    "average_slope_deg": 34.6,
    "elevation_range_m": {
      "min_m": 30.0,
      "max_m": 280.5,
      "relief_m": 250.5
    },
    "delineation_method": "basin_approximation"
  },
  "processing_notes": [
    "Parsed 2711 contour lines with elevations ranging from 30.0m to 298.0m.",
    "Generated DEM grid: 264x326 cells at 10.0m resolution in EPSG:32644.",
    "Computed terrain derivatives: mean slope=7.2°, mean suitability=58.6/100, suitable area=50.2%.",
    "Selected top recommended pond site (site_1): score=100.0, area=1600m² at (21.25536°N, 81.28146°E).",
    "Delineated upstream catchment using basin_approximation: area=0.14 ha (1,400m²), elevation span=250.5m, mean slope=34.6°."
  ]
}
