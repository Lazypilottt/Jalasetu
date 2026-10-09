# Lab7 API Stress-Test Report

Date: 2026-10-09

Endpoint tested:

```text
http://127.0.0.1:8104/IP/search/
```

The same build was deployed to:

| System | Port |
| --- | ---: |
| sys1 | 8101 |
| sys2 | 8102 |
| sys3 | 8103 |
| sys4 | 8104 |

The public sys4 route was also checked through port `3204`.

## Test environment

- Dataset: 10,000 locations
- Grid: 100 x 100
- Categories: eight
- Ranking: Dijkstra traversal distance
- Eligibility: circular Euclidean radius
- Runtime: deployed FastAPI/Uvicorn service
- Dataset rows: 10,000 plus the CSV header
- Existing JalaSetu terrain services were not stopped or modified

## Functional and boundary tests

| Case | Expected behavior | Observed |
| --- | --- | --- |
| Normal GET search | Ten IDs | HTTP 200, ten IDs |
| Zero radius at an exact location | Only exact eligible matches | HTTP 200, one ID |
| Very large radius (`999999`) | Bounded search over the dataset | HTTP 200, ten IDs |
| Coordinates far outside the dataset | No crash or unbounded scan | HTTP 200, ten IDs |
| Unknown category | Empty result | HTTP 200, `[]` |
| Empty category | Validation error | HTTP 422 |
| Negative radius | Validation error | HTTP 422 |
| `NaN` latitude | Validation error | HTTP 422 |
| Infinite radius | Validation error | HTTP 422 |
| Missing query field | Validation error | HTTP 422 |
| Malformed linkage line | Client error | HTTP 400 |
| Small custom linkage file | Road graph used | HTTP 200 |
| 9,999-line linkage file | Large graph accepted | HTTP 200 |
| POST multipart request | Same result contract as GET | Passed |

## Correctness checks

The local oracle suite compares the optimized service logic with full Dijkstra
traversal on randomized queries.

```text
4 passed in 1.73s
```

The suite includes:

- 80 randomized hidden-query-style inputs.
- At least 50 randomized cases with ten or more eligible locations.
- Exact traversal-distance ordering and ID tie-breaking.
- Zero-based numeric linkage parsing.
- GET/POST result equivalence.
- Extreme-radius and non-finite-number validation.

The deployed nodes returned the same result for the cross-node query:

```text
lat=0.37, long=0.63, cat=hospital, rad=0.3
```

```json
["3562","3565","3660","3659","3966","3758","3365","3163","3467","4362"]
```

## Custom linkage measurements

The following requests were executed against sys4:

| Linkage input | Status | Time |
| --- | ---: | ---: |
| Two-link file | 200 | 0.057 s |
| 9,999-link file, cached | 200 | 0.014 s |
| 9,999-link file, cold parse | 200 | 0.111 s |

Coordinate linkage files use four space-separated values per line:

```text
Longitude_A Latitude_A Longitude_B Latitude_B
```

The supplied `link.txt` sample was parsed successfully with 14,800 lines and
14,800 undirected grid edges.

The cold parse measurement included parsing and caching a new 9,999-line
undirected graph.

## Concurrent-load measurements

The service was tested with 20 concurrent clients:

| Requests | Concurrency | Successful | Failed | Wall time |
| ---: | ---: | ---: | ---: | ---: |
| 200 | 20 | 200 | 0 | 8 s |
| 100 | 20 | 100 | 0 | 4 s |

For the 100-request latency sample:

```text
Median: 0.694272 s
95th percentile: 0.881188 s
Maximum: 1.085748 s
```

The measured concurrent latency is end-to-end process latency under the
deployed Uvicorn process, not the warm single-call algorithm latency.

## Resource observations

During the load test on sys4:

```text
Resident memory: approximately 73–77 MB
Virtual memory: approximately 970–995 MB
```

The process remained alive and responsive after the concurrent run. No
connection failures, 5xx responses, or process exits were observed after the
hardening changes.

## Defects found and corrected during testing

The first extreme-value run exposed two issues:

1. A very large radius produced an impractically large bucket-coordinate loop.
2. `rad=inf` reached the search implementation and returned HTTP 500.

The implementation was corrected to:

- Clamp bucket iteration to the dataset's latitude and longitude bucket range.
- Reject non-finite `lat`, `long`, and `rad` values with HTTP 422.

The regression suite and the deployed extreme-value tests passed after these
changes.

## Remaining evaluation considerations

- The available attachment in this workspace contains 10,000 rows. A
  1,000,000-row attachment was not available for this run.
- The service keeps the dataset and indexes in memory, which is appropriate
  for the tested dataset and the stated 512 GB machines.
- For a true 1,000,000-row certification, startup time, resident memory,
  linkage size, and concurrent throughput should be measured again with the
  supplied million-row file.
- The public route was verified locally on sys4 through Nginx. Access from
  outside the cluster depends on the network path and firewall rules.

## Conclusion

The API passed functional, randomized correctness, malformed-input,
large-radius, large-linkage, cross-node consistency, and concurrent-load
tests. The previously discovered unbounded-radius and non-finite-input
failures were fixed before the final measurements.
