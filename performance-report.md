# Performance report

**Status: NOT MEASURED on representative hardware.** The free pilot can run locally, but no kiosk fleet, representative employee set, or production-class host benchmark has been run. No RAM, CPU, latency percentile, throughput, or queue-capacity values are claimed.

Before unattended or payroll-affecting use, benchmark the AI service and Odoo together:

1. Idle service after model load.
2. Cold and warm detection/matching for five prompted frames.
3. One kiosk under normal use.
4. Rapid retries until per-device throttling.
5. Concurrent kiosks.
6. Odoo requests while CPU-bound inference is active.
7. Service timeout, restart, invalid model, database unavailable, and saturation.

Record idle/peak RSS, CPU, request success/failure rates, P50/P95/P99 latency, saturation response, and Odoo p50/p95 change against the same baseline. Use a synthetic or explicitly acknowledged test set; do not benchmark with unapproved employee captures.
