# Distributed deployment

JalaSetu can be run as three small services without changing the existing
FastAPI application:

| Service | Port | Responsibility |
| --- | ---: | --- |
| `sys2` | 3000 (public mapping: 3202) | Parse KML/KMZ and build a serializable DEM |
| `sys3` | 3000 (public mapping: 3203) | Terrain derivatives and pond site ranking |
| `sys4` | 3000 (public mapping: 3204) | Public gateway and catchment delineation |

Start locally with:

```bash
./scripts/run_distributed.sh
```

For the three-machine deployment, sys4 must call the public mappings for the
worker machines: set `JALASETU_SYS2_URL=http://<sys2-host>:3202` and
`JALASETU_SYS3_URL=http://<sys3-host>:3203` (and optionally
`JALASETU_REQUEST_TIMEOUT=120`) in the sys4 environment. Stage payloads are
JSON documents; raster arrays are compressed-independent base64 NumPy `.npy`
values and contain their shape, dtype, CRS, affine transform, and bounds.

The service endpoints are `/health` and the versioned stage endpoints
`/v1/prepare` (sys2) and `/v1/analyze` (sys3). The sys4 public endpoint is
`POST /analyzeContour`, matching the FastAPI API's form fields and aliases.
