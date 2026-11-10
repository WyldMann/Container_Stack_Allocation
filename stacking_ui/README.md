# Offline container-stacking scenario setup

Double-click `stacking_ui/open_setup.cmd` on Windows, or run the following from
the project root.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui
```

The launcher reads the current project TOML files and opens the offline HTML page
in an Edge window. It uses local Node.js and `playwright-core`, including the
installed Codex runtime when available. Each editor shows its loaded file and offers
**Choose a different TOML (optional)** to replace its contents for the draft.

1. **Use files in the project folder** is selected by default. The dataset cards
   show the CSV paths from the stacking input TOML and let you edit them there.
   Relative paths start in `config/container_stacking`, and the CSVs must be inside the project.
   Choose **Choose files in the browser** to select the nine UTF-8 CSVs yourself.
   Either source lets you mark a dataset explicitly empty.
2. Edit the prefilled value beside each setting name. Comments and section names
   appear as text. Use TOML syntax for values, including quotes for strings. To
   change the file structure, load another TOML into its editor. The branch-code
   field overrides the selection in the stacking input TOML when filled in.
3. Click **Generate preview**. The top-down map places blocks using their
   `POS_X` and `POS_Y` coordinates. Use **Fit yard** to see all blocks or
   **100%** to read the stack grids at full size. Select any stack to inspect
   its tiers and assigned parameters. Stack colors show
   the yard plan, and the numbers show occupied tiers over capacity. The initial
   yard can still be inspected when the inbound CSV is missing. The page also
   shows the incoming containers in a horizontal queue above the map, in CSV
   order. **Save preview** downloads the
   generated JSON. **Save draft** keeps a copy of your inputs.
4. Click **Start simulation**, then **Next container** to process one CSV row at
   a time, or **Run to end** to process all remaining rows without pausing.
   Invalid rows stay in the queue and are skipped. Each placement marks
   the destination on the map with its tier. A 40 ft stack spans both slots
   as one tile. **Assignment trace** shows the decision after each step and
   lets you revisit earlier rows. Expand **Show calculation details** for the
   rejection reasons, parameter scores, and candidates in yard order.
   The map outlines locations that passed feasibility and parameter selection,
   with the chosen placement in purple and rank badges for the top five.
   Each 40 ft candidate has one outline across both slots. Select an outlined
   tile for the score breakdown and tier. Earlier traces overlay the current
   yard. The map
   becomes the final yard after the last row. Generate a fresh preview to restart.

The saved draft also works from the project root for batch use.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui "path\to\stacking-scenario-draft.json"
```

Use **Load preview** to reopen a saved `.preview.json`.

Add `--bundle` to also write a ZIP beside the draft with the CSVs and portable TOML.
Folder drafts store the configured paths and read the files when you validate.
Browser-upload drafts include the selected CSV contents. Use **Load draft** to
resume editing after closing the page.

Run the launcher again after changing the TOML files on disk. If you open
`stacking_ui/static/index.html` directly, it uses the most recently loaded
defaults for draft editing and viewing saved previews. Use the launcher to
generate previews in the page. You can refresh the defaults without opening Edge.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui --refresh-defaults
```

Python builds the preview with the existing yard and CSV validation rules. The
offline launcher keeps the prepared yards in a local Python subprocess and calls
the same placement engine as the command-line program. Each branch advances
independently. A saved preview is a snapshot of the initial yard. In
browser-upload mode, the selected uploads supply the CSVs.
Previews are limited to 2,000,000 tier cells per branch.

Queue order follows the filtered CSV. Inbound records without branch coordinates
are included in each selected branch, matching the current importer. Empty
equipment data allows inspection, but a block without equipment is flagged
before placement. Existing import warnings and errors appear in the preview.

"Source rows" counts the uploaded records. "Loaded records" counts the result
after branch filtering, grouping, and latest equipment-history selection.

`scenario.prepare_scenario(payload)` returns the populated `Yard` objects and
normalized inputs used by the simulation. `public_preview(result)` converts the
initial state to the browser's review format.

Run the scenario tests with

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_stacking_scenario
```
