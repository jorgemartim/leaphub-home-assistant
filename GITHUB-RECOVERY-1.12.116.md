# GitHub Recovery - Gateway 1.12.116

Published 1.12.115 commit: `ee77a67d3a1db6b1893a5b0940ca1bdfe6444635`.
D1 merged main commit: `6a601c35212e460d9ae1b8e7eda76d98614eb93c`.
D1 functional head: `533ee61fe800bbbe43b0770d66b4590f92f4c562`.
Functional PR: #17.

Scope: per-vehicle window diagnostics with isolated deduplication and legacy
API compatibility.

Publication remains two-phase. config.yaml must stay at 1.12.115 in the staged
release commit. GitHub Actions promotes it to 1.12.116 only after the exact GHCR
image is built, smoke-tested and anonymously readable.

Do not use force-push. Do not change physical payloads, ACK_FIRST, SAFE retry,
mechanical fence, Trips/OCPP, SQLite writer or confirmation cadence in this
release.
