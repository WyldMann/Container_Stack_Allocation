# Raw shifting and lifting CSV import

In `config/shifting_calculation/shifting_report_input.toml`, select `shifting_summary = "csv"` in
`[input.sources]` and set the branch codes and CSV path.

```toml
[input.filters]
branch_code = ["JKT74", "JKT64"]

[csv.files]
shifting_summary = "../../data_shifting_calculation/shifting_report.csv"
```

Paths resolve from the input file's directory. The CSV window ends at the most recent activity
timestamp at or before the program run time for the selected branch and equipment
mapped to loaded yard blocks, among rows with a nonempty `DTL_ID`. Activities
outside the configured categories also participate in finding that latest
timestamp. Row order does not affect it.
`generated_at` is the program run time in Unix seconds, rather than a source
snapshot timestamp. It is the upper bound for eligible activity timestamps;
the latest eligible source activity still determines the CSV window end.
The report's `latest_date` (`YYYY-MM-DD`) is derived from the window end in WIB
for both daily and weekly windows, and is `null` when no window is available.
This label does not restrict the window to a calendar date or month.
XLSX and SQL remain independently selectable.
Each selected branch is loaded and analyzed separately. Its `cy_name` comes from
its own `BRANCH_NAME` in `terminal_branches`, and equipment mappings use that
branch's section in `shifting_block_mapping.toml`. Shared CSV files must contain
the data for all selected branches. A scalar `branch_code = "JKT74"` remains supported.
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

## CSV operation blacklist

Set the optional blacklist path in the input configuration:

```toml
[csv]
shifting_blacklist_file = "operations_blacklist.toml"
```

The path resolves from the input configuration's directory. The blacklist file
contains one `[[operations]]` table per excluded record:

```toml
[[operations]]
branch_code = "JKT64"
document_id = "66261"
detail_id = "32"
equipment_code = "RTG10"
activity = "Lift Off Discharge"
activity_time = "28-11-2026 03:04"
reason = "Future-dated source operation; date pending verification."
```

All seven fields are required nonempty strings. The six identity fields must all
match. Branch, equipment and activity comparisons ignore case and surrounding
whitespace; IDs ignore surrounding whitespace. Dates use the importer's day-first
formats and WIB timezone. CSV line numbers, `BLOK` and export filenames are not
part of the match, so reordered or renamed exports retain the same exclusions.
A corrected timestamp no longer matches the original blacklist entry.

Matching rows are skipped before both window selection and operation counting.
The file is loaded once per branch import, so additions or removals take effect
on the next calculation. Missing files, malformed rules and duplicate normalized
identities raise configuration errors. Remove a table to restore its record,
use `operations = []` for an empty blacklist, or omit the input setting to disable
the blacklist. Source CSVs and historical reports are preserved. This setting
applies only to CSV operations; SQL and XLSX imports retain their existing rules.

The configured blacklist includes the JKT74 record `65155/62` at
`27-11-2026 17:45` WIB and the JKT64 record `66261/32` at
`28-11-2026 03:04` WIB. This replaces the former hard-coded temporary exclusion.

## Counting rules

- Ignore activity timestamps later than the program run time, before selecting
  the window or counting operations. A timestamp exactly equal to run time is
  eligible. Timestamps are interpreted in WIB and compared as Unix seconds,
  independently of the host timezone. One cutoff is frozen for both CSV passes;
  batch reports share their `generated_at` cutoff across branches. Direct CSV
  imports capture the current clock once, or accept `recorded_at` explicitly.
  If every otherwise qualifying activity is in the future, the report has no operations
  window. Future rows are re-evaluated on each run, while explicit blacklist
  entries continue to exclude their matching records.
- Resolve the selected branch through `terminal_branches`; match `KODE_CABANG`
  ignoring case and surrounding whitespace.
  Set `[input.filters].branch_code` to select the branch. Its terminal and branch
  IDs are resolved internally for yard inputs; numeric ID input filters are no
  longer supported. Blank or omitted branch codes disable yard scoping, and
  shifting reports still require exactly one resolved branch.
- Match `ALAT` through `shifting.block_mapping_file`, ignoring case and surrounding
  whitespace. Mapping values are yard `block_code` strings (for example, `SL = "2A"`)
  or non-empty arrays such as `RTG04 = ["1A", "2A"]`,
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
  loaded block, including zero counts when there are no matches. Equipment mapped
  to multiple blocks still produces one summary with its counts included once.
  Missing blocks are omitted; equipment is retained if any mapped block is loaded.
  Repeated block codes resolve to a single block. Multiple codes
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
When a nonempty blacklist is configured, diagnostics also contain
`blacklisted_operations`: source locations, operation identities and reasons for
matching rows in the selected branch and mapped equipment. Each excluded source
row appears once, despite the two import passes. These exclusions may be outside
the resulting report window and are not included in the shortened JSONL output.
When future-dated rows are ignored, diagnostics include `future_operations`,
listing source locations, operation identities and the `recorded_at` cutoff.
These rows are logged once during window selection. Explicit blacklist matches
are logged under `blacklisted_operations` first, so exclusions are not duplicated.
Neither diagnostic is written into the shortened JSONL output.
Running `shifting_report_calculation.py` prints non-blacklisted future operations
under their branch before the recorded metrics. The console table includes the
branch, document/detail IDs, equipment, activity, activity time in WIB, run-time
cutoff in Unix seconds, and CSV source location. Each ignored source row is
printed once. Blacklisted matches are omitted from this table. If no such future
rows are present, no future-operations section is printed. Library calls to
`build_report()` and `build_reports()` remain silent.

## Recorded JSONL format

`shifting_report_calculation.py` appends one record per branch per run to
`output/existing_yard_metrics_<BRANCH_CODE>.jsonl`, including single-branch runs.
For the selection above, the files are `existing_yard_metrics_JKT74.jsonl` and
`existing_yard_metrics_JKT64.jsonl`. Existing unsuffixed files are not migrated.
Each branch's CSV window ends at its own latest scoped activity; all SQL reports
in a run share a read-only snapshot. `build_reports()` returns a dictionary keyed
by branch code; `build_report(branch_code="JKT74")` selects one configured branch.

CSV, SQL, and XLSX reports use the same ordered fields:
`cy_name`, `branch_code`, `generated_at`, `period_start`, `period_end`, `latest_date`, `period_granularity`,
`avg_shifting_percentage`, `avg_parameter_compliance`, `shifting_observations`.
Each record occupies one line, with a space after commas and colons.

Yard identity is recorded once at the top level, including when there are no
observations. `cy_name` preserves the branch display name; `branch_code` is trimmed
and uppercased. Existing JSONL history is not rewritten; the plotter also accepts
older records with identity inside observations.

Each observation contains, in order: `block_code`, `assigned_equipment`,
`lifting_count`, `shifting_count`, `shifting_percentage`, `parameter_compliance`.
Observations come from the selected latest reporting period. Equipment mapped to
the same block within a branch is combined into one observation: counts are
summed, and shifting percentage is calculated from the combined counts.
`assigned_equipment` is an array of unique contributing equipment codes in sorted
order (for example, `["RTG03", "RTG05"]`). A single code is also an array, such as
`["SL"]`; equipment names containing spaces remain one element, such as `["RS MDL"]`.
The plotter also accepts the older comma-separated `shifting_code` field.
Equipment mapped to multiple blocks merges those blocks into one observation.
`block_code` lists the merged codes in sorted order, separated by a comma and
space (for example, `"1A, 2A"`). Overlapping assignments merge transitively:
equipment covering `1A, 2A` and equipment covering `2A, 3A` form one group.
Each equipment summary contributes its counts once. Groups stay within a branch.
These rules apply to CSV, SQL, and XLSX reports.
Available counts are retained when another equipment has missing counts, but the
block percentage is `null` until all contributing counts are available.

`avg_shifting_percentage` is `100 * total shifting / total operations`, not the
arithmetic mean of equipment percentages. It is `null` for zero operations or
incomplete counts. `avg_parameter_compliance` is the container-weighted average
across all loaded blocks, multiplied by 100. Each observation's compliance is
its block's compliance multiplied by 100, recorded once per combined block.
For merged blocks, compliance is the container-weighted average across their
unique blocks; empty blocks contribute no weight. A group containing only empty
blocks has `null` compliance.
Multiple equipment codes do not give that block additional weight in the average.
An empty yard or empty block has `null` compliance; zero compliance remains zero.
The internal block compliance method continues to return a 0-1 ratio.

`latest_date` labels the CSV/SQL window end in WIB. XLSX uses its report date,
or the last included WIB date for weekly periods. SQL still defines its window
and date when observations are empty; CSV/XLSX have `null` dates without a window.
Parameter compliance always describes the current yard snapshot.
