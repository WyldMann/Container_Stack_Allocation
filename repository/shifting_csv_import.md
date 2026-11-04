# Raw shifting and lifting CSV import

Select `shifting_summary = "csv"` in `[input.sources]` and configure:

```toml
[csv.files]
shifting_summary = "../data_CY219/shfiting_report.csv"
```

Paths resolve from `input.toml`. The CSV window ends at the most recent activity
timestamp for the selected branch and equipment mapped to loaded yard blocks,
among rows with a nonempty `DTL_ID`. Activities outside the configured categories
also participate in finding that latest timestamp. Row order does not affect it.
`recorded_at` records when the yard metrics were produced, not the window end.
The report's `latest_date` (`YYYY-MM-DD`) is derived from the window end in WIB
for both daily and weekly windows, and is `null` when no window is available.
This label does not restrict the window to a calendar date or month.
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
  whitespace. Mapping values are yard `block_code` strings (for example, `SL = "2A"`),
  resolved to the loaded yard's `block_id` internally. Recorded observations use
  `block_code`. Unmapped equipment
  and equipment assigned to absent yard block codes
  are excluded. `BLOK` and container coordinates do not determine this assignment.
- Parse `ACTIVITY_DATE_TIME` as `DD-MM-YYYY HH:MM` or `DD/MM/YYYY HH:MM` in WIB
  (UTC+7). Both formats are day-first and accept unpadded days/months. Creation and
  modification timestamps are not used. Blank or whitespace-only timestamps are
  skipped when selecting the latest window and counting operations. Nonblank,
  invalid timestamps in scoped, countable rows raise a source/line error.
- Reuse `[shifting.activities]` for both CSV and SQL. Activity names match ignoring
  capitalization, so `Lift on Loading` matches `Lift On Loading`. The configured
  lifting activities include `Lift On Delivery`; shifting activities include
  `Shifting`. Duplicate names and names assigned to both categories are rejected
  ignoring capitalization. There is no automatic prefix classification.
- `shifting.period_granularity = "daily"` means the 24 hours ending at that timestamp;
  `"weekly"` means the preceding 7 days. The start is exclusive and the end
  is inclusive, so operations at the latest timestamp are counted. One common
  window applies to all equipment codes. The importer scans twice to find the
  latest timestamp and count the selected window without
  retaining the full export in memory.
- Produce one existing `ShiftingSummary` per mapped equipment code assigned to a
  loaded block, including zero counts when there are no matches. Multiple codes
  may contribute to the same block. Shifting percentage remains
  `100 * shifting / (lifting + shifting)`; an empty denominator yields `None`.
  If there are no scoped, dated operations, return no observations and leave the
  report window unavailable (`None`).

The CSV uses the latest activity window, whose completeness is unverified.
A zero means no qualifying rows in the
supplied export, not proof that the export covers the entire window. No older
period is selected automatically. Parameter compliance still reflects the current
yard snapshot even when the CSV operations are historical. The former
`csv.shifting_cutoff` setting is no longer supported. SQL retains its rolling
last-24-hours / last-7-days windows.

Importer diagnostics can collect `excluded_activities`, listing unclassified
activity names and counts within the selected branch, mapped equipment, and
window, for rows with a nonempty operation identifier. These diagnostics are
not included in the shortened JSONL output.

## Recorded JSONL format

CSV, SQL, and XLSX reports use the same ordered fields:
`recorded_at`, `period_start`, `period_end`, `latest_date`, `period_granularity`,
`avg_shifting_percentage`, `avg_parameter_compliance`, `shifting_observations`.
Each record occupies one line, with a space after commas and colons.

Each observation contains, in order: `cy_name`, `block_code`, `shifting_code`,
`lifting_count`, `shifting_count`, `shifting_percentage`, `parameter_compliance`.
Observations come from the selected latest reporting period.

`avg_shifting_percentage` is `100 * total shifting / total operations`, not the
arithmetic mean of equipment percentages. It is `null` for zero operations or
incomplete counts. `avg_parameter_compliance` is the container-weighted average
across all loaded blocks, multiplied by 100. Each observation's compliance is
its block's compliance multiplied by 100. Multiple equipment codes may repeat
a block's compliance without giving that block additional weight in the average.
An empty yard or empty block has `null` compliance; zero compliance remains zero.
The internal block compliance method continues to return a 0-1 ratio.

`latest_date` labels the CSV/SQL window end in WIB. XLSX uses its report date,
or the last included WIB date for weekly periods. SQL still defines its window
and date when observations are empty; CSV/XLSX have `null` dates without a window.
Parameter compliance always describes the current yard snapshot.
