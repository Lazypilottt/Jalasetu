# JalaSetu

## Farm-Pond Siting and Catchment Analysis

JalaSetu is a geospatial decision-support application for identifying suitable
farm-pond locations from topographic contour data. It combines a FastAPI
backend, a React/Leaflet web interface, and a terrain-analysis pipeline that
constructs a digital elevation model (DEM), ranks candidate pond sites,
delineates the upstream catchment, and estimates collectible stormwater.

The application is designed for watershed planning, village-scale water
conservation, and rapid preliminary site screening. It provides a technical
recommendation, not a substitute for a field survey, detailed engineering
design, or statutory approval.

**New:** Location Recommendation API for finding the 10 closest locations from
a 10,000-node dataset using shortest-path routing. See [Location API](#location-recommendation-api).

---

## Contents

- [Features](#features)
- [System architecture](#system-architecture)
- [Quick start](#quick-start)
- [Using the web application](#using-the-web-application)
- [Analysis outputs](#analysis-outputs)
- [API reference](#api-reference)
- [Location Recommendation API](#location-recommendation-api)
- [Configuration](#configuration)
- [Testing](#testing)
- [Distributed services](#distributed-services)
- [Deployment](#deployment)
- [Performance and scaling](#performance-and-scaling)
- [Limitations](#limitations)
- [Repository structure](#repository-structure)
- [Engineering notes](#engineering-notes)

---

## Features

### Interactive frontend

- Upload `.kml` and `.kmz` contour files by browsing or drag-and-drop.
- Select a 250 m radius analysis area directly on the map.
- Analyze the selected area with an uploaded contour file or, for
  demonstration purposes, the bundled [`contours_1m.kml`](./contours_1m.kml)
  dataset.
- View the recommended pond location and ranked alternatives.
- Overlay the selected area, candidate pond footprints, recommended pond, and
  upstream catchment on the map.
- Review catchment area, expected storm runoff volume, pond storage capacity,
  terrain slope, elevation range, suitability score, and processing notes.
- Focus the map on any recommended or alternative candidate.
- Receive clear validation, server, timeout, and processing error messages.

### Terrain and hydrology pipeline

- Multi-strategy KML/KMZ elevation extraction.
- Local UTM reprojection for metric calculations.
- Adaptive DEM interpolation using SciPy.
- Slope, local depression, and topographic wetness analysis.
- Connected-component candidate extraction with area, width, and shape filters.
- Candidate ranking using weighted terrain suitability criteria.
- Pysheds-based flow routing with a native D8 fallback.
- SCS Curve Number runoff estimation for the delineated catchment.
- GeoJSON boundaries for frontend visualization.

---

## System architecture

```text
React + Leaflet frontend
          |
          | multipart/form-data over HTTP
          v
FastAPI API (/analyzeContour)
          |
          v
Contour parser -> DEM builder -> terrain analysis
          |
          v
Pond-site ranking -> catchment delineation -> runoff estimation
          |
          v
Structured CatchmentResponse + GeoJSON overlays
```

### Main components

| Component | Responsibility |
|---|---|
| `app/` | FastAPI application, request validation, schemas, and geospatial services |
| `frontend/` | React/Vite client and Leaflet map interface |
| `distributed/` | Optional staged services for DEM, terrain/site ranking, and gateway processing |
| `tests/` | Unit, integration, API, and end-to-end tests |
| `contours_1m.kml` | Bundled demonstration contour dataset |

The standard local workflow uses the FastAPI pipeline directly. The distributed
services are optional and are intended for deployment experiments or
stage-by-stage scaling.

---

## Quick start

### Prerequisites

- Python 3.9 or newer
- Node.js 18 or newer
- npm 9 or newer
- A modern browser with JavaScript enabled

### 1. Set up the backend

From the repository root:

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start the API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is available at:

- Health check: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>

### 2. Set up the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

The frontend defaults to `http://127.0.0.1:8000` for the API. To override it,
create `frontend/.env`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 3. Run the first analysis

Choose either workflow:

1. Upload `contours_1m.kml`, select an area on the map, and click
   **Analyze selected area**.
2. Select an area on the map and click **Analyze selected area (demo contours)**
   without uploading a file. This uses the bundled dataset and clearly labels
   the result as demonstration-data analysis.

The bundled dataset covers approximately longitude `81.2814`–`81.3126` and
latitude `21.2398`–`21.2636`. A selection outside that extent may produce a
nearest-site fallback or no suitable site.

---

## Using the web application

1. Start the backend and frontend.
2. Open the frontend in a browser.
3. Optionally upload a KML/KMZ contour map.
4. Click the map to place the fixed 250 m analysis circle. Click again to move
   it.
5. Click **Analyze selected area**.
6. Wait for terrain interpolation and catchment delineation to finish.
7. Review:
   - **Suggested pond location**: coordinates, elevation, slope, footprint, and
     suitability score.
   - **Catchment area**: contributing area in square metres and hectares.
   - **Expected water volume**: estimated design-storm runoff in cubic metres.
   - **Pond storage capacity**: estimated pond storage at the design depth.
8. Use the map overlays and candidate cards to compare locations.

The sidebar has its own scroll area so all controls, results, alternatives,
hydrology details, and processing notes remain accessible on smaller screens.

---

## Analysis outputs

### Suggested pond location

The top-ranked candidate includes:

- Latitude and longitude in WGS84.
- Average ground elevation.
- Average slope in degrees.
- Composite suitability score from 0 to 100.
- Estimated excavation footprint.
- Design-depth storage capacity.
- Optional pond boundary GeoJSON.

### Catchment area

The catchment result includes:

- Boundary polygon as a GeoJSON FeatureCollection.
- Area in square metres and hectares.
- Average catchment slope.
- Minimum, maximum, and relief elevation.
- Routing method used (`flow_accumulation` or `basin_approximation`).

### Expected water volume

Expected water volume is reported as
`catchment.estimated_runoff_volume_m3`. It is estimated with the SCS Curve
Number method using the configured design rainfall and curve number. The
response also includes runoff depth, runoff coefficient, hydrological
feasibility, and a filling factor where available.

This is a design-storm estimate. It is not a guarantee of annual yield and
does not account for every loss mechanism, including evaporation, seepage,
sedimentation, conveyance losses, or operational releases.

### Map overlays

The map renders:

- The selected analysis circle.
- The recommended pond footprint.
- Alternative candidate footprints and markers.
- The upstream catchment boundary.
- Popup summaries with pond location, catchment area, storage, and expected
  runoff volume.

---

## API reference

Interactive API documentation is available at:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>

### Endpoint summary

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns backend availability. |
| `GET` | `/analyzeContour/schema` | Returns the response schema, defaults, and example metadata. |
| `POST` | `/analyzeContour` | Runs contour, terrain, pond, catchment, and runoff analysis. |
| `POST` | `/catchment/analyzeContour` | Compatibility route for the same analysis endpoint. |
| `GET` / `POST` | `/IP/search/` | **Location Recommendation API** — finds 10 closest locations by grid distance. |

### `POST /analyzeContour`

The endpoint accepts `multipart/form-data`.

| Field | Type | Default | Description |
|---|---:|---:|---|
| `file` or `contour_map` | File | — | Optional `.kml` or `.kmz` contour file. |
| `selected_latitude` | float | — | Selected map centre latitude. |
| `selected_longitude` | float | — | Selected map centre longitude. |
| `selected_radius_m` | float | — | Selected radius, from 25 to 5000 m. |
| `dem_resolution_m` | float | Auto | DEM cell resolution, 0.5–100 m. |
| `sample_spacing_m` | float | Auto | Contour sampling interval, 0.5–100 m. |
| `ideal_slope_deg` | float | `3.0` | Ideal pond-site slope. |
| `max_slope_deg` | float | `8.0` | Maximum acceptable slope. Must exceed the ideal slope. |
| `neighborhood_radius_m` | float | Auto | Local terrain-analysis radius. |
| `weight_slope` | float | `0.35` | Slope score weight. |
| `weight_depression` | float | `0.35` | Depression score weight. |
| `weight_twi` | float | `0.30` | Wetness score weight. |
| `suitability_threshold` | float | `60.0` | Minimum candidate score. |
| `min_pond_area_m2` | float | `200.0` | Minimum candidate footprint. |
| `max_pond_area_m2` | float | — | Optional maximum footprint. |
| `max_candidate_sites` | integer | `5` | Number of ranked alternatives, 1–20. |
| `max_elongation_ratio` | float | `3.5` | Shape filter for narrow corridors. |
| `min_pond_width_m` | float | Auto | Minimum usable pond width. |
| `pond_design_depth_m` | float | `2.0` | Design depth for storage estimation. |
| `snap_radius_m` | float | `25.0` | Pour-point stream snapping radius. |
| `use_pysheds` | boolean | `true` | Try Pysheds before native D8 routing. |
| `design_rainfall_mm` | float | `100.0` | 24-hour design rainfall. |
| `curve_number` | float | `75.0` | SCS-CN value, 30–98. |

#### Upload-based request

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "selected_latitude=21.2517" \
  -F "selected_longitude=81.2970" \
  -F "selected_radius_m=250" \
  -F "dem_resolution_m=5"
```

#### Map-only fallback request

When no file is supplied, the request must include all three selected-area
fields. The server then uses the bundled `contours_1m.kml` dataset:

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour" \
  -F "selected_latitude=21.2517" \
  -F "selected_longitude=81.2970" \
  -F "selected_radius_m=250"
```

#### Response shape

The response is a `CatchmentResponse` object:

```json
{
  "status": "success",
  "message": "Contour analysis and pond catchment delineation completed successfully.",
  "input_summary": {
    "num_contours": 34,
    "elevation_min": 420.0,
    "elevation_max": 480.0,
    "dem_resolution_m": 5.0,
    "utm_crs": "EPSG:32644"
  },
  "selected_area": {
    "latitude": 21.2517,
    "longitude": 81.297,
    "radius_m": 250.0,
    "area_m2": 196349.5
  },
  "recommended_site": {
    "site_id": "site_1",
    "rank": 1,
    "latitude": 21.2518,
    "longitude": 81.2971,
    "suitability_score": 87.4,
    "area_m2": 1250.0,
    "storage_capacity_m3": 1875.0
  },
  "alternative_sites": [],
  "catchment": {
    "area_m2": 42000.0,
    "area_hectares": 4.2,
    "estimated_runoff_volume_m3": 7380.0,
    "boundary_geojson": {
      "type": "FeatureCollection",
      "features": []
    }
  },
  "processing_notes": []
}
```

The numeric values above are illustrative. Actual values depend on the
uploaded or bundled contours, selected area, DEM resolution, rainfall, and
Curve Number.

---

## Location Recommendation API

### Overview

The Location Recommendation API (`/IP/search/`) recommends the 10 closest
locations from a 10,000-node dataset using shortest-path grid routing. It
accepts latitude, longitude, category, search radius, and optional road
linkage, then returns location IDs ranked by traversal distance.

### Key features

- **Two-stage filtering**: Circular radius for eligibility, shortest-path for ranking.
- **Grid routing**: Supports default 4-neighbor grid topology or custom road linkage.
- **Efficient pathfinding**: Dijkstra's algorithm with O((V+E) log V) complexity.
- **Case-insensitive category**: Bank, cafe, hospital, park, pharmacy, restaurant, school, store.

### Endpoint: `GET /IP/search/` or `POST /IP/search/`

#### Query parameters (GET)

| Parameter | Type | Required | Description |
|---|---|---|---|
| `lat` | float | Yes | Current latitude (0.0–1.0). |
| `long` | float | Yes | Current longitude (0.0–1.0). |
| `cat` | string | Yes | Category filter (case-insensitive). |
| `rad` | float | Yes | Search radius (Euclidean, ≥ 0). |
| `link` | file | No | Optional road linkage file (space-separated node pairs). |

#### Form fields (POST multipart)

Same as query parameters above, but `link` is an uploaded file.

#### Example requests

**GET:**
```bash
curl "http://127.0.0.1:8000/IP/search/?lat=0.5&long=0.5&cat=bank&rad=0.1"
```

**POST with multipart:**
```bash
curl -X POST "http://127.0.0.1:8000/IP/search/" \
  -F "lat=0.5" \
  -F "long=0.5" \
  -F "cat=bank" \
  -F "rad=0.1"
```

**POST with custom linkage:**
```bash
curl -X POST "http://127.0.0.1:8000/IP/search/" \
  -F "lat=0.5" \
  -F "long=0.5" \
  -F "cat=bank" \
  -F "rad=0.1" \
  -F "link=@roads.txt"
```

#### Response

```json
{
  "status": "success",
  "locations": [
    "loc_1234",
    "loc_5678",
    ...
  ],
  "count": 10
}
```

#### Linkage file format

Space-separated node pairs, one per line. Lines starting with `#` are ignored.

```text
# Road network for grid
0 1
1 2
0 10
# ... additional edges
```

### Algorithm

1. **Load CSV**: Cache locations with ID, latitude, longitude, category.
2. **Construct graph**: Use provided linkage or default 4-neighbor grid.
3. **Start node**: Nearest grid node to query point.
4. **Dijkstra SSSP**: Compute shortest-path distances from start node.
5. **Filter**: Keep locations matching category AND within circular radius.
6. **Rank & return**: Sort by path distance, return top 10.

### Performance

- Query latency: 1–5 ms (100 locations) to 50–200 ms (100,000+ locations).
- Memory: ~2 MB for 10,000 locations.
- Scales efficiently with K-D tree radius filtering for large datasets.

For more details, see [LOCATION_API_REPORT.md](./LOCATION_API_REPORT.md) and
[LOCATION_API_QUICKSTART.md](./LOCATION_API_QUICKSTART.md).

---

## Configuration

### Frontend

Create `frontend/.env`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

The frontend client uses a three-minute request timeout because interpolation
and hydrological routing can be compute-intensive.

### Backend CORS

The backend uses an explicit origin allow-list. By default:

```text
http://localhost:5173,http://127.0.0.1:5173
```

For a deployed frontend, set:

```bash
export JALASETU_CORS_ORIGINS="https://frontend.example.com"
```

Multiple origins are comma-separated:

```bash
export JALASETU_CORS_ORIGINS="https://frontend.example.com,https://staging.example.com"
```

Do not use `*` with credentialed production deployments. Keep the list limited
to trusted frontend origins.

---

## Testing

Run the complete backend suite from the repository root:

```bash
source venv/bin/activate
pytest -q
```

Run only API route tests:

```bash
pytest tests/test_api_routes.py -q
```

Build the frontend:

```bash
cd frontend
npm run build
```

The test suite covers:

- Health and schema endpoints.
- KML/KMZ parsing and elevation extraction.
- UTM reprojection and DEM interpolation.
- Slope, depression, and suitability calculations.
- Pond candidate geometry and filtering.
- Pysheds/native D8 catchment delineation.
- API validation and selected-area metadata.
- Map-only bundled-contour fallback analysis.
- End-to-end response schema and geometry checks.

Before submitting changes, also run:

```bash
git diff --check
```

---

## Distributed services

The optional `distributed/` package separates the pipeline into stages:

| Service | Default port | Responsibility |
|---|---:|---|
| `distributed.sys2` | `3002` | Parse contours and build the DEM. |
| `distributed.sys3` | `3003` | Analyze terrain and rank pond sites. |
| `distributed.sys4` | `3000` | Gateway/orchestration service and catchment stage. |

For a local distributed smoke test:

```bash
./scripts/run_distributed.sh
```

The script starts `sys2` and `sys3`, then runs `sys4`. Configuration can be
overridden with:

```bash
JALASETU_SYS2_URL=http://127.0.0.1:3002 \
JALASETU_SYS3_URL=http://127.0.0.1:3003 \
JALASETU_PORT=3000 \
./scripts/run_distributed.sh
```

The standard frontend is configured for the FastAPI service on port 8000; point
`VITE_API_BASE_URL` at a compatible gateway if using the distributed deployment.

---

## Deployment

### Backend

Run the ASGI application behind a process manager or reverse proxy:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

For production:

- Use Linux containers or a Linux VM with GDAL, GEOS, and PROJ runtime support.
- Set explicit `JALASETU_CORS_ORIGINS`.
- Configure a reverse proxy upload limit appropriate for contour files.
- Set upstream and proxy timeouts to at least 60–180 seconds.
- Allocate sufficient memory for DEM interpolation; large, dense contours can
  require more than 1 GB.
- Keep temporary uploads on local ephemeral storage or a managed temporary
  volume.
- Monitor request duration, memory, failed analyses, and fallback rates.

The repository includes [`scripts/deploy_to_sys4.sh`](./scripts/deploy_to_sys4.sh)
for a systemd-based deployment on a Linux host. Review it before use because it
updates the target checkout and requires administrative privileges.

### Verified four-node deployment

The distributed deployment has been deployed and verified end-to-end across
four cluster nodes. The public application entry point is:

**<http://10.1.75.51:3204/>**

This address is the single public entry point exposed by the Nginx reverse
proxy on `sys4`.

#### Cluster topology

| Node | Internal address | Role | Service port |
|---|---|---|---:|
| `sys1` | `172.17.0.2` | React/Vite static frontend served by the lightweight SPA server | `3000` |
| `sys2` | `172.17.0.3` | KML/KMZ parsing and DEM generation | `3000` |
| `sys3` | `172.17.0.4` | Terrain derivatives and pond-site ranking | `3000` |
| `sys4` | `172.17.0.5` | Gateway, catchment delineation, runoff response, and Nginx entry point | `3000`, `3204` |

Administrative SSH access was verified through the host's mapped ports
`2201`–`2204`, corresponding to `sys1`–`sys4`. The deployment was started
from a clean process state; previous Python, Node, Vite, Uvicorn, Flask, and
SPA-server processes were stopped before verification.

#### Request routing

Nginx on `sys4` routes requests as follows:

| Request path | Upstream | Purpose |
|---|---|---|
| `/` and static assets | `172.17.0.2:3000` | Serve the frontend application |
| `/v1/parse`, `/v1/dem`, `/v1/prepare` | `172.17.0.3:3000` | Forward parsing and DEM stages to `sys2` |
| `/v1/terrain`, `/v1/rank` | `172.17.0.4:3000` | Forward terrain and ranking stages to `sys3` |
| `/analyzeContour`, `/findCatchment`, `/health` | `127.0.0.1:8000` | Handle gateway analysis and operational endpoints on `sys4` |

The frontend was built with `VITE_API_BASE_URL=""`, so browser requests use
same-origin relative paths through the public gateway. This avoids exposing
internal node addresses to users and removes the need for browser-side
cross-origin routing in the deployed configuration.

#### Deployment verification

The following checks were completed:

1. Nginx configuration validation passed with `nginx -t`.
2. The public URL returned `HTTP/1.1 200 OK` with the frontend HTML shell.
3. The real 6.7 MB `contours_1m.kml` file was uploaded from outside the
   cluster to `http://10.1.75.51:3204/analyzeContour`.
4. The complete request finished successfully in **19.06 seconds**.
5. The pipeline parsed **2,711 contours**, generated a **15 m DEM**, computed
   terrain derivatives and MCDM pond ranking, delineated the upstream
   catchment, and returned GeoJSON site and catchment boundaries.
6. The returned catchment area was approximately **0.61 hectares**.
7. All stages returned successful health checks before the full-pipeline test.

#### Memory verification

Peak observed resident memory remained below the 500 MB per-node limit during
the full-load check:

| Node | Observed RSS |
|---|---:|
| `sys1` frontend | approximately 19.9 MB |
| `sys2` parsing/DEM | approximately 241 MB |
| `sys3` terrain/ranking | approximately 361 MB |
| `sys4` gateway/catchment | approximately 295 MB |

No out-of-memory errors were observed. Idle memory on `sys2` and `sys3` was
approximately 166 MB, and the frontend SPA server used approximately 19.9 MB.
These figures are deployment observations for the verified test workload, not
capacity guarantees for arbitrarily large contour files or unrestricted
concurrency.

### Frontend

Build static assets:

```bash
cd frontend
VITE_API_BASE_URL="https://api.example.com" npm run build
```

Serve `frontend/dist/` from a CDN, Nginx, Vercel, Netlify, Cloudflare Pages, or
another static host. Configure SPA fallback to `index.html` where required.

### Deployment checklist

1. Verify `GET /health` returns HTTP 200.
2. Verify the deployed frontend can reach the API without CORS errors.
3. Upload a small KML file and confirm a complete response.
4. Test the map-only fallback inside the bundled contour extent.
5. Confirm pond, catchment, and runoff overlays render.
6. Check reverse-proxy upload and timeout limits.
7. Confirm logs do not expose uploaded file contents or sensitive data.

---

## Performance and scaling

The analysis pipeline is CPU- and memory-intensive. The API executes it in a
threadpool so the FastAPI event loop remains responsive to health checks and
other requests.

For reliable operation:

- Keep DEM resolution proportional to the input extent.
- Cap upload size at the reverse proxy and application boundary.
- Limit concurrent heavy analyses with a queue or worker pool.
- Use multiple API workers for independent requests, subject to available RAM.
- Prefer the native fallback only when Pysheds is unavailable or fails.
- Cache repeated analyses by a content hash and parameter set where appropriate.
- Use the distributed stages when DEM construction, terrain ranking, and
  catchment work need independent scaling.
- Return bounded candidate lists using `max_candidate_sites`.
- Measure p50/p95 latency and peak memory with representative contour files.

The map-only fallback is intentionally a demonstration mode. It reuses the
bundled terrain dataset rather than inventing elevation values from
coordinates, and it reports that choice in `processing_notes`.

---

## Limitations

- Results depend on contour density, elevation labels, vertical interval, and
  geometric quality.
- DEM interpolation can smooth narrow ridges, channels, and local depressions.
- Catchment delineation can be simplified on flat or noisy terrain.
- SCS-CN runoff is a design-storm estimate, not an annual water-balance model.
- Soil infiltration, evaporation, sedimentation, groundwater interaction, and
  detailed embankment design are not fully modeled.
- The bundled fallback dataset is suitable for demonstration and testing, not
  for final site approval.
- A field survey, soil investigation, land-ownership review, and engineering
  validation are required before construction.

### Future improvements

- Rainfall frequency and seasonal time-series integration.
- Soil, land-cover, infiltration, and evapotranspiration layers.
- Cut-and-fill earthwork and embankment design.
- Persistent job queues and progress reporting for very large uploads.
- Authentication, audit logging, and multi-user project management.
- Tile-based or cloud-native terrain processing for regional-scale analysis.

---

## Repository structure

```text
JalaSetu/
├── app/
│   ├── main.py                         # FastAPI entrypoint and CORS
│   ├── models/schemas.py               # Request/response models
│   ├── routers/catchment.py            # Analysis and schema routes
│   ├── services/
│   │   ├── kml_parser.py               # KML/KMZ parsing
│   │   ├── dem_builder.py              # UTM reprojection and DEM creation
│   │   ├── terrain_analysis.py         # Slope, depression, suitability
│   │   ├── pond_site.py                # Candidate extraction and ranking
│   │   ├── catchment_delineation.py   # Flow routing and runoff
│   │   └── pipeline.py                 # End-to-end orchestration
│   └── utils/geometry.py               # Geospatial helper functions
├── distributed/
│   ├── sys2.py                         # DEM stage
│   ├── sys3.py                         # Terrain/site stage
│   ├── sys4.py                         # Gateway/catchment stage
│   └── stage_payloads.py               # Serializable stage contracts
├── frontend/
│   ├── src/App.jsx                     # Application state and workflow
│   ├── src/api/catchmentApi.js         # Axios API client
│   └── src/components/                 # Upload, map, result panels
├── scripts/
│   ├── demo_run.py                     # Direct/API demonstration runner
│   ├── run_distributed.sh              # Local distributed smoke test
│   └── deploy_to_sys4.sh               # Linux systemd deployment helper
├── tests/                              # Backend test suite
├── contours_1m.kml                     # Bundled demonstration contours
├── requirements.txt                    # Python dependencies
└── main.md                             # Project report source
```

---

## Engineering notes

- Keep uploaded files temporary and delete them after processing.
- Validate file suffixes, archive integrity, XML structure, and numeric bounds
  before starting expensive processing.
- Do not expose internal filesystem paths in API errors.
- Treat `processing_notes` as part of the user-facing explainability layer.
- Preserve GeoJSON in EPSG:4326 for browser map interoperability.
- Use metric projected coordinates internally for distances, areas, and raster
  calculations.
- Validate all production changes with the backend tests, frontend build, and
  `git diff --check`.

---

## License and project status

This repository is an academic/project implementation intended for
demonstration and preliminary planning. Add the applicable project license
before distributing it as a public product.
