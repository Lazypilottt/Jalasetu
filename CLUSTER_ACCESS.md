# Cluster access

Verified 2026-09-28 from the deployment host. Use the configured `sys1`–`sys4`
SSH aliases in `~/.ssh/config` so the existing key and jump settings are used.

| Node | Working access path | Notes |
|---|---|---|
| `sys1` (`172.17.0.2`) | `ssh sys1` via `sys2` | Public port 2201 is unreliable; do not depend on it. |
| `sys2` (`10.1.75.51`) | `ssh sys2` directly on port 2202 | Working direct entry and jump host. |
| `sys3` (`172.17.0.4`) | `ssh sys3` via `sys2`; direct port 2203 also authenticated in the recent check | Internal jump path is configured and works. |
| `sys4` (`172.17.0.5`) | `ssh sys4` via `sys2` | Public port 2204 is unreliable; do not depend on it. |

The current SSH aliases use `student` and `~/.ssh/chatfat_cluster_ed25519`.
`sys1`, `sys3`, and `sys4` use `ProxyJump sys2`; sys2 connects to
`10.1.75.51:2202`. The internal nodes are on the `172.17.0.0/24` network.

Do not infer that a public SSH port is down from one timeout: the mapped ports
have been intermittent. Recheck public HTTP health separately from SSH health
before making deployment changes. On 2026-09-28, public `/health` timed out
from the host but returned HTTP 200 when queried from sys2; sys4's local
gateway and Nginx health endpoints also returned HTTP 200.
