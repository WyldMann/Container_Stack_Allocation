# Raw shifting and lifting CSV import

Select `shifting_summary = "csv"` in `[input.sources]` and configure:

```toml
[csv]
shifting_operations_file = "../data_CY219/shifting_operations.csv"
# Optional historical cutoff. Include the timezone explicitly.
shifting_cutoff = "2026-01-29T00:00:00+07:00"
```

Paths resolve from `input.toml`. The cutoff defaults to recording time. It applies
only to the CSV operations source and does not change `recorded_at`, which records
when the yard metrics were produced. XLSX and SQL remain independently selectable.

Export a UTF-8 CSV with these six uniquely named columns:

```sql
SELECT
    a."DTL_ID",
    a."DOC_ID",
    a."ACTIVITY",
    a."ACTIVITY_DATE_TIME",
    b."KODE_CABANG",
    b."ALAT"
FROM "REPORT"."TBL_INSP_MAPPING_MSA_RECEIVINGDELIVERY_DTL" a
JOIN "REPORT"."TBL_INSP_MAPPING_MSA_RECEIVINGDELIVERY_HDR" b
    ON a."DOC_ID" = b."DOC_ID";
```

Extra uniquely named columns are accepted and ignored. Column names ignore case
and surrounding whitespace. `SELECT *` from this join has duplicate headers and
is rejected as ambiguous; re-export with the explicit columns above. Do not
rename or drop duplicate columns blindly: detail and header values can differ.

The export must contain one row per operation and equipment assignment. Verify
that the header join does not multiply detail rows. The SQL source uses `EXISTS`
and is unaffected by repeated matching headers. The CSV importer counts rows with
a nonempty `DTL_ID`; it does not deduplicate by `DTL_ID`, `DOC_ID`, container, or
whole-row equality because those have not been established as global operation
keys. Include all relevant operations for the requested window, not a sample or
a limited query result.

## Counting rules

- Resolve the selected branch through `terminal_branches`; match `KODE_CABANG`
  ignoring case and surrounding whitespace.
- Match `ALAT` through `shifting.block_mapping_file`, ignoring case and surrounding
  whitespace. Unmapped equipment and equipment assigned to absent yard blocks
  are excluded. `BLOK` and container coordinates do not determine this assignment.
- Parse `ACTIVITY_DATE_TIME` as `DD-MM-YYYY HH:MM` in WIB (UTC+7). Creation and
  modification timestamps are not used. Invalid timestamps in scoped, countable
  rows raise a source/line error.
- Reuse `[shifting.activities]` for both CSV and SQL. Activity values match exactly.
  `Lift On Delivery` is currently excluded; add it to the shared lifting list only
  if it belongs in that metric. There is no automatic prefix classification.
- `shifting.period_granularity = "daily"` means the last 24 hours before the cutoff;
  `"weekly"` means the last 7 days. The start is inclusive and the end is exclusive.
- Produce one existing `ShiftingSummary` per mapped equipment code assigned to a
  loaded block, including zero counts when there are no matches. Multiple codes
  may contribute to the same block. Shifting percentage remains
  `100 * shifting / (lifting + shifting)`; an empty denominator yields `None`.

The report records the CSV source, shared activity lists, window timestamps, and
`operations_completeness = "unverified"`. A zero means no qualifying rows in the
supplied export, not proof that the export covers the entire window. No older
period is selected automatically. Parameter compliance still reflects the current
yard snapshot even when the operations cutoff is historical.

`excluded_activities` in the JSONL report lists unclassified activity names and
counts within the selected branch, mapped equipment, and window, for rows with
a nonempty operation identifier. The presenter displays nonempty exclusions.
