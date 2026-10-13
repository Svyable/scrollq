# Independent mesh-review recruitment gate — October 13, 2026

**State: prepared, NOT SENT.** This is the next evidence step for ScrolIQ's October 31 Vesuvius Challenge Progress Prize. It is not an independent review, a prize submission, a recruitment authorization, or a promise to pay.

## Why it matters

The [official Progress Prize](https://scrollprize.org/prizes) favors analytic tools that expose actionable real-scroll failure cases and show actual use. ScrolIQ's [frozen Mesh IQ sample](../artifacts/2026-10-01-mesh-review-sample/README.md) has 54 candidate surfaces and **no human labels yet**. Another diagnostic would not close this gap; an independent VC3D review might.

The [review sheet](../artifacts/2026-10-01-mesh-review-sample/review-sheet.csv) was fetched and checked for 54 rows and empty label fields on October 13. Its frozen manifest records SHA-256 `5a5284efce7d09844c91c8f99d1d0b2f06fce877dd1728c2c3f92ab5c41a0d8a`. That SHA is supplied by the committed manifest; the existing packet builder checks it when executed.

## Create the key-free packet

```bash
python bin/mesh_review_packet.py --out mesh-review-2026-10-13.zip
unzip -l mesh-review-2026-10-13.zip
```

The builder checks the frozen review-sheet hash and includes only `review-sheet.csv` and `REVIEW.md`. **Never send** `key.json`, finding kinds, source audit reports, or `flagged.tsv` to a reviewer before labels are returned. The source is public, so blinding is procedural; debug filenames may reveal controls.

## Reviewer invitation (DRAFT ONLY)

I'm seeking an independent reviewer familiar with VC3D and Herculaneum CT/mesh inspection for a pre-registered, bounded review. The key-free packet has 54 randomized candidate surfaces, with exact mesh URLs and CT roots. For each, please mark `defect`, `not_defect`, or `unclear` and add a short note where useful. You are not being asked to endorse ScrolIQ or recommend it for a prize. We want to know whether its flags distinguish genuine mesh problems from clean-segment controls.

Please do not consult ScrolIQ's source findings, key, or prior audit reports until you have returned the completed sheet. If a CT or mesh cannot be inspected, mark `unclear` rather than replacing the row. We would agree on scope, timing, any compensation, attribution and screenshot-sharing permissions **before** review starts. Nothing has been offered or committed.

## After an explicitly approved reviewer engagement

1. Send only the generated packet and the [reviewer handoff](mesh-review-handoff.md); record the reviewer's prior exposure to ScrolIQ results and VC3D version.
2. Preserve all 54 rows and all `unclear` cases. Do not replace samples or reveal hidden strata mid-review.
3. Hash the returned CSV before unblinding. Apply the frozen [scoring protocol](mesh-review-protocol.md) with `bin/mesh_review_score.py`.
4. Calibration requires at least 3/4 debug controls labeled defect. Enrichment requires the Wilson 95% lower bound for flagged precision to exceed the upper bound for the clean defect rate. If the rule fails, report the failure rather than altering the experiment.
5. Do not claim an independently validated detector, community adoption, or downstream unwrapping improvement before evidence exists. No submission or outreach without Sven's approval.

**Financial stop rule:** The screening model's +$277.50 net EV for the monthly prize does not include review costs. At an assumed $35/hour, roughly eight additional hours of unpaid pursuit effort would consume that modeled EV. Keep any recruitment/review effort bounded; prize money is discretionary and never guaranteed to ScrolIQ.
