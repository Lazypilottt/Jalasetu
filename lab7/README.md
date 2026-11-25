# Lab 7 — Proximity Search API

Recommends the ten closest locations of a requested category from a
10,000-point grid. Locations are first filtered by circular (Euclidean)
radius, then ranked by the shortest traversal distance along the grid or
along a supplied road network.

**Public endpoint:** <http://10.1.75.51:3204/IP/search/>
**Health:** <http://10.1.75.51:3204/IP/health>
(The public address is on the institute network; use the VPN off campus.)

## API

`GET /IP/search/` (query string) or `POST /IP/search/` (multipart form; use
POST to upload a road network).

| Field | Type | Meaning |
|---|---|---|
| `lat` | float | Current latitude |
| `long` | float | Current longitude |
| `cat` | text | Category (case-insensitive), e.g. `bank`, `cafe`, `hospital` |
| `rad` | float ≥ 0 | Circular eligibility radius |
| `link` | file, optional | Road links, one per line: `Longitude_A Latitude_A Longitude_B Latitude_B` |

The response is a JSON list of up to ten location IDs, nearest first:

```bash
curl "http://10.1.75.51:3204/IP/search/?lat=0.5&long=0.5&cat=bank&rad=0.1"
# ["4850","4948","4947","4648","4753","5349","4955","4451","5348","5449"]

curl -X POST "http://10.1.75.51:3204/IP/search/" \
  -F "lat=0.5" -F "long=0.5" -F "cat=bank" -F "rad=0.8" -F "link=@link.txt"
```

| Situation | Response |
|---|---|
| Valid request | `200` with up to ten IDs (fewer if fewer locations qualify, `[]` if none) |
| Missing field, negative radius, empty category | `422` |
| `NaN` or infinite coordinates or radius | `422` |
| Malformed road-link file | `400` |
| Road-link file larger than 64 MiB | `413` |

## How it works

1. **Load once.** `locations.csv` is read at start-up. Indexes map IDs, grid
   positions and latitude/longitude values to rows, and points are placed in
   spatial buckets of 8 × 8 grid cells.
2. **Filter.** Only buckets overlapping the query circle (clamped to the
   dataset) are scanned; a location qualifies if its category matches and its
   Euclidean distance is within `rad`.
3. **Rank.** Dijkstra's algorithm runs from the grid node nearest the query
   point, over the 4-neighbour grid (no diagonals) or over the uploaded road
   links. It stops as soon as ten qualifying locations are settled and the
   frontier passes the tenth distance. Ties are broken by location ID.

**Complexity.** With V = 10,000 nodes and E ≈ 19,800 grid edges (14,800 in
the sample road file), filtering costs O(b + c) for b scanned bucket points
and c candidates, and Dijkstra costs O((V + E) log V) in the worst case. In
practice it explores only the neighbourhood up to the tenth result. A road
file is parsed in O(L) for L lines, and the two most recent parsed graphs are
cached. Memory is O(V + E).

## Deployment

| Node | Port | Role |
|---|---:|---|
| sys1 | 8101 | API instance |
| sys2 | 8102 | API instance |
| sys3 | 8103 | API instance |
| sys4 | 8104 | API instance, plus the Nginx entry point on `:3204` |

- **Load balancing.** Nginx on sys4 balances `/IP/search/` across all four
  instances (`least_conn`). A failed or overloaded instance is skipped, and the
  request is retried on another instance (up to 3 tries).
- **Supervision.** Each instance runs under Supervisor (`autostart`,
  `autorestart`, process-group stop, rotated logs) through `start_lab7.sh`,
  which also clears processes left behind by a hard kill so a restart can
  always bind its port.
- **Bounded work.** One uvicorn worker per node (about 65 MB) with a
  64-connection limit and a 2,048 backlog. Nginx allows 150 requests/s per
  client with a queued burst of 400.
- **Isolated runtime.** Each node has its own virtualenv in `~/lab7/venv`.

Deploy or update all four nodes from this folder:

```bash
./deploy_lab7.sh            # or: ./deploy_lab7.sh sys2 sys4
```

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8100
```

Docker (`docker-compose.yml`) runs the same API behind an Nginx gateway on a
single machine.

## Tests

```bash
pytest test_api.py
```

The six tests are:
- Ranking checked against a full Dijkstra oracle on random queries.
- Both road-link formats parse correctly.
- GET and POST return identical results.
- Extreme and non-finite inputs are handled.
- The upload size limit is enforced.

See [LAB7_RESILIENCY.md](LAB7_RESILIENCY.md) and
[API_STRESS_TEST_REPORT.md](API_STRESS_TEST_REPORT.md) for the cluster
measurements.
