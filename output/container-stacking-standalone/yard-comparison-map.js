"use strict";

const comparisonSlotLabels = {
  changed: "Different contents",
  simulated: "Occupied only in simulation",
  reference: "Occupied only in CSV",
  removed: "Removed slot",
  same: "Matching contents"
};

function comparisonBlockLayout(block) {
  const {rows, slots, simulated, reference, removed} = block.layout;
  const index = (row, slot) => (row - 1) * slots + slot - 1;
  const map = records => new Map(records.map(item => [index(item.row, item.slot), item.tiers]));
  const actual = map(simulated);
  const other = map(reference);
  const unavailable = new Set(removed.map(([row, slot]) => index(row, slot)));
  const differences = new Map();
  for (const cell of new Set([...actual.keys(), ...other.keys()])) {
    const first = actual.get(cell);
    const second = other.get(cell);
    if (!first) differences.set(cell, "reference");
    else if (!second) differences.set(cell, "simulated");
    else if (JSON.stringify(first) !== JSON.stringify(second)) differences.set(cell, "changed");
  }
  return {rows, slots, actual, other, unavailable, differences};
}

function comparisonStackInspector(block, row, slot, actual, reference, kind) {
  const panel = el("div");
  panel.append(el("h4", "Block " + block + " · Row " + row + " · Slot " + slot));
  if (kind === "removed" || (!actual.length && !reference.length)) {
    panel.append(el("p", kind === "removed" ? "Removed slot." : "This slot is empty in both snapshots."));
    return panel;
  }
  const actualByTier = new Map(actual.map(tier => [tier.tier, tier]));
  const referenceByTier = new Map(reference.map(tier => [tier.tier, tier]));
  const tiers = [...new Set([...actualByTier.keys(), ...referenceByTier.keys()])].sort((a, b) => b - a);
  const label = tier => tier?.dummy ? "Dummy tier" :
    tier ? tier.container + " · " + tier.size + " ft" : "Empty";
  const contents = table(["Tier", "Simulation", "Imported CSV"], tiers.map(tier => [
    tier, label(actualByTier.get(tier)), label(referenceByTier.get(tier))
  ]));
  for (const [index, tr] of [...contents.querySelectorAll("tbody tr")].entries()) {
    const tier = tiers[index];
    tr.classList.toggle("comparison-tier-different",
      JSON.stringify(actualByTier.get(tier)) !== JSON.stringify(referenceByTier.get(tier)));
  }
  panel.append(contents);
  return panel;
}

function comparisonSlotMap(block, layout) {
  const {rows, slots, actual, other, unavailable, differences} = layout;
  const root = el("div");
  const maps = el("div", undefined, "comparison-maps");
  const inspector = el("div", undefined, "comparison-stack-inspector");
  const coordinates = cell => [Math.floor(cell / slots) + 1, cell % slots + 1];
  const kindAt = cell => unavailable.has(cell) ? "removed" : differences.get(cell) ?? "same";
  const boards = [];
  let selected;

  function select(cell, focusBoard) {
    for (const {tiles} of boards) {
      if (selected !== undefined) {
        tiles[selected].tabIndex = -1;
        tiles[selected].setAttribute("aria-pressed", "false");
      }
      tiles[cell].tabIndex = 0;
      tiles[cell].setAttribute("aria-pressed", "true");
    }
    selected = cell;
    const [row, slot] = coordinates(cell);
    inspector.replaceChildren(comparisonStackInspector(block, row, slot,
      actual.get(cell) ?? [], other.get(cell) ?? [], kindAt(cell)));
    focusBoard?.tiles[cell].focus();
  }

  for (const [label, tiersByCell] of [["Simulation", actual], ["Imported CSV", other]]) {
    const board = el("div", undefined, "comparison-board");
    const viewport = el("div", undefined, "comparison-grid-scroll");
    const grid = el("table", undefined, "comparison-grid");
    grid.setAttribute("aria-label", label + " · Block " + block + " · rows and slots");
    const head = el("thead");
    const header = el("tr");
    const origin = el("th", "Row / slot");
    origin.scope = "col";
    header.append(origin);
    for (let slot = 1; slot <= slots; slot++) {
      const heading = el("th", slot);
      heading.scope = "col";
      header.append(heading);
    }
    head.append(header);
    const body = el("tbody");
    const tiles = [];
    const view = {viewport, tiles};
    boards.push(view);
    for (let row = 1; row <= rows; row++) {
      const tr = el("tr");
      const heading = el("th", row);
      heading.scope = "row";
      tr.append(heading);
      for (let slot = 1; slot <= slots; slot++) {
        const cell = (row - 1) * slots + slot - 1;
        const occupied = tiersByCell.get(cell)?.length ?? 0;
        const kind = kindAt(cell);
        const tile = el("button", kind === "removed" ? "—" : occupied, "comparison-slot comparison-slot-" + kind);
        tile.type = "button";
        tile.tabIndex = -1;
        tile.setAttribute("aria-pressed", "false");
        tile.setAttribute("aria-label", "Row " + row + ", slot " + slot + ", " + occupied +
          " occupied tiers. " + comparisonSlotLabels[kind] + ".");
        tile.addEventListener("click", () => select(cell));
        tile.addEventListener("keydown", event => {
          const next = {
            ArrowLeft: slot > 1 ? cell - 1 : cell,
            ArrowRight: slot < slots ? cell + 1 : cell,
            ArrowUp: row > 1 ? cell - slots : cell,
            ArrowDown: row < rows ? cell + slots : cell
          }[event.key];
          if (next === undefined) return;
          event.preventDefault();
          if (next !== cell) select(next, view);
        });
        tiles.push(tile);
        const td = el("td");
        td.append(tile);
        tr.append(td);
      }
      body.append(tr);
    }
    grid.append(head, body);
    viewport.append(grid);
    board.append(el("h5", label), viewport);
    maps.append(board);
  }
  for (const {viewport} of boards) {
    const otherViewport = boards.find(board => board.viewport !== viewport).viewport;
    viewport.addEventListener("scroll", () => {
      if (otherViewport.scrollLeft !== viewport.scrollLeft) otherViewport.scrollLeft = viewport.scrollLeft;
      if (otherViewport.scrollTop !== viewport.scrollTop) otherViewport.scrollTop = viewport.scrollTop;
    });
  }
  root.append(maps, inspector);
  select(differences.keys().next().value ?? 0);
  return root;
}

function yardComparisonMap(blocks) {
  const root = el("div", undefined, "comparison-visual");
  const layouts = blocks.map(comparisonBlockLayout);
  const toolbar = el("div", undefined, "comparison-map-toolbar");
  const label = el("label", "Block ");
  const picker = el("select");
  const legend = el("ul", undefined, "comparison-map-legend");
  for (const [index, block] of blocks.entries()) {
    const count = layouts[index].differences.size;
    const option = el("option", block.block + (count ? " · " + count + " changed" : ""));
    option.value = index;
    picker.append(option);
  }
  for (const [kind, text] of Object.entries(comparisonSlotLabels)) {
    const entry = el("li");
    entry.append(el("span", undefined, "comparison-swatch comparison-slot-" + kind), el("span", text));
    legend.append(entry);
  }
  label.append(picker);
  toolbar.append(label, legend);
  const view = el("div");
  function showBlock() {
    const index = Number(picker.value);
    view.replaceChildren(comparisonSlotMap(blocks[index].block, layouts[index]));
  }
  picker.addEventListener("change", showBlock);
  const firstChanged = layouts.findIndex(layout => layout.differences.size);
  picker.value = Math.max(0, firstChanged);
  root.append(el("h4", "Placement maps"), toolbar,
    el("p", "Numbers show occupied tiers. Select a slot to compare its contents.", "note"), view);
  showBlock();
  return root;
}
