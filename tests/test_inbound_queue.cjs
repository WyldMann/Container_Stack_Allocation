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

function scenarioDraft(count) {
  return JSON.parse(execFileSync(python, ["-B", "-c", [
    "import json, sys",
    "from tests.test_stacking_scenario import ScenarioTests",
    "scenario = ScenarioTests()",
    "scenario.setUp()",
    "scenario.rows['inbound_containers'] = [dict(container_id=f'NEW{i:02d}', container_size='20')",
    "    for i in range(1, int(sys.argv[1]) + 1)]",
    "scenario.write_files()",
    "print(json.dumps(scenario.payload | {'version': 1, 'file_source': 'upload'}))"
  ].join("\n"), String(count)], {cwd: root, encoding: "utf8"}));
}

async function openPreview(t, count, viewport = {width: 1200, height: 900}) {
  const draft = scenarioDraft(count);
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
    ["stepStackingSimulation", "step"],
    ["addStackingQueueRow", "add_queue_row"],
    ["reorderStackingQueue", "reorder_queue"],
    ["deleteStackingQueueRow", "delete_queue_row"]
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

test("a highlighted 40 ft pair and coordinate dropdowns select the same alternate placement", async t => {
  const page = await openPreview(t, 0);
  await button(page, "Add container").click();
  const form = page.locator("#inbound-add-form");
  await form.getByRole("textbox", {name: "Container ID", exact: true}).fill("ALT40");
  await form.getByRole("combobox", {name: "Size", exact: true}).selectOption("40");
  await button(page, "Add to queue").click();
  await feedback(page, "ALT40 added to the inbound queue.").waitFor();
  const status = page.locator(".simulation-outcome [role=status]");
  const recommendation = await status.textContent();

  await button(page, "Choose alternate location").click();
  const picker = page.locator("#alternate-location");
  const select = label => picker.getByRole("combobox", {name: label, exact: true});
  assert.equal(await button(page, "Place container").isVisible(), true);
  await page.locator(".yard-trace-candidate.yard-trace-pair:not(.yard-trace-pair-anchor)").first().click();
  await status.filter({hasText: "Alternate selected"}).waitFor();
  const preview = await status.textContent();
  assert.match(preview, /Slots \d+–\d+ · Tier \d+/);
  assert.equal(await page.locator(".yard-trace-winner").count(), 2);
  const [block, row, slot] = await Promise.all(["Block", "Row", "Slot"].map(label => select(label).inputValue()));

  await button(page, "Use engine recommendation").click();
  assert.equal(await status.textContent(), recommendation);
  assert.equal(await picker.isVisible(), false);
  assert.equal(await button(page, "Place container").isVisible(), true);
  await button(page, "Choose alternate location").click();
  await select("Block").selectOption(block);
  await select("Row").selectOption(row);
  await select("Slot").selectOption(slot);
  assert.equal(await status.textContent(), preview);
  const coordinate = preview.split("Alternate selected · ")[1];

  await button(page, "Place at manual location").click();
  await status.filter({hasText: "placed at alternate · " + coordinate}).waitFor();
  await page.getByText(/Engine recommendation · Block/).first().waitFor();
  await page.getByText("Alternate placement · " + coordinate, {exact: false}).first().waitFor();
  assert.equal(await picker.isVisible(), false);
});

test("a manual coordinate can replace an occupied tier after confirmation", async t => {
  const page = await openPreview(t, 1);
  await button(page, "Choose alternate location").click();
  const picker = page.locator("#alternate-location");
  const select = name => picker.getByRole("combobox", {name, exact: true});
  await select("Block").selectOption("A");
  await select("Row").selectOption("1");
  await select("Slot").selectOption("1");
  await select("Tier").selectOption("1");
  await picker.getByText("This placement would replace OLD.", {exact: true}).waitFor();

  page.once("dialog", dialog => dialog.dismiss());
  await button(page, "Place at manual location").click();
  assert.equal(await page.locator(".inbound-card.inbound-pending").count(), 1);
  page.once("dialog", async dialog => {
    assert.match(dialog.message(), /Replace OLD/);
    await dialog.accept();
  });
  await button(page, "Place at manual location").click();
  await page.getByText("Replaced OLD.", {exact: true}).waitFor();
  const placed = page.locator(".yard-placed");
  assert.match(await placed.getAttribute("aria-label"), /Block A, row 1, Slot 01/i);
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
