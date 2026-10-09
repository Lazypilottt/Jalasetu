# Lab7 Resiliency Design

## Process recovery

Each lab7 node is managed by Supervisor rather than an ad-hoc background
process:

```text
/etc/supervisor/conf.d/lab7-location-api.conf
```

The service configuration uses:

- `autostart=true`
- `autorestart=true`
- `startsecs=5`
- `startretries=10`
- `stopasgroup=true`
- `killasgroup=true`
- bounded log rotation

Each node runs two Uvicorn worker processes with a 2,048-connection accept
backlog and a 64-connection per-worker concurrency limit. The workers are
owned by Supervisor, so a worker or master failure does not require manual
intervention.

| Node | Port |
| --- | ---: |
| sys1 | 8101 |
| sys2 | 8102 |
| sys3 | 8103 |
| sys4 | 8104 |

The sys4 Nginx route continues to expose the service through port 3204.

## Application safeguards

The API now:

- Rejects non-finite latitude, longitude, and radius values with HTTP 422.
- Bounds spatial bucket iteration to the dataset extent.
- Rejects linkage uploads larger than 64 MiB with HTTP 413.
- Keeps only two parsed custom graphs in the process cache, limiting retained
  memory from repeated unique linkage uploads.
- Returns explicit 400/422/413 responses for malformed input instead of
  silently returning a success-shaped fallback.

The API does not fabricate recommendations when a request is invalid or a
custom road graph is malformed. This preserves evaluation correctness. Process
recovery is handled by Supervisor, while valid requests continue to use the
exact radius and traversal-distance rules.

## Recovery verification

The supervised sys4 Uvicorn master was terminated deliberately during testing.
Supervisor started a replacement:

```text
before: 1830340
after:  1830382
status: RUNNING
```

The replacement passed `/health` immediately after recovery.

The local regression suite passed after the hardening changes:

```text
5 passed in 1.87s
```

All four nodes returned the same ten IDs for the cross-node validation query.

## Operational limitation

The concurrency limit intentionally bounds work rather than allowing
unlimited memory growth. During a sudden surge beyond the configured worker
capacity, Uvicorn may reject excess connections rather than allowing the
process to become unresponsive. Supervisor then provides process-level
recovery if a worker or master exits.

For a larger production deployment, the next step would be multiple sys4
gateway instances behind an external load balancer. The current design is
appropriate for the four-node assignment deployment and preserves the
existing JalaSetu terrain services.
