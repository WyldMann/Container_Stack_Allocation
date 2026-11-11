# Container stacking scenario setup

## Share the standalone simulator

Extract the standalone ZIP and open **index.html** in Chrome or Microsoft Edge. Keep the
files together. The package includes the Python engine, the interface, and a
snapshot of the stacking CSVs and TOMLs. It runs without a server or a separate
Python or Node.js installation.

Use **Replace selected CSVs** to replace any bundled dataset, or load a
different TOML in its editor. The Save buttons export TOMLs and
**containers.csv** through the browser.

To build a new snapshot from the project root, extract the
[Pyodide 0.27.7 npm archive](https://registry.npmjs.org/pyodide/-/pyodide-0.27.7.tgz).
Save the [Pyodide license](https://github.com/pyodide/pyodide/blob/0.27.7/LICENSE)
as **LICENSE** and the [CPython 3.12 license](https://github.com/python/cpython/blob/3.12/LICENSE)
as **LICENSE-Python** in the extracted **package** directory. Then run:

```powershell
.\.venv\Scripts\python.exe -m stacking_ui.standalone path\to\package output\container-stacking-standalone.zip
```

## Project launcher

Double-click `stacking_ui/open_setup.cmd` on Windows, or run the following from
the project root.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui
```

The launcher reads the current project TOML files and opens the setup page
in an Edge window. It uses local Node.js and `playwright-core`, including the
installed Codex runtime when available. Each editor shows its loaded file and offers
**Choose a different TOML (optional)** to replace its contents in the editor.

1. **Use files in the project folder** is selected by default. The dataset cards
   show the CSV paths from the stacking input TOML and let you edit them there.
   Relative paths start in `config/container_stacking`, and the CSVs must be inside the project.
   Choose **Choose files in the browser** to select the nine UTF-8 CSVs yourself.
   Either source lets you mark a dataset explicitly empty.
2. Edit the prefilled value beside each setting name. Comments and section names
   appear as text. Use TOML syntax for values, including quotes for strings. To
   change the file structure, load another TOML into its editor. Edit
   `branch_code` under **Stacking inputs** to select branches. Each editor's
   **Save** button writes its values to the corresponding project TOML.
3. Click **Generate preview**. The top-down map places blocks using their
   `POS_X` and `POS_Y` coordinates. Use **Fit yard** to see all blocks or
   **100%** to read the stack grids at full size. Select any stack to inspect
   its tiers and assigned parameters. Stack colors show
   the yard plan, and the numbers show occupied tiers over capacity. The initial
   yard can still be inspected when the inbound CSV is missing. The page also
   shows the incoming containers in a horizontal queue above the map, in CSV
   order. **Save yard CSV** opens a Save As dialog for `containers.csv` with
   the yards in the preview, including placements completed so far.
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

Existing draft JSON files work from the project root for batch use.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui "path\to\stacking-scenario-draft.json"
```

Add `--bundle` to also write a ZIP beside the draft with the CSVs and portable TOML.
Folder drafts store the configured paths and read the files when you validate.
Browser-upload drafts include the selected CSV contents.

The launcher reads the project TOMLs on each page load and refreshes untouched
editors before generating a preview. Browser edits and alternate TOMLs stay
in their editors. **Reload project TOMLs** replaces all
three editors with the files on disk.

If you open `stacking_ui/static/index.html` directly, it uses cached defaults.
You can refresh that cache without opening Edge.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui --refresh-defaults
```

Python builds the preview with the existing yard and CSV validation rules. The
launcher keeps the prepared yards in a local Python subprocess and calls
the same placement engine as the command-line program. Each branch advances
independently. In browser-upload mode, the selected uploads supply the CSVs.
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
