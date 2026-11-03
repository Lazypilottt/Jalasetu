# Distributed deployment

The backend runs on four nodes, `sys1`–`sys4`, each sized at **500 MB of RAM
and 1.5 GB of storage**. Every node does backend work. Heavy stages are not
pinned to a node: the sys4 gateway places each one on whichever node has
capacity at that moment.

| Node | Module | Role | Heavy stages |
| --- | --- | --- | --- |
| `sys1` | `distributed.sys1` | Edge: built SPA, climate/rainfall API (also used by the gateway for every analysis), capacity reporting. Standard library only. | none |
| `sys2` | `distributed.sys2` | Stage worker. Wins ties for parse + DEM and catchment. | all |
| `sys3` | `distributed.sys3` | Stage worker. Wins ties for terrain + ranking. | all |
| `sys4` | `distributed.sys4` | Gateway: job queue, scheduler, Nginx entry point; runs a stage itself only when the workers are busy and it has headroom. | all (fallback) |

sys1 gets no heavy stages because it also hosts the OpenTelemetry backends
(Tempo, Loki, Prometheus, the collector). They hold its working set near
480 MB of the 512 MiB cgroup and take 3.6 GB on disk, and sys1 has no
virtualenv. Its edge service needs about 20–35 MB.

## Pipeline stages

| Stage | Endpoint on a worker | Payload in → out |
| --- | --- | --- |
| `prepare` | `POST /v1/prepare` | KML/KMZ bytes → contours + DEM |
| `analyze` | `POST /v1/analyze` | DEM → terrain rasters + ranked sites |
| `catchment` | `POST /v1/catchment` | terrain + ranking → catchment + SCS-CN runoff |
| `climate` | `GET /v1/rainfall` on sys1 | site lat/lon → rainfall regime |

Payloads are JSON. Rasters are base64 `.npy` arrays carrying their shape,
dtype, CRS, affine transform and bounds. Workers also keep the finer-grained
`/v1/parse`, `/v1/dem`, `/v1/terrain` and `/v1/rank` endpoints.

## How placement works

1. **Measure.** `distributed/capacity.py` reads the cgroup working set
   (`memory.current - inactive_file`), which is the figure the OOM killer uses.
   The budget is `min(cgroup limit, JALASETU_MEMORY_BUDGET_MB=500)`.
2. **Admit.** A worker accepts a heavy stage only if a slot is free
   (`JALASETU_WORKER_SLOTS=1`) and headroom is at least
   `JALASETU_STAGE_RESERVE_MB=150`. That is the measured peak growth of one
   stage above an idle worker. Otherwise it answers `503` with `Retry-After`.
   After each stage it runs `gc.collect()` and `malloc_trim(0)`, so RSS does not
   creep up over many requests.
3. **Rank.** `distributed/scheduler.py` probes every node's `/health`
   (cached for 2 s) and orders eligible nodes by: accepting work, fewest stages
   in flight (counting dispatches the gateway has already sent), stage affinity,
   then most memory headroom. The gateway itself goes last on ties.
4. **Fall through.** A busy node is skipped for the next one. If every
   reachable node is busy, the stage waits, with backoff, up to
   `JALASETU_QUEUE_TIMEOUT=90` s, then fails with 503. It is never forced onto a
   saturated node. Only when no worker is reachable at all does the gateway run
   the stage itself regardless of headroom (the original fail-over behaviour).
   A worker's `4xx` means the input is bad, so that error is returned
   immediately rather than retried elsewhere.

The gateway runs at most `JALASETU_MAX_ACTIVE_JOBS=2` analyses at a time and
queues `JALASETU_MAX_QUEUED_JOBS=6` more. Waiting uploads are capped at
`JALASETU_MAX_QUEUED_MB=64` in total, because they sit in the gateway's own
500 MB.

## Gateway API (sys4)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/jobs` | Submit an analysis (same form fields as `/analyzeContour`); returns `202` with `poll_url`. |
| `GET` | `/v1/jobs/<id>` | `state`, current `stage` and `node`, completed `stages`, and `result` when done. |
| `POST` | `/analyzeContour`, `/findCatchment` | Synchronous analysis; shares the job queue's limits. |
| `GET` | `/v1/cluster` | Live per-node memory, storage, slots and reachability (drives the frontend's cluster panel). |
| `GET` | `/health` | Gateway capacity and queue stats. |

Every successful result carries `execution.stages`: the node, mode and
duration of each stage. A request without a file must include
`selected_latitude`, `selected_longitude` and `selected_radius_m` to use the
bundled contours. Otherwise the gateway answers `422`, matching the FastAPI app.

## Running it

Local, four processes:

```bash
./scripts/run_distributed.sh   # sys1 :3001, sys2 :3002, sys3 :3003, gateway :3000
cd frontend && VITE_API_BASE_URL=http://127.0.0.1:3000 npm run dev
```

Docker, each container capped at 500 MB with no swap:

```bash
(cd frontend && VITE_API_BASE_URL="" npm run build)
docker compose -f docker-compose.distributed.yml up --build
```

Cluster (dry run first; it prints every command):

```bash
scripts/deploy_cluster.sh                  # dry run
scripts/deploy_cluster.sh --apply          # rolling: sys2, sys3, sys1, sys4
scripts/deploy_cluster.sh --apply --prune  # also free disk to fit 1.5 GB
```

The deploy installs `requirements-runtime.txt` (no FastAPI, tests or
matplotlib) and the per-node supervisor programs in `deploy/supervisor/`. Those
programs set `MALLOC_ARENA_MAX=2` and single-threaded BLAS/numba. The deploy
also installs the Nginx config and restarts the health prober. `--prune`
removes the stale `backend_minimal` tree (about 1 GB on sys2), `.git`
(198 MB), dev-only packages and the pip cache. Each node's `/health` reports
its deployment footprint against the 1.5 GB budget.
