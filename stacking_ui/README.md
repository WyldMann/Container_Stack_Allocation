# Container stacking scenario setup

## Share the standalone simulator

Extract the standalone ZIP and open **container-stacking-simulator.html** in Chrome or Microsoft Edge. Keep the
files together. The package includes the Python engine, the interface, and a
snapshot of the stacking CSVs and TOMLs. It runs without a server or a separate
Python or Node.js installation.

Under **Use bundled CSVs**, choose a yard branch from the dropdown. It lists
the branches that have yard blocks in the package. **Download bundled CSVs (ZIP)**
saves all nine original input CSVs, including all branches, in one archive. It
works offline without generating a preview and remains available when replacing
files. Extract the archive to inspect or edit the CSVs, then use **Select CSV
folder** to load them again. Choose **Replace selected
CSVs** to replace individual files or load a TOML under **Input configuration**.
**CSV column mappings** also offers **Load from TOML**. **Save settings** remembers
the current TOML in this browser for future visits to the same page.
**Save as TOML** downloads a copy.
**Save yard CSV** downloads **containers.csv**.
Under **Replace selected CSVs**, use **Select CSV folder** to replace all nine
input files at once. The folder must contain all nine CSVs named in **Input
configuration**. A missing or ambiguous file leaves the previous selection
intact. The bundled TOML already names the standard CSV files.

**Currently loader accessible** checks whether the loader can reach the
destination before placement. **Preserve access to occupied stacks** and
**Preserve access to future receiving locations** check which locations would
lose access after placement. Each rule has its own mode and enables its weight
in **Heuristic** mode. The default unreachable destination multiplier is 0.25.
Each access loss weight defaults to 1 per location that loses access.

Each block has **Above**, **Below**, **Left**, and **Right** access switches around
its grid. Set them before starting that branch's simulation. Green **Open** and
red **Closed** states control loader entry; Above and Below also provide exterior
working space. Reach stackers (`EQUIPMENT_TYPE = RS`) can serve 20 ft containers
from reachable ground on any of the four sides, including exterior working space
at an open Left or Right border. Other loaders retain Above/Below service, and
40 ft containers still need two aligned working positions Above or Below.
Equipment selection checks the selected loader's capability; access preservation
includes RS approaches whenever an RS is registered in the yard.
The switches lock after the first inbound row is processed.
Unlisted blocks default to all four borders open, and RTG service remains exempt.

Each block's **Save block access settings** button is grey until at least one border differs
from its saved setting. Returning all switches to their saved values disables
it again, including when the CSV is empty and all borders default to open.
Saving only writes that block; changes to other blocks stay unsaved.
The map lists every block with unsaved access changes. The message disappears
when all changes are saved or reverted.

In the standalone package, **Save block access settings** remembers that block's settings in
this browser. Generate another bundled preview to reuse them. **Download
bundled CSVs (ZIP)** includes the saved `block_accessibility.csv` alongside the
other inputs, preserving access settings for other branches. Share that CSV or
the downloaded data ZIP to transfer settings to another browser or computer.
In the desktop launcher, **Save block access settings** updates that block in the configured
project CSV. The file uses `BLOCK_ID,ABOVE,BELOW,LEFT,RIGHT` with `TRUE` or `FALSE` values.
An empty or omitted optional CSV uses the default open borders. Uploading a
replacement accessibility CSV uses that file for the current preview.

**Pyramid stacking** has two independent switches, both on by default:
**Reduce score as the tier gap grows** applies the declining score curve, and
**Reject placements above the tier gap limit** rejects placements beyond
`stacking_safety_maxima`. Turning off
the decrease gives a score multiplier of 1; turning off the bound allows larger
differences at the curve's endpoint score. Turning both off skips the pyramid
rule and keeps its settings for later. The difference is the post-placement height
above the tallest considered neighbor, with ground height zero as the fallback.
The score is 1 through `feasibility.stacking_safety_penalty_start` (default `1`),
then declines linearly to `heuristic.stacking_safety_limit_multiplier` (default
`0.25`) at `feasibility.stacking_safety_maxima` (default `2`). Differences above
the maximum are rejected; the maximum itself remains feasible.

The penalty start must be a whole number from zero to one below the maximum.
The maximum must be a positive whole number, and the multiplier must be between
zero and one. The UI clamps thresholds to this range and keeps the previous
value for blank or fractional entries. The switches save through
`feasibility.stacking_safety_mode`: both on is `combined`, decrease only is
`heuristic`, bound only is `feasibility`, and both off is `off`. Older boolean or mode settings
continue to select their corresponding mode; the old
`heuristic.unsafe_stacking_multiplier` supplies the endpoint multiplier when
the new multiplier is omitted. Heuristic mode now uses the declining curve
instead of the former pass/fail score step.

The switches around the stack square select which neighbor sides provide pyramid
support. **Up** and **Down** default on; **Left** and **Right** default off,
including in older TOMLs that omit these settings. Configure them with
`stacking_safety_neighbor_up`, `stacking_safety_neighbor_down`,
`stacking_safety_neighbor_left`, and `stacking_safety_neighbor_right` under
`[feasibility]`. Up/down follow the previous/next row in the yard grid.
For 40 ft containers, up/down consider both slots along the footprint, and
left/right are outside the complete footprint. At least one enabled neighbor
must support a placement above the isolated-stack height limit. With all four
sides off, that height limit still applies. Turning the pyramid rule off retains
the selected sides for later.

**Container size clustering** groups two independently configured terms:

- Same-size reward: `2 ** (size_cluster_reward_bias * S / (S + size_cluster_reward_prior))`.
- Different-size penalty: `2 ** (-size_cluster_penalty_bias * O / (O + size_cluster_penalty_prior))`.

The clustering multiplier is reward × penalty. `S` sums
`2 ** (-distance / hl_size_cluster_reward_distance)` for occupied matching
stacks within `size_cluster_reward_radius`. `O` sums
`2 ** (-distance / hl_size_cluster_penalty_distance)` for occupied
different-size stacks within `size_cluster_penalty_radius`. Distances use
the closest footprint cells in grid units. Stack height does not
increase the evidence, 40 ft pairs count once, and the supporting footprint
is excluded. Each prior must be positive; a larger prior makes its effect
build more slowly. Each bias must be non-negative; zero disables that term.
Each radius is a non-negative integer, and zero disables only its term.
Each distance half-influence value must be positive.
The green reward panel and brown penalty panel have separate controls and
formula labels, with both effects shown in the shared graph below.
`enable_size_cluster_reward` and `enable_size_cluster_penalty` independently
switch each term on or off. Off contributes a neutral multiplier of 1,
disables only that panel's numeric controls, and retains its configured values.
Both switches start on in the project configuration.

Older TOMLs can still use `size_cluster_bias`, `size_cluster_prior`,
`size_cluster_radius`, and `hl_size_cluster_distance` as fallbacks for
omitted reward or penalty settings. Explicit term settings
take precedence, including zero. Scoring always uses the new independent
denominators, so mixed-size neighborhoods can receive different scores
from the former shared-denominator formula.
The legacy `enable_size_cluster` supplies either term's switch when that
term has no explicit switch. Explicit term switches override it independently.

To build a new snapshot from the project root, extract the
[Pyodide 0.27.7 npm archive](https://registry.npmjs.org/pyodide/-/pyodide-0.27.7.tgz).
Save the [Pyodide license](https://github.com/pyodide/pyodide/blob/0.27.7/LICENSE)
as **LICENSE** and the [CPython 3.12 license](https://github.com/python/cpython/blob/3.12/LICENSE)
as **LICENSE-Python** in the extracted **package** directory. Then run:

```powershell
.\.venv\Scripts\python.exe -m stacking_ui.standalone path\to\package output\container-stacking-standalone.zip
```

To preset the standalone filter to JKT64 without adding any other CSVs, run:

```powershell
.\.venv\Scripts\python.exe -m stacking_ui.standalone path\to\package output\container-stacking-standalone.zip --branch-code JKT64
```

Choose **Replace selected CSVs** and select the JKT64 CSV folder before
generating its preview.

To include the current yard CSVs directly in the package and open JKT64 by default:

```powershell
.\.venv\Scripts\python.exe -m stacking_ui.standalone .venv\yard-stacking-pyodide-0.27.7\package output\container-stacking-standalone.zip --data-dir data_container_stacking --branch-code JKT64
```

The data directory must be inside the project and contain the nine CSV filenames
used by the input TOML. The ZIP includes those CSVs, so selecting a folder in the
browser is unnecessary. The current BigYard data lives directly in
`data_container_stacking`; archived CSVs in its subfolders are excluded.

## Project launcher

Double-click `stacking_ui/open_setup.cmd` on Windows, or run the following from
the project root.

```powershell
.\.venv\Scripts\python.exe -m stacking_ui
```

The launcher reads the current project TOML files and opens the setup page
in an Edge window. It uses local Node.js and `playwright-core`, including the
installed Codex runtime when available. Each editor shows its loaded file and offers
**Load from TOML** to replace its contents in the editor.

1. Under **Yard and inbound data**, **Use files in the project folder** is
   selected by default. Use **Input configuration** to load another input TOML
   or edit `branch_code`. The dataset cards show the configured CSV paths and
   let you edit them there.
   Relative paths start in `config/container_stacking`, and the CSVs must be inside the project.
   Choose **Choose files in the browser** to select the nine UTF-8 CSVs yourself.
   Either source lets you mark a dataset explicitly empty. Open **CSV column
   mappings** below the cards to edit or load a mapping. Use TOML syntax when
   editing text values in either editor.
2. Under **Simulation settings**, edit the prefilled values in **Placement
   settings**. Each editor's **Save** button writes its values to the
   corresponding project TOML.
3. Click **Generate preview**. The top-down map uses a compact schematic layout.
   `POS_X` and `POS_Y` determine the general arrangement, with near-aligned blocks
   grouped into rows and columns and excessive distances replaced by compact gaps.
   Blocks sharing a position form a compact cluster. Original coordinates still
   supply simulation distances, and stack tiles keep their 20 ft proportions.
   Use the mouse wheel over the map, the zoom
   slider, or the **−** and **+** buttons to adjust its size. Right-click and drag
   to pan the map. Select any stack to inspect
   its tiers and assigned parameters. Stack colors show
   the yard plan, and the numbers show occupied tiers over capacity. **Yard tier
   gaps** lists affected slots. Before starting a branch, **Fill gaps with dummy
   containers** can temporarily fill gaps the simulator can repair safely.
   Dummy tiers count as occupied and are excluded from the yard CSV. Generate a
   fresh preview to return to the original inputs. **Input and yard issues**
   groups the other errors and warnings with their source files and row numbers.
   Skipped records appear as warnings. You can still run a branch with a usable
   yard and inbound queue.
   The initial
   yard can still be inspected when the inbound CSV is missing. The page also
   shows the incoming containers in a horizontal queue above the map. Click a card or
   focus it with **Tab** to see its details below the queue. **Add container** appends
   a row to the selected branch for this preview. Enter a container ID and select
   20 ft or 40 ft. Open **Container details (optional)** to enter the same cargo,
   routing, vessel, and move-time fields shown on a focused card. Check **Dummy
   container** to have the simulator assign the ID and disable the optional
   details. Placed dummies are excluded from the yard CSV. Use **Delete container**
   and confirm to remove an unprocessed row from this preview. Press **Enter** on a
   focused card to reach its actions. Use **Move to front** to make it next in line
   or **Move to end** to put it last. Hold a dragged card near either edge of the
   queue to scroll and release it at the insertion marker. On a focused card,
   press **Alt + Left Arrow** or **Alt + Right Arrow** to move it one place. The simulation
   follows the new order, including changes made between steps. **Save yard CSV**
   opens a Save As dialog for `containers.csv` with the yards in the preview,
   including placements completed so far.
4. **Generate preview** shows the suggested assignment for the current container.
   Drag another card into the first remaining position to make it current and
   see its suggestion. **Choose alternate location** accepts coordinates inside the
   yard grid. Click a stack on the map or use the **Block**, **Row**, **Slot**, and
   **Tier** dropdowns. A 40 ft container uses a complete slot pair. The simulator
   asks for confirmation before replacing an occupant in the selected footprint.
   **Use engine recommendation** returns to the engine's location. **Place at
   manual location** commits a selected alternate, and **Place container**
   commits the engine recommendation.
   **View trace** shows the engine recommendation and committed alternate, and
   **Save yard CSV** exports the actual placement. When a row is invalid or has no
   qualifying location, **Skip container** advances the queue. **Run to end**
   starts with the displayed assignment and processes later rows automatically. Each placement marks
   the destination on the map with its tier. A 40 ft stack spans both slots
   as one tile. Use **View assignment** to revisit completed rows or return to
   the current suggestion. Expand **Show calculation details** for the
   rejection reasons, parameter scores, and candidates in yard order.
   The map outlines locations that passed feasibility and parameter selection,
   with the chosen placement in purple and rank badges for the top five.
   Each 40 ft candidate has one outline across both slots. Select an outlined
   tile for the score breakdown and tier. Earlier traces overlay the current
   yard. The map
   becomes the final yard after the last row. Generate a fresh preview to restart.
5. After a branch finishes, use **Compare yard** to load a CSV in the same
   format as `containers.csv`. Select a block and then a slot in the linked
   placement maps to compare tier contents. Compare placements by container ID
   and review occupancy and parameter compliance for the yard and each block.

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

Each branch starts in filtered CSV order. Reordering applies to that branch
for the current preview. Generating a fresh preview restores CSV order.
Inbound records without branch coordinates
are included in each selected branch, matching the current importer. An
equipment-free yard can run with null equipment and a neutral equipment-distance
multiplier; no equipment is moved. Blocks without equipment are flagged in the
preview. Existing import warnings and errors appear there too.

"Source rows" counts the uploaded records. "Loaded records" counts the result
after branch filtering, grouping, and latest equipment-history selection.

`scenario.prepare_scenario(payload)` returns the populated `Yard` objects and
normalized inputs used by the simulation. `public_preview(result)` converts the
initial state to the browser's review format.

Run the scenario tests with

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_stacking_scenario
```

Check the schematic layout's spacing, alignment, and coordinate preservation with:

```powershell
node --test tests/test_yard_map_layout.cjs
```

Run the inbound queue browser tests from the project root with the launcher's
Edge, Playwright, and Python dependencies.

```powershell
node --test tests/test_inbound_queue.cjs
```
