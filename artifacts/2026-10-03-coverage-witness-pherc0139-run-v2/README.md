# PHerc0139 coverage-witness deletion observation v2

**Research-only observation for issue #151.**

The v1 result remains a formal FAIL because its largest deletion consumed its
entire evaluation window. V2 is bound to the separately merged protocol:

`artifacts/2026-10-03-coverage-witness-pherc0139-prereg-v2/spec.json`

The only scientific change from v1 is the evaluation window: 51×51 instead of
41×41 material-grid vertices. The exact source, six centers, 21/31/41 deletion
sizes, witness association, distance tolerances, synthetic parallel
substitution, and all decision thresholds are unchanged.

The measured result is create-only. A PASS still does not promote a production
coverage-witness diagnostic; it only clears the deletion-calibration gate for a
separately preregistered unconditioned Stage B.
