# JalaSetu

Automated terrain analysis, farm pond site selection, and catchment delineation from topographic contour maps.

---

## 1. Project Overview

JalaSetu is a geospatial system for identifying optimal farm pond excavation sites and computing upstream rainwater catchment areas from contour maps.

In many rural watershed planning projects, farm pond siting is conducted ad hoc through visual inspection without quantitative terrain analysis. This frequently results in ponds placed on excessive slopes, in areas with insufficient drainage catchment, or where excavation yields poor storage efficiency.

JalaSetu provides an end-to-end automated workflow:
1. The user uploads an elevation contour map file (.kml or .kmz).
2. The backend extracts elevation contours, constructs a Digital Elevation Model (DEM), derives terrain slope and depression metrics, identifies candidate pond sites, and delineates the upstream contributing catchment basin.
3. The frontend displays the recommended site, alternative candidates, excavation footprint statistics, catchment boundary polygon, and processing notes on an interactive map.

---

## 2. Architecture

The project consists of two components:
- **Backend (`app/`)**: A FastAPI Python service that handles geospatial parsing, raster DEM interpolation, terrain analysis, site ranking, and hydrological catchment delineation.
- **Frontend (`frontend/`)**: A single-page web client built with React, Vite, and React-Leaflet.

The frontend interacts with the backend over HTTP by sending `multipart/form-data` requests to the `/analyzeContour` endpoint. The API client uses the `VITE_API_BASE_URL` environment variable, which defaults to `http://127.0.0.1:8000`.

### Directory Tree

```text
JalaSetu/
├── README.md
├── requirements.txt
├── contours_1m.kml
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py
│   ├── routers/
│   │   ├── __init__.py
│   │   └── catchment.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── catchment_delineation.py
│   │   ├── dem_builder.py
│   │   ├── kml_parser.py
│   │   ├── pipeline.py
│   │   ├── pond_site.py
│   │   └── terrain_analysis.py
│   └── utils/
│       ├── __init__.py
│       └── geometry.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       ├── index.css
│       ├── main.jsx
│       ├── api/
│       │   ├── catchmentApi.d.ts
│       │   └── catchmentApi.js
│       └── components/
│           ├── CatchmentDetailsPanel.jsx
│           ├── MapView.jsx
│           ├── ProcessingNotesBanner.jsx
│           ├── ResultsLayer.jsx
│           ├── SiteSummaryPanel.jsx
│           └── UploadPanel.jsx
├── scripts/
│   └── demo_run.py
└── tests/
    ├── __init__.py
    ├── test_api_e2e.py
    ├── test_api_routes.py
    ├── test_catchment_delineation.py
    ├── test_dem_builder.py
    ├── test_health.py
    ├── test_kml_parser.py
    ├── test_pipeline.py
    ├── test_pond_site.py
    └── test_terrain_analysis.py
```

---

## 3. Backend

### Service Modules

The processing pipeline runs through modules in `app/services/` in the following sequence:

1. **`kml_parser.py` (`KMLParserService`)**:
   Parses uploaded `.kml` and `.kmz` files into GeoDataFrames in EPSG:4326. Uses a multi-strategy elevation extraction approach:
   - `<ExtendedData>` tags (`<Data>` and `<SimpleData>`) matching elevation attribute names.
   - `<name>` tag regex patterns (e.g. `Contour 450`, `450m`, numbers).
   - `<description>` tag regex patterns.
   - 3D coordinate geometry (Z-coordinate values).
   Features lacking identifiable elevation attributes are skipped with logged warnings.

2. **`dem_builder.py` (`DEMBuilderService`)**:
   Reprojects contour lines from WGS84 (EPSG:4326) to an auto-calculated local metric UTM projection. Samples vertices and interpolates a continuous 2D raster DEM using SciPy (`scipy.interpolate.griddata` with linear/cubic methods and nearest-neighbor boundary fill). Derives data-driven grid resolution when not explicitly set. Packages output into a `DEMData` dataclass.

3. **`terrain_analysis.py` (`TerrainAnalysisService`)**:
   Calculates terrain derivatives from the DEM:
   - Slope in degrees and percentage via finite-difference gradient.
   - Topographic Position Index (TPI) and local depression index (0 to 100) using neighborhood window filters.
   - Weighted composite suitability score (0 to 100) combining slope criteria and local depression factors.
   - Binary suitability mask of valid excavation cells.

4. **`pond_site.py` (`PondSiteService`)**:
   Segments contiguous suitable raster cells using 8-connectivity connected-component labeling (`scipy.ndimage.label`). Filters candidate regions by footprint area constraints (`min_pond_area_m2`), elongation aspect ratio (`max_elongation_ratio`) to reject linear road/channel corridors, and minimum usable footprint width (`min_pond_width_m`). Computes real-world coordinates (WGS84 and UTM), average elevation, slope, shape metrics, excavation area, and suitability ranks.

5. **`catchment_delineation.py` (`CatchmentDelineationService`)**:
   Traces the upstream contributing drainage basin for the top recommended pond location. Attempts Pysheds hydrological routing (pit filling, depression resolution, D8 flow direction, flow accumulation, and stream snapping). Falls back to native D8 steepest descent with topological sort accumulation and reverse breadth-first search (BFS) if Pysheds is unavailable or fails. Vectorizes the catchment raster mask into a GeoJSON FeatureCollection polygon.

6. **`pipeline.py` (`analyze_contour_file`)**:
   Orchestrates the entire sequence from input file to structured `CatchmentResponse`. Applies configuration defaults from `DEFAULT_PIPELINE_PARAMS`, handles error recovery, triggers relaxed parameter fallback if initial criteria find no candidate sites, and logs execution notes.

`app/utils/geometry.py` provides supporting functions for calculating the optimal UTM EPSG zone from longitude/latitude bounds and reprojecting GeoDataFrames.

### Local Installation and Setup

Prerequisites: Python 3.9 or higher.

1. Navigate to the project root:
   ```bash
   cd JalaSetu
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   # On Windows: .\venv\Scripts\Activate.ps1
   ```

3. Install backend dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Start the backend development server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   Or run the module directly:
   ```bash
   python -m app.main
   ```

The backend server listens on `http://127.0.0.1:8000`.

### Environment Configuration

The backend runs with sensible defaults out of the box. No mandatory `.env` file is required for local execution. CORS is enabled for all origins by default in `app/main.py`.

### Running Backend Tests

Run all tests using pytest:

```bash
pytest tests/ -v
```

### Test Suite Breakdown

| Test File | Scope and Coverage |
|---|---|
| `tests/test_health.py` | Validates `GET /health` endpoint response code and status message. |
| `tests/test_kml_parser.py` | Tests KML/KMZ parsing strategies (name regex, ExtendedData, 3D coordinates), feature skipping, KMZ unzipping, and UTM reprojection. |
| `tests/test_dem_builder.py` | Tests DEM grid interpolation on synthetic conical hill data, bounds validity, GeoTIFF export, and hillshade generation. |
| `tests/test_terrain_analysis.py` | Verifies finite-difference slope angles against analytical planar ramps, depression index on synthetic bowls, and GeoTIFF/PNG export. |
| `tests/test_pond_site.py` | Verifies connected component extraction, centroid calculation, minimum area filtering, and linear road corridor shape rejection. |
| `tests/test_catchment_delineation.py` | Tests watershed delineation on synthetic V-valley terrain, pour point snapping, and GeoJSON export. |
| `tests/test_pipeline.py` | Integration test running `analyze_contour_file` on synthetic KML data. |
| `tests/test_api_routes.py` | Tests FastAPI route validation, parameter bounds checking, invalid extension rejection, and empty file handling. |
| `tests/test_api_e2e.py` | End-to-end test verifying full Pydantic response schemas, coordinate bounding box containment, positive catchment area, and live execution on `contours_1m.kml`. |

---

## 4. API Reference

Interactive documentation is available at:
- **Swagger UI**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

### Endpoints Overview

| Method | Path | Summary |
|---|---|---|
| `POST` | `/analyzeContour` | Upload contour map, analyze terrain, rank pond sites, and delineate catchment. |
| `GET` | `/analyzeContour/schema` | Retrieve OpenAPI response schema documentation and example payload. |
| `GET` | `/health` | Check operational status of the server. |

---

### POST `/analyzeContour`

Accepts a contour map file via `multipart/form-data` and executes the terrain analysis pipeline.

#### Request Form Parameters

| Field Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | File | Yes | | KML (.kml) or KMZ (.kmz) file containing elevation contour lines. |
| `dem_resolution_m` | float | No | Auto | DEM raster grid cell resolution in meters (0.5 to 100.0). Derived adaptively if omitted. |
| `sample_spacing_m` | float | No | Auto | Contour vertex sampling interval in meters (0.5 to 100.0). Defaults to resolution / 2. |
| `ideal_slope_deg` | float | No | `3.0` | Maximum ideal slope in degrees (0.0 to 45.0). Slopes below this receive 100% slope score. |
| `max_slope_deg` | float | No | `8.0` | Upper allowable slope limit in degrees (1.0 to 60.0). Slopes above this receive 0% slope score. |
| `neighborhood_radius_m` | float | No | Auto | Neighborhood filter radius in meters for local depression detection (5.0 to 500.0). |
| `weight_slope` | float | No | `0.5` | Weight for slope factor in composite suitability score (0.0 to 1.0). |
| `weight_depression` | float | No | `0.5` | Weight for depression factor in composite suitability score (0.0 to 1.0). |
| `suitability_threshold` | float | No | `60.0` | Minimum suitability score (0.0 to 100.0) required for candidate pond sites. |
| `min_pond_area_m2` | float | No | `200.0` | Minimum contiguous footprint in square meters for a viable pond (10.0 to 1,000,000.0). |
| `max_pond_area_m2` | float | No | None | Optional maximum allowable pond footprint in square meters (50.0 to 10,000,000.0). |
| `max_candidate_sites` | int | No | `5` | Maximum number of ranked candidate pond sites to return (1 to 20). |
| `max_elongation_ratio` | float | No | `3.5` | Maximum allowable major-to-minor axis elongation ratio (1.0 to 50.0) to filter out roads and corridors. |
| `min_pond_width_m` | float | No | Auto | Minimum allowable pond footprint width in meters (1.0 to 500.0). Derived from cell size if omitted. |
| `snap_radius_m` | float | No | `25.0` | Search radius in meters to snap pour point to stream channel (0.0 to 200.0). |
| `use_pysheds` | bool | No | `true` | Attempt Pysheds hydrological flow accumulation first before native D8 fallback. |

#### Response Schema (`CatchmentResponse`)

The response schema matches `app/models/schemas.py`:

| Field Name | Type | Description |
|---|---|---|
| `status` | string | Execution status: `success`, `no_suitable_site`, `partial_success`, or `error`. |
| `message` | string (optional) | Summary explanation of analysis results. |
| `input_summary` | object (optional) | Summary of parsed contour inputs and DEM metadata. |
| `input_summary.num_contours` | integer | Total number of contour features extracted from KML/KMZ. |
| `input_summary.elevation_min` | float | Minimum elevation found in contour lines (meters). |
| `input_summary.elevation_max` | float | Maximum elevation found in contour lines (meters). |
| `input_summary.dem_resolution_m` | float | Interpolated DEM raster cell resolution (meters/pixel). |
| `input_summary.utm_crs` | string (optional) | Auto-detected local UTM Projected CRS (e.g. `EPSG:32643`). |
| `recommended_site` | object (optional) | Top-ranked recommended pond site (rank 1). |
| `recommended_site.site_id` | string | Unique identifier for candidate site (e.g. `site_1`). |
| `recommended_site.rank` | integer | Suitability rank (1 is highest recommendation). |
| `recommended_site.latitude` | float | Centroid latitude in WGS84 decimal degrees. |
| `recommended_site.longitude` | float | Centroid longitude in WGS84 decimal degrees. |
| `recommended_site.elevation_m` | float | Average ground elevation at pond site (meters). |
| `recommended_site.suitability_score` | float | Composite terrain suitability score (0 to 100). |
| `recommended_site.area_m2` | float | Contiguous excavation footprint area (square meters). |
| `recommended_site.slope_deg` | float (optional) | Average terrain slope at site (degrees). |
| `recommended_site.boundary_geojson` | object (optional) | Suitability region boundary polygon in standard WGS84 GeoJSON FeatureCollection format. |
| `alternative_sites` | array of objects | Ranked alternative candidate pond sites (same fields as `recommended_site` including `boundary_geojson`). |
| `catchment` | object (optional) | Delineated upstream catchment contributing to recommended pond site. |
| `catchment.boundary_geojson` | object (optional) | Catchment boundary polygon in standard WGS84 GeoJSON FeatureCollection format. |
| `catchment.area_m2` | float | Catchment contributing drainage area (square meters). |
| `catchment.area_hectares` | float | Catchment contributing drainage area (hectares). |
| `catchment.average_slope_deg` | float | Mean ground slope across the catchment (degrees). |
| `catchment.elevation_range_m` | object | Elevation relief metrics across the catchment basin. |
| `catchment.elevation_range_m.min_m` | float | Lowest elevation point in catchment (meters). |
| `catchment.elevation_range_m.max_m` | float | Highest ridge elevation in catchment (meters). |
| `catchment.elevation_range_m.relief_m` | float | Total basin elevation relief span (`max_m - min_m`) (meters). |
| `catchment.delineation_method` | string | Hydrological routing engine used (`flow_accumulation` or `basin_approximation`). |
| `processing_notes` | array of strings | Execution logs, parameter choices, skipped features, and warnings. |

#### Example Request

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "dem_resolution_m=5.0" \
  -F "ideal_slope_deg=3.0" \
  -F "max_slope_deg=8.0" \
  -F "min_pond_area_m2=200.0" \
  -F "suitability_threshold=60.0"
```

#### Example Response

```json
{
  "status": "success",
  "message": "Contour analysis and pond catchment delineation completed successfully.",
  "input_summary": {
    "num_contours": 34,
    "elevation_min": 420.0,
    "elevation_max": 480.0,
    "dem_resolution_m": 5.0,
    "utm_crs": "EPSG:32643"
  },
  "recommended_site": {
    "site_id": "site_1",
    "rank": 1,
    "latitude": 28.553412,
    "longitude": 77.112845,
    "elevation_m": 431.25,
    "suitability_score": 91.4,
    "area_m2": 1450.0,
    "slope_deg": 1.85,
    "boundary_geojson": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": {
            "type": "Polygon",
            "coordinates": [
              [
                [77.111, 28.552],
                [77.114, 28.552],
                [77.114, 28.555],
                [77.111, 28.555],
                [77.111, 28.552]
              ]
            ]
          },
          "properties": {
            "site_id": "site_1",
            "rank": 1,
            "area_m2": 1450.0
          }
        }
      ]
    }
  },
  "alternative_sites": [
    {
      "site_id": "site_2",
      "rank": 2,
      "latitude": 28.558901,
      "longitude": 77.11893,
      "elevation_m": 438.5,
      "suitability_score": 86.2,
      "area_m2": 875.0,
      "slope_deg": 2.4,
      "boundary_geojson": {
        "type": "FeatureCollection",
        "features": [
          {
            "type": "Feature",
            "geometry": {
              "type": "Polygon",
              "coordinates": [
                [
                  [77.117, 28.557],
                  [77.12, 28.557],
                  [77.12, 28.56],
                  [77.117, 28.56],
                  [77.117, 28.557]
                ]
              ]
            },
            "properties": {
              "site_id": "site_2",
              "rank": 2,
              "area_m2": 875.0
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
                [77.105, 28.548],
                [77.12, 28.548],
                [77.12, 28.56],
                [77.105, 28.56],
                [77.105, 28.548]
              ]
            ]
          },
          "properties": {
            "delineation_method": "flow_accumulation",
            "area_m2": 184500.0,
            "area_ha": 18.45
          }
        }
      ]
    },
    "area_m2": 184500.0,
    "area_hectares": 18.45,
    "average_slope_deg": 4.82,
    "elevation_range_m": {
      "min_m": 431.2,
      "max_m": 478.5,
      "relief_m": 47.3
    },
    "delineation_method": "flow_accumulation"
  },
  "processing_notes": [
    "Parsed 34 contour lines with elevations ranging from 420.0m to 480.0m.",
    "Generated DEM grid: 340x280 cells at 5.0m resolution in EPSG:32643.",
    "Computed terrain derivatives: mean slope=4.2°, mean suitability=58.3/100, suitable area=14.6%.",
    "Selected top recommended pond site (site_1): score=91.4, area=1450m² at (28.55341°N, 77.11285°E).",
    "Delineated upstream catchment using flow_accumulation: area=18.45 ha (184,500m²), elevation span=47.3m, mean slope=4.8°."
  ]
}
```

---

### GET `/analyzeContour/schema`

Returns the full OpenAPI JSON schema definition for `CatchmentResponse`, default parameters, and a reference example payload.

#### Example Request

```bash
curl http://127.0.0.1:8000/analyzeContour/schema
```

---

### GET `/health`

Operational health check endpoint.

#### Example Request

```bash
curl http://127.0.0.1:8000/health
```

#### Example Response

```json
{
  "status": "ok",
  "message": "Pond Catchment API is running"
}
```

---

## 5. Frontend

### Capabilities

The frontend allows users to:
- Drag and drop or browse for `.kml` and `.kmz` contour map files.
- Inspect the top recommended pond location and ranked alternative candidate sites.
- View the contributing watershed boundary polygon overlay and candidate markers on an interactive Leaflet map.
- Review terrain statistics including basin drainage area, elevation relief, slope, and excavation footprint.
- Read processing notes and warnings regarding fallback routing or relaxed thresholds.

### Component Breakdown

Components are located in `frontend/src/components/`:

- **`UploadPanel.jsx`**: Handles file drag-and-drop, format validation (.kml/.kmz), upload progress indication, parameter overrides, and error alerts.
- **`MapView.jsx`**: Renders the Leaflet interactive map container with OpenStreetMap tiles, automatic bounding box fitting, and smooth camera panning.
- **`ResultsLayer.jsx`**: Renders map vector overlays, including the semi-transparent catchment boundary polygon, rank 1 pond site marker, and alternative site markers with popup cards.
- **`SiteSummaryPanel.jsx`**: Displays metrics for the top recommended pond site (score, excavation area, coordinates, elevation, slope) and includes an expandable list of alternative sites with focus triggers.
- **`CatchmentDetailsPanel.jsx`**: Displays catchment drainage area (hectares and square meters), basin elevation range, average slope, and a routing method indicator badge.
- **`ProcessingNotesBanner.jsx`**: Renders dismissible notices translating backend execution logs and routing fallback caveats into plain guidance.

The API client in `frontend/src/api/catchmentApi.js` builds `multipart/form-data` requests, sends them to `POST /analyzeContour`, and normalizes HTTP and connection errors into structured error objects.

### Local Installation and Setup

Prerequisites: Node.js 18 or higher, npm 9 or higher.

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Configure environment variables:
   Create a `.env` file in the `frontend/` directory (optional):
   ```env
   VITE_API_BASE_URL=http://127.0.0.1:8000
   ```
   If omitted, the API client automatically defaults to `http://127.0.0.1:8000`.

4. Start the development server:
   ```bash
   npm run dev
   ```

The frontend application will be available at `http://localhost:5173`.

### Production Build

To compile and bundle optimized static assets:

```bash
npm run build
```

The output is generated in the `frontend/dist/` directory.

To preview the production build locally:

```bash
npm run preview
```

---

## 6. Running the Full Stack Locally

Follow these steps to run both backend and frontend together:

### Step 1: Start the Backend Server

Open a terminal at the repository root:

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Confirm backend health:
```bash
curl http://127.0.0.1:8000/health
```

### Step 2: Start the Frontend Client

Open a second terminal:

```bash
cd frontend
npm run dev
```

### Step 3: Test the End-to-End Workflow

1. Open `http://localhost:5173` in a web browser.
2. Confirm the header badge displays "Waiting for Contour Upload".
3. Upload the sample contour file `contours_1m.kml` located at the root of this repository.
4. The system executes the analysis pipeline and renders:
   - The delineated catchment basin polygon on the map.
   - The top recommended pond excavation site marker.
   - Ranked alternative candidate sites.
   - Drainage area and slope statistics in the sidebar panels.

### Step 4: Run CLI Demo Script (Alternative)

You can also run the complete analysis directly from the command line using `scripts/demo_run.py`:

```bash
# Run against running backend server
python scripts/demo_run.py contours_1m.kml --mode api

# Run in-process pipeline without a server
python scripts/demo_run.py contours_1m.kml --mode direct --output-dir ./output
```

The script prints the structured JSON report and saves a composite visualization plot (`output/contours_1m_demo_visualization.png`).

---

## 7. Deployment Guide

### Backend Deployment

The backend is an ASGI application (`app.main:app`).

#### Production ASGI Server

Run Uvicorn with multiple workers:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Or run Gunicorn with Uvicorn workers:
```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app -b 0.0.0.0:8000
```

#### Containerization (Dockerfile)

A production Dockerfile for the backend requires system geospatial libraries (GDAL, GEOS, PROJ) for `rasterio`, `geopandas`, and `shapely`:

```dockerfile
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    gdal-bin \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

#### Hosting Platforms

The backend can be hosted on:
- **Container Services (Render, Railway, Fly.io, AWS ECS, Google Cloud Run)**: Build using the Dockerfile above. Allocate at least 1 GB to 2 GB RAM for spatial interpolation operations on large contour datasets.
- **Linux Virtual Machine (Ubuntu/Debian on AWS EC2, DigitalOcean, Hetzner)**: Install system packages (`sudo apt install libgdal-dev gdal-bin libgeos-dev libproj-dev python3-venv`), set up a systemd service unit, and place Nginx as a reverse proxy in front of Uvicorn.

### Frontend Deployment

#### Building Static Assets

Compile the frontend:
```bash
cd frontend
VITE_API_BASE_URL="https://api.yourdomain.com" npm run build
```

The compiled assets in `frontend/dist/` can be served by any static web server or CDN platform.

#### Hosting Platforms

- **Vercel / Netlify / Cloudflare Pages**: Connect the Git repository, set the root directory to `frontend`, set the build command to `npm run build`, and set the output directory to `dist`. Configure the environment variable `VITE_API_BASE_URL` to point to the deployed backend URL.
- **Nginx / S3 / CloudFront**: Upload the contents of `frontend/dist/` to your static file root or S3 bucket, configured for single-page application (SPA) routing fallback to `index.html`.

### CORS Configuration

The backend must allow requests from the deployed frontend origin. In `app/main.py`, the CORS middleware is configured as:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with specific frontend domain in strict production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

For strict production security, replace `allow_origins=["*"]` with your specific frontend domain (e.g. `allow_origins=["https://jalasetu.yourdomain.com"]`).

### Post-Deployment Verification Checklist

1. Send a request to `GET /health` on the deployed backend URL and verify HTTP 200 with `status: "ok"`.
2. Open the deployed frontend URL in a browser and verify that the page loads with no JavaScript console errors.
3. Upload `contours_1m.kml` through the web interface and confirm that the API call completes and displays pond sites and catchment polygons.
4. Verify that reverse proxies (e.g. Nginx or Cloudflare) allow file uploads up to at least 50 MB (`client_max_body_size 50M`).
5. Verify that gateway timeouts are set to at least 60 to 120 seconds to accommodate compute-heavy interpolation on large contour files.

---

## 8. Known Limitations and Future Work

### Known Limitations

- **DEM Resolution and Extent**: Interpolating large geographic extents at high resolution (e.g. sub-meter) increases memory usage and computation time. The system uses adaptive resolution (clamping between 1.0m and 50.0m) to balance detail with performance.
- **Hydrological Routing Fallbacks**: When continuous flow routing through Pysheds encounters complex sink depressions or flat terrain, the pipeline falls back to native D8 breadth-first search (`basin_approximation`). This may produce simplified watershed boundaries in very flat terrain.
- **No Rainfall and Infiltration Modeling**: The current implementation computes topographic suitability and geometric catchment drainage area. It does not model precipitation time-series, soil infiltration rates, evaporation losses, or runoff volume hydrographs.
- **Contour Input Quality**: The accuracy of DEM interpolation depends on the density and vertical interval of the input contour lines. Coarse or sparse contour maps will produce smoother, less defined drainage channels.

### Future Work

- **Runoff Yield Estimation**: Integrate rainfall statistics (e.g. IMD or CHIRPS datasets) to compute estimated monsoon runoff harvest volumes in cubic meters.
- **Soil and Infiltration Layers**: Incorporate soil texture data to assess pond percolation rates and determine lining requirements.
- **Earthwork Volume Calculation**: Compute cut-and-fill excavation volumes and embankment dimensions for candidate pond sites.

---

## 9. Repository Structure

```text
JalaSetu/
├── README.md                              # Main project documentation
├── requirements.txt                      # Python backend dependencies
├── contours_1m.kml                       # Sample contour dataset (1m interval)
│
├── app/                                  # FastAPI backend source
│   ├── __init__.py
│   ├── main.py                           # Application entrypoint & middleware
│   │
│   ├── models/                           # Pydantic schemas & contracts
│   │   ├── __init__.py
│   │   └── schemas.py                    # Request and response models
│   │
│   ├── routers/                          # API route definitions
│   │   ├── __init__.py
│   │   └── catchment.py                  # /analyzeContour & /health endpoints
│   │
│   ├── services/                         # Core geospatial pipeline services
│   │   ├── __init__.py
│   │   ├── kml_parser.py                 # KML/KMZ extraction & elevation parsing
│   │   ├── dem_builder.py                # UTM reprojection & DEM interpolation
│   │   ├── terrain_analysis.py           # Slope, depression, & suitability scoring
│   │   ├── pond_site.py                  # Candidate site extraction & ranking
│   │   ├── catchment_delineation.py      # Watershed routing & GeoJSON vectorization
│   │   └── pipeline.py                   # End-to-end pipeline orchestrator
│   │
│   └── utils/                            # Geospatial helper utilities
│       ├── __init__.py
│       └── geometry.py                   # UTM zone detection & reprojection helpers
│
├── frontend/                             # React Vite web client
│   ├── index.html                        # HTML entrypoint
│   ├── package.json                      # NPM dependencies & build scripts
│   ├── package-lock.json
│   ├── vite.config.js                    # Vite configuration
│   │
│   └── src/
│       ├── App.jsx                       # Main application component & state
│       ├── index.css                     # Global styles & layout
│       ├── main.jsx                      # React DOM mounting entrypoint
│       │
│       ├── api/                          # Backend API client
│       │   ├── catchmentApi.d.ts         # TypeScript type definitions
│       │   └── catchmentApi.js           # Axios client & error normalization
│       │
│       └── components/                   # Modular UI components
│           ├── CatchmentDetailsPanel.jsx # Catchment statistics & hydrology metrics
│           ├── MapView.jsx               # React-Leaflet map view container
│           ├── ProcessingNotesBanner.jsx # Notice banner for processing logs & caveats
│           ├── ResultsLayer.jsx          # Vector layers for sites & watershed polygon
│           ├── SiteSummaryPanel.jsx      # Top site summary & alternative candidate list
│           └── UploadPanel.jsx           # Drag-and-drop file upload interface
│
├── scripts/
│   └── demo_run.py                       # CLI demo runner & visualization exporter
│
├── output/                               # Default directory for exported test artifacts
│   ├── contours_1m_analysis_response.json
│   └── contours_1m_demo_visualization.png
│
└── tests/                                # Backend test suite (pytest)
    ├── __init__.py
    ├── test_api_e2e.py                   # End-to-end API integration tests
    ├── test_api_routes.py                # FastAPI route validation tests
    ├── test_catchment_delineation.py     # Watershed delineation tests
    ├── test_dem_builder.py               # DEM builder & GeoTIFF export tests
    ├── test_health.py                    # Health check endpoint test
    ├── test_kml_parser.py                # KML/KMZ parser unit tests
    ├── test_pipeline.py                  # Pipeline integration tests
    ├── test_pond_site.py                 # Pond siting algorithm tests
    └── test_terrain_analysis.py          # Slope & depression index tests
```
