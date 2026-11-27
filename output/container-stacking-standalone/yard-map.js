"use strict";

function layoutYardBlocks(blocks) {
  const gap = 22;
  const padding = 16;
  if (!blocks.length) return {rectangles: [], width: padding * 2, height: padding * 2};

  const groups = new Map();
  for (const block of blocks) {
    const key = block.x + "," + block.y;
    if (!groups.has(key)) groups.set(key, {x: block.x, y: block.y, blocks: []});
    const group = groups.get(key);
    // Each 20 ft slot is 90 × 36 px (20:8), with a 3 px grid gap.
    const width = Math.max(270, 144 + block.slots * 93);
    const height = 224 + block.rows * 39;
    group.blocks.push({block, width, height});
  }

  const positions = [...groups.values()];
  // Infer alignment from typical neighboring coordinates, so small offsets do
  // not manufacture extra rows/columns and a distant outlier cannot set the scale.
  const nearest = positions.map((group, index) => positions.reduce((distance, other, otherIndex) =>
    index === otherIndex ? distance : Math.min(distance, Math.hypot(group.x - other.x, group.y - other.y)), Infinity));
  nearest.sort((a, b) => a - b);
  const tolerance = positions.length > 1 ? nearest[Math.floor((nearest.length - 1) / 2)] * 0.15 : 0;
  function bands(axis) {
    const values = [...new Set(positions.map(group => group[axis]))].sort((a, b) => a - b);
    const indices = new Map();
    let start = values[0];
    let index = 0;
    for (const value of values) {
      if (value - start > tolerance) {
        start = value;
        index++;
      }
      indices.set(value, index);
    }
    return indices;
  }
  const columns = bands("x");
  const rows = bands("y");
  const cells = new Map();
  for (const group of positions) {
    const column = columns.get(group.x);
    const row = rows.get(group.y);
    const key = column + "," + row;
    if (!cells.has(key)) cells.set(key, {column, row, blocks: []});
    cells.get(key).blocks.push(...group.blocks);
  }

  // Blocks sharing a schematic position form a compact cluster. Tallest-first
  // shelves keep that cluster stable without making a long vertical list.
  for (const cell of cells.values()) {
    cell.blocks.sort((a, b) => b.height - a.height || b.width - a.width ||
      String(a.block.code).localeCompare(String(b.block.code), "en", {numeric: true}));
    const area = cell.blocks.reduce((total, item) => total + item.width * item.height, 0);
    const targetWidth = Math.max(...cell.blocks.map(item => item.width), Math.sqrt(area * 1.25));
    const shelves = [];
    cell.width = 0;
    cell.height = 0;
    for (const item of cell.blocks) {
      let shelf = shelves.find(candidate => candidate.width + gap + item.width <= targetWidth);
      if (!shelf) {
        shelf = {top: shelves.length ? cell.height + gap : 0, width: 0, height: item.height};
        shelves.push(shelf);
        cell.height = shelf.top + shelf.height;
      }
      item.left = shelf.width ? shelf.width + gap : 0;
      item.top = shelf.top;
      shelf.width = item.left + item.width;
      cell.width = Math.max(cell.width, shelf.width);
    }
  }

  const ordered = [...cells.values()].sort((a, b) => a.row - b.row || a.column - b.column);
  const rowCells = [];
  for (const cell of ordered) {
    rowCells[cell.row] ??= [];
    cell.previous = rowCells[cell.row].at(-1);
    rowCells[cell.row].push(cell);
  }
  const columnCount = Math.max(...columns.values()) + 1;
  const columnCells = Array.from({length: columnCount}, (_, column) =>
    ordered.filter(cell => cell.column === column));
  function arrange(columnStep) {
    // Align columns across rows, adding panel widths only where two cells must
    // sit beside one another. Coordinate distances do not affect these gaps.
    let left = 0;
    for (const members of columnCells) {
      if (members[0].column) left += columnStep;
      for (const cell of members) {
        if (cell.previous) left = Math.max(left, cell.previous.left + cell.previous.width + gap);
      }
      for (const cell of members) cell.left = left;
    }

    // Compact rows against panels that actually overlap horizontally; a tall
    // panel in another column should not create an empty band across the map.
    let top = 0;
    const placed = [];
    for (const members of rowCells) {
      if (placed.length) top += gap;
      for (const cell of members) {
        for (const other of placed) {
          if (cell.left < other.left + other.width + gap && cell.left + cell.width + gap > other.left) {
            top = Math.max(top, other.top + other.height + gap);
          }
        }
      }
      for (const cell of members) cell.top = top;
      placed.push(...members);
    }

    const rectangles = ordered.flatMap(cell => cell.blocks.map(({block, width, height, left, top}) => ({
      block, width, height,
      left: padding + cell.left + left,
      top: padding + cell.top + top,
    })));
    return {
      rectangles,
      width: Math.ceil(Math.max(...rectangles.map(item => item.left + item.width)) + padding),
      height: Math.ceil(Math.max(...rectangles.map(item => item.top + item.height)) + padding),
    };
  }

  // A little horizontal room can prevent a much taller map. Choose a compact
  // fit for a typical map viewport, independent of occupancy or screen resizing.
  const aspect = 1.25;
  const step = Math.sqrt(ordered.reduce((area, cell) => area + cell.width * cell.height, 0) * aspect) / columnCount;
  const layouts = [gap, ...[0.5, 1, 1.5, 2].map(factor => Math.max(gap, step * factor))].map(arrange);
  layouts.sort((a, b) => Math.max(a.width / aspect, a.height) - Math.max(b.width / aspect, b.height) ||
    a.width * a.height - b.width * b.height);
  return layouts[0];
}

function blockStackingStartEditor(block, onChange) {
  const fields = el("fieldset", undefined, "yard-stacking-start-fields");
  fields.append(el("legend", "Start stacking from"));
  const enabled = el("input");
  enabled.type = "checkbox";
  enabled.setAttribute("role", "switch");
  const toggle = el("span", undefined, "toml-switch");
  const track = el("span", undefined, "toml-switch-track");
  track.setAttribute("aria-hidden", "true");
  toggle.append(enabled, track);
  const enabledLabel = el("label", "Prefer this row or slot", "yard-stacking-start-toggle");
  enabledLabel.append(toggle);
  fields.append(enabledLabel);
  const mode = el("select");
  for (const [value, label] of [["row", "Row"], ["slot", "Slot"]]) {
    const option = el("option", label);
    option.value = value;
    mode.append(option);
  }
  const position = el("input");
  position.type = "number";
  position.min = "1";
  position.step = "1";
  position.required = true;
  const half = el("input");
  half.type = "number";
  half.min = "0";
  half.step = "any";
  const options = el("div", undefined, "yard-stacking-start-options");
  for (const [label, input] of [["Preference", mode], ["Start number", position], ["Distance for half score", half]]) {
    const field = el("label", label);
    field.append(input);
    options.append(field);
  }
  fields.append(options);
  const effectiveLabel = el("p", undefined, "yard-caption");
  effectiveLabel.setAttribute("aria-live", "polite");
  const feedback = el("p", undefined, "yard-settings-feedback not-ready");
  feedback.setAttribute("role", "status");
  const graph = createPlacementGraphs(path => {
    const {override, effective, error, half_distance_if_blank} = block.stacking_start;
    const {axis, position, half_distance} = error ? effective : override ?? effective;
    if (path === stackingStartAxisPath) return JSON.stringify(axis);
    if (path === stackingStartPositionPath) return String(position);
    if (path === stackingStartHalfDistancePath) return String(half_distance ?? half_distance_if_blank);
  }, ["stackingStart"]).stackingStart;

  function updateLimits() {
    position.max = String(mode.value === "row" ? block.rows : block.slots);
  }

  function sync() {
    const {override, effective, error, half_distance_if_blank} = block.stacking_start;
    enabled.checked = override?.enabled === true;
    mode.value = override?.axis === "slot" ? "slot" : "row";
    position.value = override?.position ?? 1;
    half.value = override?.half_distance ?? "";
    half.placeholder = String(half_distance_if_blank);
    options.classList.toggle("is-scoring-off", !effective.enabled);
    effectiveLabel.textContent = effective.enabled ? "Active preference · " + stackingStartLabel(effective) :
      "Scoring is off for this block.";
    feedback.textContent = error ?? "";
    updateLimits();
    graph.update();
  }

  async function commit() {
    if (!position.checkValidity()) {
      enabled.checked = block.stacking_start.override?.enabled === true;
      feedback.textContent = "Choose a whole number from 1 to " + position.max + ".";
      return;
    }
    if (!half.checkValidity() || (half.value && !(half.valueAsNumber > 0))) {
      enabled.checked = block.stacking_start.override?.enabled === true;
      feedback.textContent = "Enter a positive half-score distance or leave it blank to use 2.";
      return;
    }
    const preference = {axis: mode.value, position: position.valueAsNumber,
      half_distance: half.value ? half.valueAsNumber : null, enabled: enabled.checked};
    await onChange(preference, sync, text => {
      enabled.checked = block.stacking_start.override?.enabled === true;
      feedback.textContent = text;
    });
  }

  enabled.addEventListener("change", commit);
  mode.addEventListener("change", () => {
    updateLimits();
    if (!position.checkValidity()) position.value = "1";
    commit();
  });
  position.addEventListener("change", commit);
  half.addEventListener("change", commit);
  sync();
  return {fields, effectiveLabel, feedback, graph};
}

function createYardMap(branch, branches = [branch], accessOptions = {}) {
  if (!branch.yard_map?.blocks?.length) return null;

  const colors = new Map([
    ["33", ["#dceafa", "#285a8e"]],
    ["35", ["#eee4fa", "#664189"]],
    ["38", ["#d9efe6", "#235f4c"]],
  ]);
  const palette = [
    ["#f4e2e1", "#854a47"], ["#d9eef3", "#256072"], ["#f6e6cc", "#7f4d16"],
    ["#e9ead4", "#5e6126"], ["#f5e0ef", "#82416d"], ["#dfe9ff", "#3d5591"],
  ];
  function occupancyColor(rate) {
    const red = Math.round(185 * Math.max(0, Math.min(rate, 1)));
    return "rgb(" + red + ", 0, 0)";
  }

  const ids = [...new Set(branches.flatMap(item => Object.keys(item.yard_map?.parameters ?? {})))].sort();
  ids.filter(id => !colors.has(id)).forEach((id, index) => colors.set(id, palette[index % palette.length]));

  const root = el("div", undefined, "yard-view");
  const header = el("div", undefined, "yard-view-heading");
  header.append(el("h3", "Yard map"));
  const body = el("div", undefined, "yard-view-layout");
  root.append(header, body);
  const borderControls = new Map();
  const accessSides = [["above", "Above"], ["below", "Below"], ["left", "Left"], ["right", "Right"]];
  const accessStatus = el("p", undefined, "yard-caption yard-access-status");
  accessStatus.setAttribute("role", "status");
  accessStatus.hidden = true;
  header.append(accessStatus);
  let accessEditable = Boolean(accessOptions.editable);
  let accessPending = false;
  let activeSettings;
  function settingsChanged(block) {
    const start = block.stacking_start?.override;
    const savedStart = block.saved_stacking_start;
    return accessSides.some(([side]) => block.border_access[side] !== block.saved_border_access[side]) ||
      start?.axis !== savedStart?.axis || start?.position !== savedStart?.position ||
      start?.half_distance !== savedStart?.half_distance || start?.enabled !== savedStart?.enabled;
  }
  function syncAccessControls() {
    for (const controls of borderControls.values()) controls.forEach(control => control.setLocked());
    activeSettings?.sync();
  }
  function accessMessage(text, error = false) {
    accessStatus.textContent = text;
    accessStatus.hidden = !text;
    accessStatus.classList.toggle("not-ready", error);
  }
  function showAccessChanges() {
    const codes = branch.yard_map.blocks.filter(settingsChanged).map(block => block.code)
      .sort((first, second) => first.localeCompare(second, "en", {numeric: true}));
    const names = new Intl.ListFormat("en", {style: "long", type: "conjunction"}).format(codes);
    accessMessage(codes.length ? (codes.length === 1 ? "Block " : "Blocks ") + names +
      (codes.length === 1 ? " has" : " have") + " unsaved settings." : "");
  }
  function button(label, className) {
    const control = el("button", undefined, className);
    control.type = "button";
    control.setAttribute("aria-label", label);
    return control;
  }

  async function changeBlockSettings(change, report = accessMessage) {
    if (accessPending || busy) return;
    accessPending = true;
    syncAccessControls();
    try {
      await action(async () => {
        await change();
        showAccessChanges();
      }, report);
    } finally {
      accessPending = false;
      syncAccessControls();
    }
  }

  function borderSwitch(block, side, label, positioned = false) {
    const toggle = button("Block " + block.code + " " + side + " border access",
      "yard-access-switch" + (positioned ? " yard-access-" + side : ""));
    toggle.setAttribute("role", "switch");
    const direction = el("span", label, "yard-access-direction");
    const lock = el("span", undefined, "yard-access-lock");
    lock.setAttribute("aria-hidden", "true");
    direction.append(lock);
    function paint() {
      const open = block.border_access[side];
      toggle.setAttribute("aria-checked", String(open));
      toggle.replaceChildren(direction, el("strong", open ? "Open" : "Closed"));
      const use = side === "above" || side === "below" ? "ground equipment entry and exterior working space" :
        "ground equipment entry and, when 20 ft side access is enabled, exterior reach stacker working space";
      toggle.title = label + " border is " + (open ? "open" : "closed") + " for " + use + ".";
    }
    function setLocked() {
      toggle.disabled = !accessEditable || accessPending;
      toggle.dataset.accessLocked = String(!accessEditable);
      if (accessEditable) toggle.removeAttribute("aria-description");
      else toggle.setAttribute("aria-description", "Block access is locked.");
    }
    toggle.addEventListener("click", () => {
      if (!accessEditable) return;
      return changeBlockSettings(async () => {
        const next = !block.border_access[side];
        await accessOptions.onChange(block, side, next);
        block.border_access[side] = next;
        borderControls.get(block.id).forEach(control => control.paint());
        activeSettings?.paintBorders();
      }, activeSettings?.report);
    });
    paint();
    return {toggle, paint, setLocked};
  }

  function openBlockSettings(block) {
    const title = "Block " + block.code + " settings";
    const dialog = el("dialog", undefined, "yard-block-settings");
    dialog.setAttribute("aria-label", title);
    const lock = el("p", "Block settings are locked for this run. Generate a fresh preview to edit them.", "yard-caption");
    const borders = el("fieldset", undefined, "yard-settings-borders");
    borders.append(el("legend", "Border access"));
    const switches = accessSides.map(([side, label]) => borderSwitch(block, side, label));
    borders.append(...switches.map(control => control.toggle));
    const status = el("p", undefined, "yard-settings-feedback");
    status.setAttribute("role", "status");
    const close = button("Close", "secondary");
    close.textContent = "Close";
    const save = button("Save block settings", "yard-block-save");
    save.textContent = "Save block settings";
    const actions = el("div", undefined, "actions");
    actions.append(close, save);
    const report = (text, error = false) => {
      status.textContent = text;
      status.classList.toggle("not-ready", error);
    };
    const start = block.stacking_start && blockStackingStartEditor(block, (preference, sync, reportError) => {
      if (!accessEditable || !accessOptions.onStackingStart) return;
      return changeBlockSettings(async () => {
        block.stacking_start = await accessOptions.onStackingStart(block, preference);
        sync();
      }, reportError);
    });
    dialog.append(el("h4", title), lock, borders);
    if (start) dialog.append(start.fields, start.effectiveLabel, start.feedback, start.graph.element);
    dialog.append(status, actions);
    activeSettings = {report, paintBorders: () => switches.forEach(control => control.paint()), sync() {
      lock.hidden = accessEditable;
      switches.forEach(control => control.setLocked());
      if (start) start.fields.disabled = !accessEditable || accessPending || !accessOptions.onStackingStart;
      const canSave = accessOptions.onSave && settingsChanged(block);
      save.disabled = accessPending || !canSave;
      save.dataset.accessLocked = String(!canSave);
      save.title = canSave ? (globalThis.stackingStandalone ? "Save to bundled data in this browser." : "Save to the project CSV.") :
        "No block settings changes to save.";
    }};
    close.addEventListener("click", () => dialog.close());
    dialog.addEventListener("cancel", event => { if (accessPending) event.preventDefault(); });
    dialog.addEventListener("close", () => {
      start?.graph.disconnect();
      dialog.remove();
      activeSettings = undefined;
    });
    save.addEventListener("click", () => changeBlockSettings(async () => {
      await accessOptions.onSave(block);
      block.saved_border_access = {...block.border_access};
      block.saved_stacking_start = block.stacking_start?.override ?? null;
      report("Saved settings for block " + block.code + ".");
    }, report));
    root.append(dialog);
    activeSettings.sync();
    dialog.showModal();
  }

  function paint(mark, ids) {
    const tones = ids.map(id => colors.get(id)).filter(Boolean);
    if (!tones.length) return;
    mark.style.setProperty("--yard-fill", tones[0][0]);
    mark.style.setProperty("--yard-ink", tones[0][1]);
    if (tones.length > 1) {
      const stops = tones.map(([fill], index) =>
        fill + " " + (100 * index / tones.length) + "% " + (100 * (index + 1) / tones.length) + "%");
      mark.style.backgroundImage = "linear-gradient(90deg," + stops.join(",") + ")";
    }
  }

  const two = number => String(number).padStart(2, "0");
  const branchLabel = branch => branch.branch_code + (branch.branch_name ? " · " + branch.branch_name : "");
  const parameterLabel = (id, parameter) => "P" + id + (parameter?.name ? " · " + parameter.name : "");
  const slotLabel = (stack, partner) => partner ?
    "Slots " + two(partner.slot) + "–" + two(stack.slot) : "Slot " + two(stack.slot);
  const assignedParameters = (stack, partner) => partner ?
    [...new Set([...partner.parameters, ...stack.parameters])] : stack.parameters;

  const stackActions = el("div", undefined, "yard-stack-actions");
  const addDummy = el("button", "Add dummy container", "secondary");
  addDummy.type = "button";
  const dummySize = el("select");
  dummySize.setAttribute("aria-label", "Dummy container size");
  for (const [value, label] of [["auto", "20ft/Auto"], ["40", "40 ft"]]) {
    const option = el("option", label);
    option.value = value;
    dummySize.append(option);
  }
  const dummyAdd = el("div", undefined, "actions yard-dummy-add");
  dummyAdd.append(addDummy, dummySize);
  const dummyAvailability = el("small", undefined, "yard-caption");
  dummyAvailability.setAttribute("aria-live", "polite");
  dummyAvailability.hidden = true;
  const removeTop = el("button", "Remove top container", "secondary");
  removeTop.type = "button";
  const stackStatus = el("p", undefined, "yard-caption");
  stackStatus.setAttribute("role", "status");
  stackStatus.hidden = true;
  if (accessOptions.onAddDummy) stackActions.append(dummyAdd, dummyAvailability);
  if (accessOptions.onRemoveTop) stackActions.append(removeTop);
  stackActions.append(stackStatus);

  function reportStackEdit(text, error = false) {
    stackStatus.textContent = text;
    stackStatus.hidden = !text;
    stackStatus.classList.toggle("not-ready", error);
  }

  async function editSelectedStack(control, edit, message) {
    const restoreFocus = document.activeElement === control;
    await action(async () => {
      const placed = await edit();
      applyPlacement(placed);
      if (accessOptions.onStackEdit) await accessOptions.onStackEdit();
      else selectStack(selection.view, selection.index);
      const slots = placed.stacks.length === 2 ?
        "Slots " + two(placed.slot - 1) + "–" + two(placed.slot) : "Slot " + two(placed.slot);
      reportStackEdit(message + " · " + placed.block + " · Row " + two(placed.row) + " · " + slots + " · Tier " + placed.tier);
    }, reportStackEdit);
    if (restoreFocus && root.isConnected) {
      const target = control.disabled || !control.isConnected ? selection.view.tiles[selection.index] : control;
      target.focus({preventScroll: true});
    }
  }

  addDummy.addEventListener("click", () => {
    if (accessPending || busy || addDummy.disabled) return;
    return editSelectedStack(addDummy, () => accessOptions.onAddDummy({
      ...selectedLocation(), size: dummySize.value === "40" ? "40" : null
    }), "Dummy added");
  });
  dummySize.addEventListener("change", () => {
    const {view, index} = selection;
    reportStackEdit("");
    syncDummyAction(view.block, view.block.stacks[index]);
  });
  removeTop.addEventListener("click", () => {
    if (accessPending || busy || removeTop.disabled) return;
    const {view, index} = selection;
    const top = view.block.stacks[index].tiers.at(-1);
    if (!top) return;
    const label = top.dummy ? (top.size === "40" ? "40 ft dummy container" : "dummy container") : top.container_id;
    if (!window.confirm("Remove " + label + " from tier " + top.tier + " in this yard preview?")) return;
    return editSelectedStack(removeTop, () => accessOptions.onRemoveTop({
      ...selectedLocation(), tier: top.tier, container_id: top.container_id ?? null
    }), "Removed " + label);
  });

  function syncDummyAction(block, stack) {
    const top = stack.tiers.at(-1);
    const height = top?.tier ?? 0;
    let reason = "";
    if (stack.removed) reason = "This stack is removed.";
    else if (height >= stack.capacity) reason = "There is no tier available above this stack.";
    else if (dummySize.value === "40" || top?.size === "40") {
      const partnerSlot = stack.slot % 2 ? stack.slot + 1 : stack.slot - 1;
      const partner = partnerSlot <= block.slots ? block.stacks[(stack.row - 1) * block.slots + partnerSlot - 1] : null;
      if (!partner || partner.removed) reason = "Select a complete, active slot pair.";
      else if ((partner.tiers.at(-1)?.tier ?? 0) !== height) reason = "Both slots need the same stack height.";
      else if (height >= partner.capacity) reason = "The paired slot has no tier available above it.";
    }
    addDummy.disabled = Boolean(reason);
    addDummy.dataset.accessLocked = String(addDummy.disabled);
    addDummy.title = reason;
    dummyAvailability.textContent = dummySize.value === "40" ? reason : "";
    dummyAvailability.hidden = !dummyAvailability.textContent;
  }

  function appendStackActions(panel, block, stack) {
    if (!accessOptions.onAddDummy && !accessOptions.onRemoveTop) return;
    syncDummyAction(block, stack);
    removeTop.disabled = !stack.tiers.length;
    removeTop.dataset.accessLocked = String(removeTop.disabled);
    panel.append(stackActions);
  }

  function renderInspector(panel, block, stack, partner, selectedStack, placed, traceEntries) {
    const heading = el("div", undefined, "yard-inspector-heading");
    const extra = Math.max(0, stack.tiers.length - stack.capacity);
    const occupancy = el("span", stack.removed ? "Removed · " + stack.tiers.length + " occupied" :
      stack.tiers.length + " of " + stack.capacity + " occupied", "yard-occupancy");
    occupancy.classList.toggle("yard-overcapacity", extra > 0);
    heading.append(el("h4", "Stack details"), occupancy);
    panel.replaceChildren(heading, el("p", block.code + " · Row " + two(stack.row) + " · " +
      slotLabel(stack, partner), "yard-caption"));
    if (placed) {
      panel.append(el("p", "Just placed " + placed.container_id + " at tier " + placed.tier, "yard-placement-note"));
    }
    if (traceEntries) {
      panel.append(el("h4", "Assignment trace"));
      for (const {description, breakdown} of traceEntries) {
        panel.append(el("p", description, "yard-trace-detail"));
        if (breakdown) panel.append(heuristicTable(breakdown));
      }
    }
    if (stack.anomaly) panel.append(el("p", "Tier gap below an occupied position.", "yard-gap-note"));
    if (extra) panel.append(el("p", "Over capacity by " + extra + (extra === 1 ? " tier." : " tiers."),
      "yard-overcapacity"));
    const footprint = stack.tiers.find(tier => tier.size === "40");
    if (partner) panel.append(el("p", "40 ft stack · Selected slot " + two(selectedStack.slot), "yard-caption"));
    else if (footprint) panel.append(el("p", "40 ft footprint · Slots " +
      two(footprint.anchor_slot - 1) + "-" + two(footprint.anchor_slot), "yard-caption"));

    panel.append(el("h4", "Assigned parameters"));
    const assigned = assignedParameters(stack, partner);
    if (!assigned.length) panel.append(el("p", "No parameter assigned.", "yard-caption"));
    for (const id of assigned) {
      const parameter = parameters[id];
      const detail = el("details", undefined, "yard-parameter");
      detail.open = assigned.length === 1;
      const inAnchor = stack.parameters.includes(id);
      const suffix = partner && inAnchor !== partner.parameters.includes(id) ?
        " · Slot " + two(inAnchor ? stack.slot : partner.slot) : "";
      const summary = el("summary", parameterLabel(id, parameter) + suffix);
      paint(summary, [id]);
      const rules = el("ul");
      for (const criterion of parameter?.criteria ?? []) {
        const points = parameter.and_score == null ? " · " + criterion.points + " pts" : "";
        rules.append(el("li", criterion.label + " · " + criterion.value + points));
      }
      if (parameter?.and_score != null) rules.append(el("li", "All criteria match · " + parameter.and_score + " pts"));
      if (!rules.children.length) rules.append(el("li", "No criteria recorded."));
      detail.append(summary, rules);
      panel.append(detail);
    }
    if (stack.removed && !stack.tiers.length) {
      appendStackActions(panel, block, selectedStack);
      return;
    }

    panel.append(el("h4", "Tier contents"));
    const tiers = new Map(stack.tiers.map(tier => [tier.tier, tier]));
    const highestTier = stack.tiers.reduce((highest, tier) => Math.max(highest, tier.tier), stack.capacity);
    const rows = [];
    for (let number = highestTier; number >= 1; number--) {
      const tier = tiers.get(number);
      if (!tier || tier.dummy) {
        rows.push([number, tier ? "Dummy container" : "Empty", tier?.size === "40" ? "40 ft" : "—",
          "—", "—", "—", "—"]);
        continue;
      }
      rows.push([
        number, tier.container_id, tier.size + " ft", {F: "Full", E: "Empty"}[tier.fill] ?? tier.fill,
        tier.operation || "—", tier.grade, tier.weight == null ? "—" : tier.weight.toLocaleString(),
      ]);
    }
    const contents = table(["Tier", "Container", "Size", "Fill", "Operation", "Grade", "Weight"], rows);
    contents.classList.add("yard-tier-table");
    if (placed) contents.querySelectorAll("tbody tr")[highestTier - placed.tier].classList.add("yard-placed-tier");
    panel.append(contents);
    if (stack.tiers.some(tier => tier.weight != null)) {
      panel.append(el("p", "Weight values use the source units.", "yard-caption"));
    }
    appendStackActions(panel, block, selectedStack);
  }

  const {blocks, parameters} = branch.yard_map;
  const {rectangles, width, height} = layoutYardBlocks(blocks);
  const mapPanel = el("div", undefined, "yard-panel");
  const toolbar = el("div", undefined, "yard-map-toolbar");
  const legend = el("div", undefined, "yard-legend");
  legend.setAttribute("aria-label", "Map legend");
  const controls = el("div", undefined, "yard-map-controls");
  const zoomOut = button("Zoom out", "yard-map-zoom-button");
  zoomOut.textContent = "−";
  const zoomSlider = el("input", undefined, "yard-map-zoom-slider");
  zoomSlider.type = "range";
  zoomSlider.max = "200";
  zoomSlider.step = "any";
  zoomSlider.setAttribute("aria-label", "Yard map zoom");
  const zoomIn = button("Zoom in", "yard-map-zoom-button");
  zoomIn.textContent = "+";
  const zoomLevel = el("output", undefined, "yard-map-zoom-level");
  zoomLevel.setAttribute("aria-live", "off");
  controls.append(zoomOut, zoomSlider, zoomIn, zoomLevel);
  toolbar.append(legend, controls);
  const traceKey = el("div", undefined, "yard-trace-key");
  traceKey.hidden = true;

  const viewport = el("div", undefined, "yard-map-scroll");
  viewport.setAttribute("role", "region");
  viewport.setAttribute("aria-label", "Top-down yard map");
  viewport.tabIndex = 0;
  viewport.style.setProperty("--yard-map-height", height + 2 + "px");
  const extent = el("div", undefined, "yard-map-extent");
  const stage = el("div", undefined, "yard-map-stage");
  stage.style.width = width + "px";
  stage.style.height = height + "px";
  extent.append(stage);
  viewport.append(extent);
  mapPanel.append(toolbar, traceKey, viewport);
  const inspector = el("div", undefined, "yard-panel yard-inspector");
  inspector.setAttribute("aria-live", "polite");
  body.append(mapPanel, inspector);

  for (const [id, parameter] of Object.entries(parameters)) {
    const swatch = el("span", undefined, "yard-swatch");
    paint(swatch, [id]);
    const item = el("div");
    item.append(swatch, el("span", parameterLabel(id, parameter)));
    legend.append(item);
  }
  for (const [label, style, mark] of [
    ["Unassigned", "yard-swatch"], ["Removed slot", "yard-swatch yard-removed"],
    ["Open tier gap", "yard-gap", "!"],
  ]) {
    const item = el("div");
    item.append(el("span", mark, style), el("span", label));
    legend.append(item);
  }

  let selection;
  let placement;
  const marked = new Set();
  const traceTiles = new Map();

  function pairPartner(view, index) {
    return view.tiles[index] === view.tiles[index - 1] ? view.block.stacks[index - 1] : null;
  }

  function matchingPair(view, index) {
    const {block} = view;
    const anchor = block.stacks[index];
    const partner = block.stacks[index - 1];
    if (!anchor.tiers.some(tier => tier.size === "40") || anchor.removed || partner.removed || anchor.capacity !== partner.capacity ||
        anchor.tiers.length !== partner.tiers.length || !anchor.tiers.every((tier, i) => {
          const other = partner.tiers[i];
          return tier.tier === other.tier && tier.size === "40" && other.size === "40" &&
            tier.anchor_slot === anchor.slot && other.anchor_slot === anchor.slot &&
            tier.dummy === other.dummy && tier.container_id === other.container_id;
        })) return null;
    return partner;
  }

  function mergePair(view, index) {
    const {tiles} = view;
    const merged = pairPartner(view, index);
    if (merged) return merged;
    const partner = matchingPair(view, index);
    if (!partner) return null;
    const tile = tiles[index];
    const previous = tiles[index - 1];
    tile.parentElement.colSpan = 2;
    tile.tabIndex = previous.tabIndex === 0 ? 0 : tile.tabIndex;
    if (view.focusIndex === index - 1) view.focusIndex = index;
    if (selection?.view === view && selection.index === index - 1) {
      tile.setAttribute("aria-pressed", "true");
    }
    previous.parentElement.remove();
    tiles[index - 1] = tile;
    return partner;
  }

  function splitPair(view, index) {
    const tile = view.tiles[index];
    tile.parentElement.colSpan = 1;
    tile.parentElement.before(stackCell(view, index - 1));
    view.tiles[index - 1].tabIndex = -1;
    tile.setAttribute("aria-pressed", "false");
  }

  function selectStack(view, index) {
    if (selection) {
      selection.view.tiles[selection.index].setAttribute("aria-pressed", "false");
    }

    const {block, tiles} = view;
    const anchor = tiles[index] === tiles[index + 1] ? index + 1 : index;
    const stack = block.stacks[anchor];
    const partner = pairPartner(view, anchor);
    tiles[view.focusIndex].tabIndex = -1;
    tiles[anchor].tabIndex = 0;
    tiles[anchor].setAttribute("aria-pressed", "true");
    view.focusIndex = anchor;
    selection = {view, index};
    const placed = placement?.block === block.code &&
      placement.stacks.some(item => item.row === stack.row && item.slot === stack.slot);
    renderInspector(inspector, block, stack, partner, block.stacks[index],
      placed ? placement : null, traceTiles.get(tiles[anchor]));
  }

  function selectedLocation() {
    const {view, index} = selection;
    const {row, slot} = view.block.stacks[index];
    return {block: view.block.code, row, slot};
  }

  function paintStack(tile, block, stack, partner) {
    const occupied = stack.tiers.length;
    const overcapacity = occupied > stack.capacity;
    const occupancy = occupied + "/" + stack.capacity;
    const assigned = assignedParameters(stack, partner);
    const names = assigned.map(id => "P" + id);
    tile.setAttribute("aria-label", "Block " + block.code + ", row " + stack.row + ", " + slotLabel(stack, partner) + ", " +
      (partner ? "40 ft, " : "") +
      (stack.removed ? "removed, " + stack.tiers.length + " tiers occupied" : occupancy + " tiers occupied") +
      (overcapacity ? ", over capacity" : "") +
      (names.length ? ", " + names.join(", ") : ", unassigned") +
      (stack.anomaly ? ", tier gap" : ""));
    tile.replaceChildren();
    if (stack.removed && !occupied) {
      tile.append(el("strong", "x"));
    } else {
      paint(tile, assigned);
      const count = el("strong", occupancy, occupied ? "yard-count" : "yard-count yard-count-empty");
      if (overcapacity) count.classList.add("yard-overcapacity");
      else if (occupied) count.style.color = occupancyColor(occupied / stack.capacity);
      const code = names[0] ? names[0] + (names.length > 1 ? " +" + (names.length - 1) : "") : "-";
      tile.append(count, el("small", code));
    }
    if (stack.anomaly) tile.append(el("span", "!", "yard-gap"));
    if (stack.tiers.some(tier => tier.size === "40")) tile.append(el("span", "40 ft", "yard-pair"));
  }

  function stackCell(view, index) {
    const {block} = view;
    const stack = block.stacks[index];
    const row = stack.row - 1;
    const slot = stack.slot - 1;
    const tile = el("button", undefined, "yard-tile" + (stack.removed ? " yard-removed" : ""));
    tile.type = "button";
    tile.tabIndex = index === 0 ? 0 : -1;
    tile.setAttribute("aria-pressed", "false");
    tile.addEventListener("click", event => {
      const bounds = tile.getBoundingClientRect();
      const leftHalf = event.detail && pairPartner(view, index) && event.clientX < bounds.left + bounds.width / 2;
      reportStackEdit("");
      selectStack(view, leftHalf ? index - 1 : index);
      accessOptions.onSelectionChange?.();
    });
    tile.addEventListener("keydown", event => {
      const direction = {ArrowLeft:[0,-1], ArrowRight:[0,1], ArrowUp:[-1,0], ArrowDown:[1,0]}[event.key];
      if (!direction) return;
      event.preventDefault();
      const nextRow = row + direction[0];
      const leftOfPair = direction[1] === -1 && pairPartner(view, index);
      const nextSlot = slot + direction[1] - (leftOfPair ? 1 : 0);
      if (nextRow < 0 || nextRow >= block.rows || nextSlot < 0 || nextSlot >= block.slots) return;
      const next = nextRow * block.slots + nextSlot;
      reportStackEdit("");
      selectStack(view, next);
      view.tiles[next].focus();
      accessOptions.onSelectionChange?.();
    });
    view.tiles[index] = tile;
    const cell = el("td");
    cell.append(tile);
    return cell;
  }

  const percent = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
  function updateBlockEquipment({block, equipment}) {
    const codes = block.equipment_codes ?? [];
    equipment.textContent = "Equipment: " + (codes.join(", ") || "None");
    equipment.title = equipment.textContent;
  }

  function updateBlockSummary({block, summary, occupancy, compliance}) {
    summary.textContent = block.rows + " rows × " + block.slots + " slots · " + block.tier_limit + " tiers · " +
      block.container_count + " containers · " + block.occupied_tiers + "/" + block.tier_capacity +
      " tier positions occupied";
    occupancy.textContent = "Occupancy rate " + (block.tier_capacity ? percent.format(block.occupied_tiers / block.tier_capacity) : "N/A");
    compliance.textContent = "Parameter compliance " +
      (block.parameter_compliance == null ? "N/A" : percent.format(block.parameter_compliance));
  }

  const views = [];
  for (const rectangle of rectangles) {
    const {block, left, top, width, height} = rectangle;
    const panel = el("div", undefined, "yard-block");
    panel.style.left = left + "px";
    panel.style.top = top + "px";
    panel.style.width = width + "px";
    panel.style.height = height + "px";
    const heading = el("div", undefined, "yard-block-heading");
    const summary = el("p", undefined, "yard-caption");
    const occupancy = el("p", undefined, "yard-caption");
    const compliance = el("p", undefined, "yard-caption");
    const equipment = el("p", undefined, "yard-caption");
    block.border_access ??= {above: true, below: true, left: true, right: true};
    block.saved_border_access ??= {...block.border_access};
    if (!Object.hasOwn(block, "saved_stacking_start")) block.saved_stacking_start = block.stacking_start?.override ?? null;
    const titleRow = el("div", undefined, "yard-block-title");
    const settings = button("Block " + block.code + " settings", "yard-block-settings-trigger");
    settings.textContent = "Block settings";
    settings.setAttribute("aria-haspopup", "dialog");
    settings.addEventListener("click", () => { if (!busy && !accessPending) openBlockSettings(block); });
    titleRow.append(el("h4", "Block " + block.code), settings);
    heading.append(titleRow, equipment, summary, occupancy, compliance);
    const grid = el("table", undefined, "yard-grid");
    grid.style.setProperty("--yard-slot-count", block.slots);
    grid.setAttribute("aria-label", "Stack grid for block " + block.code);
    const head = el("thead");
    const columns = el("tr");
    columns.append(el("th", "Row"));
    for (let slot = 1; slot <= block.slots; slot++) {
      const label = el("th", two(slot));
      label.scope = "col";
      label.setAttribute("aria-label", "Slot " + two(slot));
      columns.append(label);
    }
    head.append(columns);

    const view = {block, equipment, summary, occupancy, compliance, tiles: [], focusIndex: 0};
    updateBlockEquipment(view);
    updateBlockSummary(view);
    const rows = el("tbody");
    for (let row = 0; row < block.rows; row++) {
      const line = el("tr");
      const label = el("th", two(row + 1));
      label.scope = "row";
      line.append(label);
      for (let slot = 0; slot < block.slots; slot++) {
        const index = row * block.slots + slot;
        const stack = block.stacks[index];
        line.append(stackCell(view, index));
        const partner = stack.slot % 2 === 0 ? mergePair(view, index) : null;
        paintStack(view.tiles[index], block, stack, partner);
      }
      rows.append(line);
    }
    grid.append(head, rows);
    const accessFrame = el("div", undefined, "yard-access-frame");
    accessFrame.append(grid);
    const controls = accessSides.map(([side, label]) => borderSwitch(block, side, label, true));
    borderControls.set(block.id, controls);
    accessFrame.append(...controls.map(control => control.toggle));
    panel.append(heading, accessFrame);
    stage.append(panel);
    views.push(view);
  }

  const initial = views.reduce((current, view) =>
    view.block.occupied_tiers > current.block.occupied_tiers ? view : current);
  selectStack(initial, Math.max(0, initial.block.stacks.findIndex(stack => stack.tiers.length)));

  let fitScale = 1;
  let scale = 1;
  const zoomPercent = new Intl.NumberFormat(undefined, {style: "percent", maximumSignificantDigits: 3});
  function paintZoom(nextScale, keepCenter = false, pointer = null) {
    const frame = viewport.getBoundingClientRect();
    const oldExtent = extent.getBoundingClientRect();
    const targetX = pointer?.x ?? frame.left + viewport.clientWidth / 2;
    const targetY = pointer?.y ?? frame.top + viewport.clientHeight / 2;
    const anchorX = !pointer && oldExtent.width <= viewport.clientWidth ? width / 2 :
      Math.max(0, Math.min(width, (targetX - oldExtent.left) / scale));
    const anchorY = !pointer && oldExtent.height <= viewport.clientHeight ? height / 2 :
      Math.max(0, Math.min(height, (targetY - oldExtent.top) / scale));
    const minScale = fitScale / 10;
    scale = Math.max(minScale, Math.min(2, nextScale));
    stage.style.transform = "scale(" + scale + ")";
    extent.style.width = Math.ceil(width * scale) + "px";
    extent.style.height = Math.ceil(height * scale) + "px";
    zoomSlider.min = String(minScale * 100);
    zoomSlider.value = String(scale * 100);
    zoomLevel.textContent = zoomPercent.format(scale);
    zoomSlider.setAttribute("aria-valuetext", zoomLevel.textContent);
    zoomOut.disabled = scale <= minScale * (1 + Number.EPSILON);
    zoomIn.disabled = scale >= 2;
    if (keepCenter) {
      const newExtent = extent.getBoundingClientRect();
      viewport.scrollLeft += newExtent.left + anchorX * scale - targetX;
      viewport.scrollTop += newExtent.top + anchorY * scale - targetY;
    }
  }
  function resizeMap() {
    const wasAtFit = scale === fitScale;
    if (viewport.clientWidth && viewport.clientHeight) {
      fitScale = Math.min(1, viewport.clientWidth / width, viewport.clientHeight / height);
    }
    paintZoom(wasAtFit ? fitScale : scale);
  }
  zoomOut.addEventListener("click", () => paintZoom(scale / 1.25, true));
  zoomIn.addEventListener("click", () => paintZoom(scale * 1.25, true));
  zoomSlider.addEventListener("input", () => paintZoom(Number(zoomSlider.value) / 100, true));
  viewport.addEventListener("wheel", event => {
    if (!event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    event.preventDefault();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1);
    paintZoom(scale * Math.exp(-delta * 0.0015), true, {x: event.clientX, y: event.clientY});
  }, {passive: false});
  let pan = null;
  viewport.addEventListener("pointerdown", event => {
    if (event.button !== 2 || pan) return;
    event.preventDefault();
    pan = {id: event.pointerId, x: event.clientX, y: event.clientY,
      left: viewport.scrollLeft, top: viewport.scrollTop};
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("yard-map-panning");
  });
  viewport.addEventListener("pointermove", event => {
    if (event.pointerId !== pan?.id) return;
    event.preventDefault();
    viewport.scrollLeft = pan.left - (event.clientX - pan.x);
    viewport.scrollTop = pan.top - (event.clientY - pan.y);
  });
  function stopPan(event) {
    if (event.pointerId !== pan?.id) return;
    pan = null;
    viewport.classList.remove("yard-map-panning");
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
  }
  viewport.addEventListener("pointerup", stopPan);
  viewport.addEventListener("pointercancel", stopPan);
  viewport.addEventListener("lostpointercapture", stopPan);
  viewport.addEventListener("contextmenu", event => event.preventDefault());
  function centerSelection() {
    const tile = selection.view.tiles[selection.index].getBoundingClientRect();
    const frame = viewport.getBoundingClientRect();
    viewport.scrollLeft += tile.left - frame.left + (tile.width - viewport.clientWidth) / 2;
    viewport.scrollTop += tile.top - frame.top + (tile.height - viewport.clientHeight) / 2;
  }
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => {
      if (viewport.isConnected) resizeMap();
      else observer.disconnect();
    });
    observer.observe(viewport);
  }
  resizeMap();
  header.append(el("p", branchLabel(branch) + " · Compact schematic (distances not to scale)", "yard-caption"));

  function showTrace(trace, {historical = false, placed = null, preserveSelection = false} = {}) {
    for (const tile of traceTiles.keys()) {
      tile.classList.remove("yard-trace-candidate", "yard-trace-winner",
        "yard-trace-pair", "yard-trace-pair-anchor");
      tile.querySelector(".yard-trace-rank")?.remove();
      tile.removeAttribute("aria-description");
    }
    traceTiles.clear();
    root.classList.toggle("yard-trace-history", historical);
    let target = markPlacement(placed);
    traceKey.hidden = !trace;
    if (!trace) {
      selectStack(selection.view, selection.index);
      return;
    }

    const {row, calculation, alternate_rank: alternateRank, manual_destination: manual} = trace;
    const candidates = calculation?.candidates ?? [];
    for (const candidate of candidates) {
      const view = views.find(item => item.block.code === candidate.block);
      const anchor = (candidate.row - 1) * view.block.slots + candidate.slot - 1;
      const anchorTile = view.tiles[anchor];
      const footprint = new Set([anchorTile]);
      if (row.size === "40") footprint.add(view.tiles[anchor - 1]);
      const selected = alternateRank == null ? candidate.selected : candidate.candidate_rank === alternateRank;
      const chosen = !manual && selected && (row.status === "placed" || row.status === "suggested");
      const slots = row.size === "40" ? "Slots " + two(candidate.slot - 1) + "–" + two(candidate.slot) :
        "Slot " + two(candidate.slot);
      const state = chosen ? (row.status === "placed" ? "Placed" : alternateRank == null ? "Suggested placement" : "Alternate selected") :
        candidate.selected ? "Engine recommendation" : "Passed parameter selection";
      const rankLabel = candidate.rank == null ? "" : "Rank " + candidate.rank + " · ";
      const description = rankLabel + slots + " · Tier " + candidate.tier + " · " + (candidate.equipment ?? "No equipment") + " · " + state;
      const breakdown = heuristicRows(candidate, calculation.enabled_multipliers);
      for (const tile of footprint) {
        if (!traceTiles.has(tile)) traceTiles.set(tile, []);
        traceTiles.get(tile).push({chosen, description, breakdown,
          badgeRank: tile === anchorTile ? candidate.rank : null});
        if (footprint.size === 2) tile.classList.add("yard-trace-pair");
      }
      if (footprint.size === 2) anchorTile.classList.add("yard-trace-pair-anchor");
      if (!target || selected) target = {view, anchor};
    }
    if (manual) {
      const view = views.find(item => item.block.code === manual.block);
      const anchor = (manual.row - 1) * view.block.slots + manual.slot - 1;
      const anchorTile = view.tiles[anchor];
      const footprint = new Set([anchorTile]);
      if (row.size === "40") footprint.add(view.tiles[anchor - 1]);
      const description = "Manual " + (row.status === "placed" ? "placement" : "selection") + " · Tier " + manual.tier +
        (manual.equipment ? " · " + manual.equipment : "");
      for (const tile of footprint) {
        if (!traceTiles.has(tile)) traceTiles.set(tile, []);
        traceTiles.get(tile).push({chosen: true, description});
        if (footprint.size === 2) tile.classList.add("yard-trace-pair");
      }
      if (footprint.size === 2) anchorTile.classList.add("yard-trace-pair-anchor");
      target = {view, anchor};
    }
    for (const [tile, entries] of traceTiles) {
      tile.classList.add(entries.some(entry => entry.chosen) ? "yard-trace-winner" : "yard-trace-candidate");
      tile.setAttribute("aria-description", entries.map(entry => entry.description).join(". "));
      const ranks = entries.map(entry => entry.badgeRank).filter(rank => rank != null);
      if (ranks.length) {
        const badge = el("span", "#" + ranks.join(", #"), "yard-trace-rank");
        badge.setAttribute("aria-hidden", "true");
        tile.append(badge);
      }
    }

    const rejected = Object.values(calculation?.rejections ?? {}).reduce((total, count) => total + count, 0);
    const context = calculation ?
      (calculation.checked - rejected) + " of " + calculation.checked + " locations passed feasibility" :
      "No placement search";
    traceKey.replaceChildren(
      el("strong", (row.status === "suggested" ? "Suggestion #" : "Trace #") + row.position + " · " + (row.container_id || "Missing container ID")),
      el("span", context + (historical ? " · Earlier trace on the current yard" : "")),
      el("span", manual ? "Purple marks the manual location" : candidates.length ?
        candidates.length + " passed parameter selection · Badges mark the top five · Select a location for its score" +
          (row.status === "suggested" ? (alternateRank == null ? " · Purple marks rank 1" : " · Purple marks the chosen alternate") :
            row.status === "placed" ? " · Purple marks the placement" : "") :
        "No locations passed parameter selection")
    );
    if (target && !preserveSelection) {
      selectStack(target.view, target.anchor);
      if (scale > fitScale) centerSelection();
    } else {
      selectStack(selection.view, selection.index);
    }
  }


  function markPlacement(placed) {
    for (const tile of marked) {
      tile.classList.remove("yard-placed");
      tile.querySelector(".yard-placement-badge")?.remove();
      tile.removeAttribute("title");
    }
    marked.clear();
    placement = null;
    if (!placed) return null;
    const view = views.find(item => item.block.code === placed.block);
    const index = (placed.row - 1) * view.block.slots + placed.slot - 1;
    if (!view.block.stacks[index].tiers.some(tier => tier.tier === placed.tier && tier.container_id === placed.container_id)) {
      return null;
    }
    placement = placed;
    for (const stack of placed.stacks) {
      const tile = view.tiles[(stack.row - 1) * view.block.slots + stack.slot - 1];
      tile.classList.add("yard-placed");
      tile.title = placed.container_id + " placed at tier " + placed.tier;
      marked.add(tile);
    }
    const anchor = view.tiles[index];
    const badge = el("span", "T" + placed.tier, "yard-placement-badge");
    badge.setAttribute("aria-hidden", "true");
    anchor.append(badge);
    return {view, anchor: index};
  }

  function applyPlacement(placed) {
    const view = views.find(item => item.block.code === placed.block);
    const {block, tiles} = view;
    for (const [blockId, codes] of Object.entries(placed.equipment_updates ?? {})) {
      const affected = views.find(item => item.block.id === blockId);
      affected.block.equipment_codes = codes;
      updateBlockEquipment(affected);
    }
    for (const stack of placed.updated_stacks ?? placed.stacks) {
      const index = (stack.row - 1) * block.slots + stack.slot - 1;
      block.occupied_tiers += stack.tiers.length - block.stacks[index].tiers.length;
      block.stacks[index] = stack;
    }
    if (!placed.dummy) {
      block.parameter_compliance = placed.parameter_compliance;
      block.container_count += placed.removed ? -1 : 1 - (placed.displaced?.length ?? 0);
    }
    if (placed.manual) return;
    let repaint = placed.stacks;
    const anchorSlot = placed.slot + (placed.removed ? placed.slot % 2 : 0);
    const anchor = (placed.row - 1) * block.slots + anchorSlot - 1;
    if (placed.removed && anchorSlot <= block.slots) {
      if (pairPartner(view, anchor) && !matchingPair(view, anchor)) splitPair(view, anchor);
      else mergePair(view, anchor);
      repaint = block.stacks.slice(anchor - 1, anchor + 1);
    } else if (placed.stacks.length === 2) {
      mergePair(view, anchor);
    }
    for (const stack of repaint) {
      const index = (stack.row - 1) * block.slots + stack.slot - 1;
      if (tiles[index] !== tiles[index + 1]) paintStack(tiles[index], block, stack, pairPartner(view, index));
    }
    updateBlockSummary(view);
  }
  syncAccessControls();
  showAccessChanges();
  return {element: root, applyPlacement, showTrace, selectedLocation, accessBusy: () => accessPending,
    setAccessEditable(editable) { accessEditable = editable; syncAccessControls(); }};
}
