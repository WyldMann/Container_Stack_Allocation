# Raw shifting and lifting CSV import

Select `shifting_summary = "csv"` in `[input.sources]` and configure:

```toml
[csv.files]
shifting_summary = "../data_CY219/shfiting_report.csv"
```

Paths resolve from `input.toml`. The CSV window starts at the earliest activity
timestamp for the selected branch and equipment mapped to loaded yard blocks,
among rows with a nonempty `DTL_ID`. Activities outside the configured categories
also participate in finding that first timestamp. Row order does not affect it.
`recorded_at` records when the yard metrics were produced, not the window start.
XLSX and SQL remain independently selectable.
The CSV path is resolved with the other entries in `[csv.files]` and stored in
`settings["csv_files"]["shifting_summary"]`. The former
`csv.shifting_operations_file` setting is rejected. `csv.shifting_workbook_file`
and `csv.shifting_workbook_sheet` apply only to the XLSX source.

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
- `shifting.period_granularity = "daily"` means the first 24 hours from that timestamp;
  `"weekly"` means the first 7 days. The start is inclusive and the end
  is exclusive. One common window applies to all equipment codes. The importer
  scans twice to find the earliest timestamp and count the selected window without
  retaining the full export in memory.
- Produce one existing `ShiftingSummary` per mapped equipment code assigned to a
  loaded block, including zero counts when there are no matches. Multiple codes
  may contribute to the same block. Shifting percentage remains
  `100 * shifting / (lifting + shifting)`; an empty denominator yields `None`.
  If there are no scoped, dated operations, return no observations and leave the
  report window unavailable (`None`).

The report records the CSV source, shared activity lists, window timestamps, and
`operations_period_basis = "first_activity_window"` and
`operations_completeness = "unverified"`. A zero means no qualifying rows in the
supplied export, not proof that the export covers the entire window. No older
period is selected automatically. Parameter compliance still reflects the current
yard snapshot even when the CSV operations are historical. The former
`csv.shifting_cutoff` setting is no longer supported. SQL retains its rolling
last-24-hours / last-7-days windows.

`excluded_activities` in the JSONL report lists unclassified activity names and
counts within the selected branch, mapped equipment, and window, for rows with
a nonempty operation identifier. The presenter displays nonempty exclusions.
