"use strict";

const assert = require("node:assert/strict");
const {execFileSync} = require("node:child_process");
const {existsSync} = require("node:fs");
const {homedir} = require("node:os");
const path = require("node:path");
const {test} = require("node:test");
const {pathToFileURL} = require("node:url");
const {startWorker} = require("../stacking_ui/browser.cjs");

const root = path.resolve(__dirname, "..");
const bundledNode = path.join(homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node");
const {chromium} = require(require.resolve("playwright-core", {paths: [root, bundledNode]}));
const localPython = process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python";
const python = process.env.STACKING_TEST_PYTHON ??
  (existsSync(path.join(root, localPython)) ? path.join(root, localPython) : "python");

function scenarioDraft(count, {firstId = "", firstSize = "20", equipmentChoices = ""}) {
  return JSON.parse(execFileSync(python, ["-B", "-c", [
    "import json, sys",
    "from tests.test_stacking_scenario import ScenarioTests",
    "scenario = ScenarioTests()",
    "scenario.setUp()",
    "scenario.rows['inbound_containers'] = [dict(container_id=f'NEW{i:02d}', container_size='20')",
    "    for i in range(1, int(sys.argv[1]) + 1)]",
    "if sys.argv[2]: scenario.rows['inbound_containers'][0]['container_id'] = sys.argv[2]",
    "if scenario.rows['inbound_containers']: scenario.rows['inbound_containers'][0]['container_size'] = sys.argv[4]",
    "if sys.argv[3]:",
    "    scenario.rows['yard_blocks'].append(scenario.rows['yard_blocks'][0] |",
    "        dict(block_id='11', block_code='B', pos_x='10'))",
    "    equipment = [('SL1', 'SL', 'A'), ('RS1', 'RS', 'A')]",
    "    if sys.argv[3] == 'open': equipment.append(('RTG2', 'RTG', 'B'))",
    "    for code, kind, block in equipment:",
    "        scenario.rows['master_equipment'].append(dict(equipment_code=code, equipment_type=kind))",
    "        scenario.rows['equipment_history'].append(scenario.rows['equipment_history'][0] |",
    "            dict(equipment_code=code, block_code=block))",
    "    if sys.argv[3] == 'blocked':",
    "        scenario.rows['existing_containers'].append(scenario.rows['existing_containers'][0] |",
    "            dict(container_id='OBSTACLE', block_code='B', row_no='2', slot_no='2'))",
    "        scenario.rows['block_accessibility'] = [dict(block_id='11', above='false', below='true',",
    "            left='true', right='false')]",
    "scenario.write_files()",
    "print(json.dumps(scenario.payload | {'version': 1, 'file_source': 'upload'}))"
  ].join("\n"), String(count), firstId, equipmentChoices, firstSize], {cwd: root, encoding: "utf8"}));
}

async function openPreview(t, count, viewport = {width: 1200, height: 900}, fixture = {}) {
  const draft = scenarioDraft(count, fixture);
  const browser = await chromium.launch({channel: "msedge", headless: true});
  t.after(() => browser.close());
  const worker = startWorker(python);
  t.after(() => worker.close());
  const page = await browser.newPage({offline: true, locale: "en-US", viewport});
  page.setDefaultTimeout(10000);
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  t.after(() => assert.deepEqual(pageErrors, []));

  await page.exposeFunction("generateStackingPreview", () => worker.request({op: "preview", draft}));
  for (const [method, op] of [
    ["suggestStackingAssignment", "suggest"],
    ["getStackingManualEquipment", "manual_equipment"],
    ["stepStackingSimulation", "step"],
    ["addStackingQueueRow", "add_queue_row"],
    ["reorderStackingQueue", "reorder_queue"],
    ["deleteStackingQueueRow", "delete_queue_row"],
    ["updateStackingBlockAccess", "update_block_access"],
    ["addStackingDummy", "add_stack_dummy"],
    ["removeStackingTop", "remove_stack_top"]
  ]) {
    await page.exposeFunction(method, request => worker.request({...request, op}));
  }
  await page.goto(pathToFileURL(path.join(root, "stacking_ui", "static", "index.html")).href);
  await page.getByRole("button", {name: "Generate preview", exact: true}).click();
  return page;
}

const button = (page, name) => page.getByRole("button", {name, exact: true});
const cardIds = page => page.locator(".inbound-card strong");
const feedback = (page, text) => page.getByText(text, {exact: true});

test("scan order switch writes the selected mode into the preview TOML", async t => {
  const page = await openPreview(t, 1);
  await page.waitForFunction(() => !document.getElementById("generate-preview").disabled);
  const switchGroup = page.getByRole("radiogroup", {name: "Scan order"});
  const rowWise = switchGroup.getByRole("radio", {name: "Row-wise"});
  const slotWise = switchGroup.getByRole("radio", {name: "Slot-wise"});
  const penaltyStart = page.getByRole("spinbutton", {name: "Start reducing score", exact: true});
  const previewToml = () => page.evaluate(() => buildDraft().config_toml);
  const load = text => page.locator("#load-config").setInputFiles({
    name: "scan-order.toml", mimeType: "application/toml", buffer: Buffer.from(text)
  });

  assert.equal(await slotWise.isChecked(), true);
  assert.equal(await penaltyStart.inputValue(), "0");
  await load("[heuristic]\nenable_equipment_distance = false\n");
  await feedback(page, "Loaded scan-order.toml.").waitFor();
  assert.equal(await slotWise.isChecked(), true);
  assert.equal(await penaltyStart.inputValue(), "0");
  await switchGroup.getByText("Row-wise", {exact: true}).click();
  assert.equal(await rowWise.isChecked(), true);
  assert.equal(await previewToml(), '[heuristic]\nscan_order = "row_wise"\nenable_equipment_distance = false\n');
  await switchGroup.getByText("Slot-wise", {exact: true}).click();
  assert.equal(await previewToml(), "[heuristic]\nenable_equipment_distance = false\n");

  await load("heuristic = { scan_order = 'slot_wise', enable_equipment_distance = false }\n");
  await feedback(page, "Loaded scan-order.toml.").waitFor();
  assert.equal(await slotWise.isChecked(), true);
  await switchGroup.getByText("Row-wise", {exact: true}).click();
  assert.equal(await previewToml(), 'heuristic = { scan_order = "row_wise", enable_equipment_distance = false }\n');
});

test("equipment access controls can edit a TOML with legacy loader keys", async t => {
  const page = await openPreview(t, 1);
  await page.waitForFunction(() => !document.getElementById("generate-preview").disabled);
  const group = page.getByRole("group", {name: "Equipment access", exact: true});
  await group.getByText(/When the block’s RTG serves the placement/).waitFor();
  for (const name of ["Loss of access to occupied stacks", "Loss of access to future receiving locations"]) {
    assert.equal(await group.getByRole("radiogroup", {name, exact: true}).count(), 1);
  }
  assert.equal(await page.getByRole("radiogroup", {name: "Placements above the stack height limit", exact: true}).count(), 1);
  const text = '[feasibility]\nloader_destination_access_mode = "heuristic"\n' +
    '[heuristic]\nloader_inaccessible_destination_multiplier = 0.6\n';
  await page.locator("#load-config").setInputFiles({
    name: "legacy-access.toml", mimeType: "application/toml", buffer: Buffer.from(text)
  });
  await feedback(page, "Loaded legacy-access.toml.").waitFor();

  const modes = group.getByRole("radiogroup", {name: "Unreachable destinations"});
  const weight = group.getByRole("textbox", {name: "Unreachable destination multiplier"});
  assert.equal(await modes.getByRole("radio", {name: "Reduce score"}).isChecked(), true);
  assert.equal(await weight.inputValue(), "0.6");
  await weight.fill("0.7");
  assert.equal(await page.evaluate(() => buildDraft().config_toml), text.replace("0.6", "0.7"));
  await modes.getByText("Reject", {exact: true}).click();
  assert.match(await page.evaluate(() => buildDraft().config_toml), /loader_destination_access_mode = "feasibility"/);
  await modes.getByText("Off", {exact: true}).click();
  assert.match(await page.evaluate(() => buildDraft().config_toml), /loader_destination_access_mode = "off"/);
  await modes.getByText("Reduce score", {exact: true}).click();
  assert.match(await page.evaluate(() => buildDraft().config_toml), /loader_destination_access_mode = "heuristic"/);
});

test("block access switches show locks once the first inbound row is processed", async t => {
  const page = await openPreview(t, 2);
  const switches = page.getByRole("switch", {name: /border access/});
  const locks = switches.locator(".yard-access-lock:visible");
  const above = switches.filter({hasText: "Above"}).first();
  await above.waitFor();
  const count = await switches.count();
  assert.ok(count >= 4);
  assert.equal(await above.isEnabled(), true);
  assert.equal(await locks.count(), 0);

  await page.evaluate(() => {
    const update = globalThis.updateStackingBlockAccess;
    globalThis.updateStackingBlockAccess = async access => {
      await new Promise(resolve => { globalThis.finishAccessUpdate = resolve; });
      return update(access);
    };
  });
  await above.click();
  await page.waitForFunction(() => typeof globalThis.finishAccessUpdate === "function");
  assert.equal(await above.isDisabled(), true);
  assert.equal(await locks.count(), 0);
  await page.evaluate(() => globalThis.finishAccessUpdate());
  await page.waitForFunction(() => !document.querySelector(".yard-access-above").disabled);
  assert.equal(await above.isChecked(), false);

  await page.evaluate(() => {
    const step = globalThis.stepStackingSimulation;
    globalThis.stepStackingSimulation = async request => {
      await new Promise(resolve => { globalThis.finishFirstStep = resolve; });
      return step(request);
    };
  });
  await button(page, "Place container").click();
  await page.waitForFunction(() => typeof globalThis.finishFirstStep === "function");
  assert.equal(await above.isDisabled(), true);
  assert.equal(await locks.count(), 0);
  await page.evaluate(() => globalThis.finishFirstStep());
  await page.getByText(/1 of 2 processed/).waitFor();
  assert.equal(await locks.count(), count);
  assert.equal(await above.isDisabled(), true);
  assert.equal(await above.isChecked(), false);
  assert.equal(await above.getAttribute("aria-description"), "Block access is locked.");
});

async function containerDetails(page) {
  return page.getByRole("region", {name: "Container details"}).locator("dl > div").evaluateAll(
    fields => Object.fromEntries(fields.map(field => [
      field.querySelector("dt").textContent, field.querySelector("dd").textContent
    ]))
  );
}

test("optional container details match the focused card and survive placement", async t => {
  const page = await openPreview(t, 0, {width: 390, height: 844});
  const form = page.locator("#inbound-add-form");
  const textbox = name => form.getByRole("textbox", {name, exact: true});
  const select = name => form.getByRole("combobox", {name, exact: true});
  const optionalFields = {
    "Condition": "AV", "Grade": "FG", "Operation": "D", "Principal": "MRT",
    "Port of loading": "THLCH", "Port of transshipment": "SGSIN", "Port of discharge": "IDJKT",
    "Vessel": "MPS", "Voyage": "KN286W", "Vessel operator": "MRT"
  };

  await button(page, "Add container").click();
  await textbox("Container ID").fill("DISCARD");
  await button(page, "Cancel adding container").click();
  assert.equal(await form.isVisible(), false);
  await button(page, "Add container").click();
  assert.equal(await textbox("Container ID").inputValue(), "");
  await textbox("Container ID").fill("MAN-40");
  await select("Size").selectOption("40");
  assert.equal(await textbox("Vessel").isVisible(), false);
  await form.getByText("Container details (optional)", {exact: true}).click();
  assert.ok(await form.evaluate(element => element.scrollWidth === element.clientWidth));
  const labels = await form.locator(".inbound-add-fields label span").allTextContents();

  await select("Full / empty").selectOption("F");
  await form.getByRole("spinbutton", {name: "Weight", exact: true}).fill("12500.12345");
  for (const [label, value] of Object.entries(optionalFields)) await textbox(label).fill(value.toLowerCase());
  await textbox("Move time").fill("sometime");
  await button(page, "Add to queue").click();
  await form.getByText(/Enter a valid move time/).waitFor();
  assert.equal(await cardIds(page).count(), 0);
  assert.equal(await textbox("Vessel").inputValue(), "mps");

  await textbox("Move time").fill("2026-11-23 14:25");
  await button(page, "Add to queue").click();
  await feedback(page, "MAN-40 added to the inbound queue.").waitFor();
  const details = await containerDetails(page);
  assert.deepEqual(Object.keys(details).slice(2, -1), labels);
  assert.deepEqual(details, {Status: "pending", Size: "40 ft", "Full / empty": "Full", Weight: "12,500.12345",
    ...optionalFields, "Move time": "2026-11-23 14:25", Source: "Manual entry"});
  await button(page, "Place container").click();
  await page.getByText(/Simulation complete.*1 placed/).waitFor();
  assert.deepEqual(await containerDetails(page), {...details, Status: "placed"});

  await button(page, "Add container").click();
  assert.equal(await textbox("Vessel").isVisible(), false);
  await textbox("Container ID").fill("QUICK-20");
  await select("Size").selectOption("20");
  await button(page, "Add to queue").click();
  await feedback(page, "QUICK-20 added to the inbound queue.").waitFor();
  assert.equal((await containerDetails(page)).Weight, "—");
});

test("the dummy option disables optional details and leaves drafted values for a regular container", async t => {
  const page = await openPreview(t, 0);
  const form = page.locator("#inbound-add-form");
  await button(page, "Add container").click();
  const identifier = form.getByRole("textbox", {name: "Container ID", exact: true});
  const size = form.getByRole("combobox", {name: "Size", exact: true});
  const dummy = form.getByRole("checkbox", {name: "Dummy container"});
  const optional = form.getByText("Container details (optional)", {exact: true});
  await identifier.fill("MANUAL");
  await size.selectOption("20");
  await optional.click();
  const vessel = form.getByRole("textbox", {name: "Vessel", exact: true});
  await vessel.fill("DRAFT");
  await dummy.check();
  assert.equal(await identifier.isDisabled(), true);
  assert.equal(await vessel.isDisabled(), true);
  assert.equal(await size.isEnabled(), true);
  await dummy.uncheck();
  assert.equal(await identifier.inputValue(), "MANUAL");
  assert.equal(await vessel.inputValue(), "DRAFT");
  assert.equal(await vessel.isEnabled(), true);
  await dummy.check();
  await button(page, "Add to queue").click();
  await feedback(page, "DUMMY-INBOUND-1 added to the inbound queue.").waitFor();
  const details = await containerDetails(page);
  assert.equal(details.Size, "20 ft");
  assert.equal(details.Vessel, "—");
  assert.equal(details.Source, "Dummy container");
});

test("using the selected 40 ft pair matches selecting its coordinate from the dropdowns", async t => {
  const page = await openPreview(t, 0);
  await button(page, "Add container").click();
  const form = page.locator("#inbound-add-form");
  await form.getByRole("textbox", {name: "Container ID", exact: true}).fill("ALT40");
  await form.getByRole("combobox", {name: "Size", exact: true}).selectOption("40");
  await button(page, "Add to queue").click();
  await feedback(page, "ALT40 added to the inbound queue.").waitFor();
  const status = page.locator(".simulation-outcome [role=status]");
  const recommendation = await status.textContent();

  await page.locator(".yard-trace-candidate.yard-trace-pair:not(.yard-trace-pair-anchor)").first().click();
  const selectedStack = page.locator('.yard-tile[aria-pressed="true"]');
  const selectedLabel = await selectedStack.getAttribute("aria-label");
  await button(page, "Use manual input").click();
  await page.getByRole("heading", {name: "Manual assignment", exact: true}).waitFor();
  assert.equal(await selectedStack.getAttribute("aria-label"), selectedLabel);
  const picker = page.locator("#alternate-location");
  const select = label => picker.getByRole("combobox", {name: label, exact: true});
  const autoTier = picker.getByRole("switch", {name: "Auto-select open tier"});
  const useSelected = button(page, "Use selected stack");
  const placeManual = button(page, "Place using manual input");
  assert.equal(await autoTier.isChecked(), true);
  assert.equal(await select("Tier").isDisabled(), true);
  assert.equal(await placeManual.isDisabled(), true);
  await autoTier.uncheck();
  await useSelected.click();
  await status.filter({hasText: "Alternate selected"}).waitFor();
  assert.equal(await autoTier.isChecked(), false);
  assert.equal(await select("Tier").isEnabled(), true);
  assert.equal(await useSelected.isDisabled(), true);
  assert.equal(await placeManual.isEnabled(), true);
  const preview = await status.textContent();
  assert.match(preview, /Slots \d+–\d+ · Tier \d+/);
  assert.equal(await page.locator(".yard-trace-winner").count(), 2);
  assert.equal(await page.locator(".yard-trace-winner.yard-trace-pair").count(), 2);
  assert.equal(await page.locator(".yard-trace-winner.yard-trace-pair-anchor").count(), 1);
  const [block, row, slot] = await Promise.all(["Block", "Row", "Slot"].map(label => select(label).inputValue()));
  await page.locator(".yard-trace-candidate.yard-trace-pair-anchor").first().click();
  assert.equal(await status.textContent(), preview);
  assert.deepEqual(await Promise.all(["Block", "Row", "Slot"].map(label => select(label).inputValue())), [block, row, slot]);
  assert.equal(await useSelected.isEnabled(), true);

  await button(page, "Use engine recommendation").click();
  await page.getByRole("heading", {name: "Suggested assignment", exact: true}).waitFor();
  assert.equal(await status.textContent(), recommendation);
  assert.equal(await picker.isVisible(), false);
  assert.equal(await button(page, "Place container").isVisible(), true);
  await button(page, "Use manual input").click();
  await select("Block").selectOption(block);
  await select("Row").selectOption(row);
  assert.equal(await placeManual.isDisabled(), true);
  await select("Slot").selectOption(slot);
  await status.filter({hasText: preview}).waitFor();
  assert.equal(await status.textContent(), preview);
  const coordinate = preview.split("Alternate selected · ")[1];
  const tier = await select("Tier").inputValue();
  await autoTier.uncheck();
  assert.equal(await select("Tier").isEnabled(), true);
  await select("Tier").selectOption("");
  assert.equal(await placeManual.isDisabled(), true);
  await select("Tier").selectOption(tier);

  await placeManual.click();
  await status.filter({hasText: "placed at alternate · " + coordinate}).waitFor();
  await page.getByText(/Engine recommendation · Block/).first().waitFor();
  await page.getByText("Alternate placement · " + coordinate, {exact: false}).first().waitFor();
  assert.equal(await picker.isVisible(), false);
  const highlighted = page.locator(".yard-trace-winner");
  assert.equal(await highlighted.count(), 1);
  assert.deepEqual(await highlighted.evaluate(tile => ({
    columns: tile.parentElement.colSpan,
    extension: getComputedStyle(tile, "::after").content,
    outlineColor: getComputedStyle(tile).outlineColor,
  })), {columns: 2, extension: "none", outlineColor: "rgb(99, 54, 176)"});

  await button(page, "Add container").click();
  await form.getByRole("textbox", {name: "Container ID", exact: true}).fill("USE20");
  await form.getByRole("combobox", {name: "Size", exact: true}).selectOption("20");
  await button(page, "Add to queue").click();
  await feedback(page, "USE20 added to the inbound queue.").waitFor();
  const leftSlot = Number(slot) - 1;
  const pair = "Slots " + String(leftSlot).padStart(2, "0") + "–" + String(slot).padStart(2, "0");
  const mergedTile = page.getByRole("button", {name: new RegExp("Block " + block + ", row " + row + ", " + pair)});
  await mergedTile.click({position: {x: 5, y: 5}});
  await page.getByText("40 ft stack · Selected slot " + String(leftSlot).padStart(2, "0"), {exact: true}).waitFor();
  await button(page, "Use manual input").click();
  await button(page, "Use selected stack").click();
  assert.equal(await select("Slot").inputValue(), String(leftSlot));
  assert.equal(await select("Tier").inputValue(), String(Number(tier) + 1));
});

test("a manual coordinate can replace an occupied tier after confirmation", async t => {
  const page = await openPreview(t, 1);
  await button(page, "Use manual input").click();
  const picker = page.locator("#alternate-location");
  const select = name => picker.getByRole("combobox", {name, exact: true});
  await select("Block").selectOption("A");
  await select("Row").selectOption("1");
  await select("Slot").selectOption("1");
  assert.equal(await select("Tier").inputValue(), "2");
  await picker.getByRole("switch", {name: "Auto-select open tier"}).uncheck();
  await select("Tier").selectOption("1");
  await picker.getByText("This placement would replace OLD.", {exact: true}).waitFor();

  page.once("dialog", dialog => dialog.dismiss());
  await button(page, "Place using manual input").click();
  assert.equal(await page.locator(".inbound-card.inbound-pending").count(), 1);
  page.once("dialog", async dialog => {
    assert.match(dialog.message(), /Replace OLD/);
    await dialog.accept();
  });
  await button(page, "Place using manual input").click();
  await page.getByText("Replaced OLD.", {exact: true}).waitFor();
  const placed = page.locator(".yard-placed");
  assert.match(await placed.getAttribute("aria-label"), /Block A, row 1, Slot 01/i);
  await page.getByText(/placed at alternate.*Tier 1/).waitFor();
});

test("manual placement warns about a mismatched size anywhere in the footprint", async t => {
  const page = await openPreview(t, 2, undefined, {firstSize: "40"});
  const picker = page.locator("#alternate-location");
  const select = name => picker.getByRole("combobox", {name, exact: true});
  const status = page.locator(".simulation-outcome [role=status]");
  const mismatch = picker.getByText(/Size mismatch/);
  async function selectStack(slot) {
    await button(page, "Use manual input").click();
    await select("Block").selectOption("A");
    await select("Row").selectOption("1");
    await select("Slot").selectOption(slot);
  }

  await selectStack("2");
  await mismatch.filter({hasText: /40 ft placement.*20 ft containers/}).waitFor();
  assert.equal(await select("Tier").inputValue(), "2");
  await select("Slot").selectOption("4");
  await status.filter({hasText: "Slots 3–4"}).waitFor();
  assert.equal(await mismatch.count(), 0);
  await select("Slot").selectOption("2");
  await button(page, "Place using manual input").click();
  await status.filter({hasText: "#2 NEW02"}).waitFor();

  await selectStack("2");
  await mismatch.filter({hasText: /20 ft placement.*40 ft containers/}).waitFor();
  await picker.getByRole("switch", {name: "Auto-select open tier"}).uncheck();
  await select("Tier").selectOption("2");
  assert.match(await mismatch.textContent(), /replace NEW01/);
});

test("manual equipment options follow the selected stack and the chosen loader moves", async t => {
  const page = await openPreview(t, 1, undefined, {equipmentChoices: "open"});
  await button(page, "Use manual input").click();
  const picker = page.locator("#alternate-location");
  const select = name => picker.getByRole("combobox", {name, exact: true});
  const equipment = select("Equipment");
  const codes = () => equipment.locator('option[value]:not([value=""])').allTextContents();
  assert.equal(await equipment.isDisabled(), true);
  await select("Block").selectOption("A");
  assert.equal(await equipment.isDisabled(), true);
  await select("Row").selectOption("1");
  await select("Slot").selectOption("1");
  await equipment.locator('option[value="RTG1"]').waitFor({state: "attached"});
  assert.deepEqual(await codes(), ["RTG1", "RS1", "SL1"]);
  await equipment.selectOption("RTG1");
  await select("Block").selectOption("B");
  assert.deepEqual(await codes(), []);
  assert.equal(await equipment.inputValue(), "");
  await select("Row").selectOption("2");
  await select("Slot").selectOption("2");
  await equipment.locator('option[value="RTG2"]').waitFor({state: "attached"});
  assert.deepEqual(await codes(), ["RTG2", "RS1", "SL1"]);
  const place = button(page, "Place using manual input");
  assert.equal(await place.isDisabled(), true);
  assert.equal(await button(page, "Run to end").isDisabled(), true);
  await page.getByRole("button", {name: /^Block B, row 2, Slot 02,/}).click();
  await button(page, "Use selected stack").click();
  await equipment.locator('option[value="RTG2"]:checked').waitFor({state: "attached"});
  assert.equal(await place.isEnabled(), true);
  await equipment.selectOption("SL1");
  assert.equal(await place.isEnabled(), true);
  await place.click();
  await page.getByText(/Alternate placement.*Manual override.*SL1/).waitFor();
  const block = code => page.locator(".yard-block").filter({has: page.getByRole("heading", {name: "Block " + code, exact: true})});
  await block("A").getByText("Equipment: RTG1, RS1", {exact: true}).waitFor();
  await block("B").getByText("Equipment: RTG2, SL1", {exact: true}).waitFor();
});

test("manual equipment refreshes as approaches change and allows a placement without equipment", async t => {
  const page = await openPreview(t, 1, undefined, {equipmentChoices: "blocked"});
  await button(page, "Use manual input").click();
  const picker = page.locator("#alternate-location");
  const select = name => picker.getByRole("combobox", {name, exact: true});
  const equipment = select("Equipment");
  const reachable = equipment.locator('optgroup[label="Can reach this stack"]');
  const blocked = equipment.locator('optgroup[label="Cannot reach this stack"]');
  const option = (group, code) => group.locator('option[value="' + code + '"]');
  await select("Block").selectOption("B");
  await select("Row").selectOption("1");
  await select("Slot").selectOption("2");
  await option(reachable, "RS1").waitFor({state: "attached"});
  assert.equal(await equipment.inputValue(), "RS1");
  assert.equal(await option(blocked, "SL1").evaluate(node => node.matches(":disabled")), true);

  await page.getByRole("button", {name: /^Block B, row 2, Slot 02,/}).click();
  page.once("dialog", dialog => dialog.accept());
  await button(page, "Remove top container").click();
  await option(reachable, "SL1").waitFor({state: "attached"});
  assert.equal(await option(reachable, "SL1").evaluate(node => node.matches(":enabled")), true);
  assert.equal(await equipment.inputValue(), "RS1");
  const block = page.locator(".yard-block").filter({has: page.getByRole("heading", {name: "Block B", exact: true})});
  for (const side of ["Below", "Left"]) {
    await block.getByRole("switch", {name: new RegExp(side + ".*border access", "i")}).click();
  }
  await picker.getByText("Manual override will place this container without equipment.", {exact: true}).waitFor();
  assert.equal(await equipment.isEnabled(), true);
  assert.equal(await equipment.inputValue(), "");
  assert.equal(await reachable.count(), 0);
  assert.equal(await option(blocked, "RS1").evaluate(node => node.matches(":disabled")), true);
  assert.equal(await option(blocked, "SL1").evaluate(node => node.matches(":disabled")), true);
  await button(page, "Place using manual input").click();
  await page.getByText(/Alternate placement.*Manual override.*No equipment/).waitFor();
  await block.getByText("Equipment: None", {exact: true}).waitFor();
});

test("yard edits refresh the recommendation and the selected manual tier", async t => {
  const page = await openPreview(t, 1, undefined, {firstId: "OLD"});
  await button(page, "Skip container").waitFor();
  const stack = page.getByRole("button", {name: /^Block A, row 1, Slot 01,/});
  await stack.click();
  page.once("dialog", dialog => dialog.accept());
  await button(page, "Remove top container").click();
  await button(page, "Place container").waitFor();
  assert.equal(await page.locator(".inbound-card.inbound-pending strong").textContent(), "OLD");

  await button(page, "Use manual input").click();
  await button(page, "Use selected stack").click();
  const picker = page.locator("#alternate-location");
  const tier = picker.getByRole("combobox", {name: "Tier", exact: true});
  assert.equal(await tier.inputValue(), "1");
  await button(page, "Add dummy container").click();
  await page.locator(".yard-stack-actions [role=status]").filter({hasText: "Dummy added"}).waitFor();
  assert.equal(await picker.isVisible(), true);
  assert.equal(await tier.inputValue(), "2");
  assert.match(await stack.getAttribute("aria-description"), /Rank \d+.*Tier 2/);

  page.once("dialog", dialog => dialog.accept());
  await button(page, "Remove top container").click();
  await page.locator(".yard-stack-actions [role=status]").filter({hasText: "Removed dummy container"}).waitFor();
  assert.equal(await picker.isVisible(), true);
  assert.equal(await tier.inputValue(), "1");
  assert.match(await stack.getAttribute("aria-description"), /Rank \d+.*Tier 1/);
  await button(page, "Place using manual input").click();
  await page.getByText(/placed at alternate.*Tier 1/).waitFor();
});

test("quick moves update the next assignment and preserve processed rows", async t => {
  const page = await openPreview(t, 4);
  const ids = cardIds(page);
  const front = button(page, "Move to front");
  const end = button(page, "Move to end");
  const suggestion = id => page.locator(".simulation-outcome [role=status]").filter({hasText: id});

  await button(page, "Place container").click();
  await suggestion("#2 NEW02").waitFor();
  const rankOne = page.locator('.yard-trace-winner[aria-pressed="true"] .yard-trace-rank');
  assert.equal(await rankOne.textContent(), "#1");
  assert.equal(await page.locator(".yard-placement-badge").count(), 0);
  const assignment = page.getByRole("combobox", {name: "View assignment"});
  await assignment.selectOption("0");
  assert.equal(await page.locator(".yard-placement-badge").count(), 1);
  await assignment.selectOption("current");
  assert.equal(await rankOne.textContent(), "#1");
  assert.equal(await page.locator(".yard-placement-badge").count(), 0);
  await ids.first().click();
  assert.equal(await front.isDisabled(), true);
  assert.equal(await end.isDisabled(), true);

  await ids.nth(1).click();
  assert.equal(await front.isDisabled(), true);
  await end.click();
  await feedback(page, "NEW02 moved to #4.").waitFor();
  await suggestion("#2 NEW03").waitFor();
  assert.deepEqual(await ids.allTextContents(), ["NEW01", "NEW03", "NEW04", "NEW02"]);
  assert.equal(await end.isDisabled(), true);

  await page.keyboard.press("Enter");
  assert.ok(await front.evaluate(element => element === document.activeElement));
  await page.keyboard.press("Enter");
  await feedback(page, "NEW02 moved to #2.").waitFor();
  await suggestion("#2 NEW02").waitFor();
  assert.deepEqual(await ids.allTextContents(), ["NEW01", "NEW02", "NEW03", "NEW04"]);
  assert.equal(await page.locator(".inbound-card.inbound-placed strong").textContent(), "NEW01");
});

test("dragging scrolls to both queue edges and drops at the updated insertion marker", async t => {
  const page = await openPreview(t, 18);
  const track = page.locator(".inbound-track");
  const ids = cardIds(page);
  const marker = track.locator("[data-drop-edge]");
  const clientScrollLeft = () => track.evaluate(element => element.scrollLeft);

  async function dragToEdge(card, side) {
    await card.scrollIntoViewIfNeeded();
    const source = await card.boundingBox();
    const bounds = await track.boundingBox();
    const y = source.y + source.height / 2;
    const edgeX = side === "right" ? bounds.x + bounds.width - 7 : bounds.x + 7;
    await page.mouse.move(source.x + source.width / 2, y);
    await page.mouse.down();
    await page.mouse.move(edgeX, y, {steps: 15});
    return {edgeX, top: bounds.y};
  }

  await dragToEdge(ids.first(), "right");
  await page.waitForFunction(() => {
    const track = document.querySelector(".inbound-track");
    return track.scrollLeft + track.clientWidth >= track.scrollWidth - 1;
  });
  assert.equal(await marker.getAttribute("data-drop-edge"), "after");
  assert.equal(await marker.locator("strong").textContent(), "NEW18");
  await page.mouse.up();
  await feedback(page, "NEW01 moved to #18.").waitFor();
  assert.equal(await ids.last().textContent(), "NEW01");

  await dragToEdge(ids.last(), "left");
  await page.waitForFunction(() => document.querySelector(".inbound-track").scrollLeft <= 1);
  assert.equal(await marker.getAttribute("data-drop-edge"), "before");
  assert.equal(await marker.locator("strong").textContent(), "NEW02");
  await page.mouse.up();
  await feedback(page, "NEW01 moved to #1.").waitFor();
  assert.equal(await ids.first().textContent(), "NEW01");

  const start = await clientScrollLeft();
  const {edgeX, top} = await dragToEdge(ids.first(), "right");
  await page.waitForFunction(start => document.querySelector(".inbound-track").scrollLeft > start + 100, start);
  await page.mouse.move(edgeX, top - 8, {steps: 3});
  await marker.waitFor({state: "detached"});
  const stopped = await clientScrollLeft();
  await page.mouse.up();
  assert.equal(await clientScrollLeft(), stopped);
  assert.equal(await ids.first().textContent(), "NEW01");
});
