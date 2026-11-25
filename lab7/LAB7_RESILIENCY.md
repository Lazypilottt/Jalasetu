# Lab7 Resiliency Design

## Load balancing and failover

All four nodes run the API, and Nginx on sys4 spreads `/IP/search/` across
them:

| Node | Port |
| --- | ---: |
| sys1 | 8101 |
| sys2 | 8102 |
| sys3 | 8103 |
| sys4 | 8104 |

```nginx
upstream lab7_api {
    least_conn;
    server 127.0.0.1:8104  max_fails=2 fail_timeout=10s;
    server 172.17.0.2:8101 max_fails=2 fail_timeout=10s;
    server 172.17.0.3:8102 max_fails=2 fail_timeout=10s;
    server 172.17.0.4:8103 max_fails=2 fail_timeout=10s;
}
```

- **Failover.** If an instance refuses a connection, times out, or answers
  502/503 (uvicorn sheds load with 503 at its concurrency limit), the request
  moves to another instance (`proxy_next_upstream`, up to 3 tries). Searches
  are read-only, so POST requests are retried too.
- **Skipping a bad node.** An instance that fails twice is skipped for 10 s.
- **Rate limit.** `/IP/search/` has its own per-client limit of 150 requests/s.
  Bursts of up to 400 requests are queued rather than rejected.
- **Health route.** `GET /IP/health` returns the health of whichever lab7
  instance answers.

The full configuration is in `scripts/nginx_jalasetu_optimized.conf` and
`scripts/nginx_jalasetu_limits.conf` at the repository root.

## Process recovery

Each instance is managed by Supervisor
(`/etc/supervisor/conf.d/lab7-location-api.conf`, installed from
`lab7-supervisor.conf` by `deploy_lab7.sh`):

- `autostart=true`, `autorestart=true`, `startsecs=5`, `startretries=10`
- `stopasgroup=true`, `killasgroup=true`
- rotated logs (20 MB × 5)

Supervisor starts `start_lab7.sh <port>`, which runs uvicorn with one worker,
a 64-connection concurrency limit and a 2,048-connection backlog.

**The port-recovery problem.** Before uvicorn starts, the script checks
whether anything still listens on its port. If the listener belongs to this
service's own virtualenv, it stops that whole process group. Without this
check, a uvicorn master killed with SIGKILL (for example by the OOM killer)
left its workers holding the port, and Supervisor's restarts failed with
"address already in use".

## Memory

The nodes have 512 MiB each and are shared with the JalaSetu services. One
worker per node uses about 61–65 MB. Two workers per node used about 170 MB,
because each worker holds its own copy of the dataset and uvicorn adds a
manager and a resource tracker. Nginx provides the parallelism across the four
nodes instead.

## Application safeguards

- Non-finite latitude, longitude or radius values are rejected with HTTP 422.
- Spatial bucket scans are clamped to the dataset extent, so huge radii stay
  bounded.
- Road-link uploads larger than 64 MiB are rejected with HTTP 413.
- Only the two most recent parsed road graphs are cached.
- Malformed input gets an explicit 400/422/413, never a success-shaped
  fallback.

## Recovery verification (2026-11-25)

The lab7 uvicorn process on one node was killed with SIGKILL one second into
a 20-client, 1,000-request run through the public URL:

```text
1000 requests, 20 clients: codes={200: 1000}
sys2 pid before=747915 after=747959; RUNNING; health 200
```

No request failed: Nginx moved in-flight traffic to the other three nodes,
and Supervisor restarted the killed instance within seconds. Each of the four
nodes was also killed individually and came back `RUNNING` with a healthy
`/health`.

## Operational limitation

Above the configured limits, the API queues and then rejects requests
(429 at Nginx, 503 from uvicorn) instead of letting memory grow without
bound. The single Nginx entry point on sys4 remains a single point of
failure; a larger deployment would add a second gateway behind an external
load balancer.
