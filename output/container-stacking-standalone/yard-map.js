"use strict";

function layoutYardBlocks(blocks) {
  const gap = 22;
  const padding = 16;
  const groups = new Map();
  for (const block of blocks) {
    const key = block.x + "," + block.y;
    if (!groups.has(key)) groups.set(key, {x: block.x, y: block.y, width: 0, height: 0, blocks: []});
    const group = groups.get(key);
    const width = Math.max(190, 56 + block.slots * 47);
    const height = 124 + block.rows * 39;
    const offset = group.blocks.length ? group.height + gap : 0;
    group.blocks.push({block, width, height, offset});
    group.width = Math.max(group.width, width);
    group.height = offset + height;
  }

  const positions = [...groups.values()];
  const minX = Math.min(...positions.map(group => group.x));
  const minY = Math.min(...positions.map(group => group.y));
  const spread = Math.max(
    Math.max(...positions.map(group => group.x)) - minX,
    Math.max(...positions.map(group => group.y)) - minY,
  );
  let scale = spread ? Math.min(1, 800 / spread) : 1;
  // Use the same scale on both axes. Each pair needs a gap on only one axis.
  for (let i = 0; i < positions.length; i++) {
    for (let j = i + 1; j < positions.length; j++) {
      const a = positions[i];
      const b = positions[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const clearX = dx ? ((dx > 0 ? a.width : b.width) + gap) / Math.abs(dx) : Infinity;
      const clearY = dy ? ((dy > 0 ? a.height : b.height) + gap) / Math.abs(dy) : Infinity;
      scale = Math.max(scale, Math.min(clearX, clearY));
    }
  }

  const rectangles = positions.flatMap(group => group.blocks.map(item => ({
    ...item,
    left: padding + (group.x - minX) * scale,
    top: padding + (group.y - minY) * scale + item.offset,
  })));
  return {
    rectangles,
    width: Math.ceil(Math.max(...rectangles.map(item => item.left + item.width)) + padding),
    height: Math.ceil(Math.max(...rectangles.map(item => item.top + item.height)) + padding),
  };
}

function createYardMap(branch, branches = [branch]) {
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

  function button(label, className) {
    const control = el("button", undefined, className);
    control.type = "button";
    control.setAttribute("aria-label", label);
    return control;
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

  function renderInspector(panel, block, stack, partner, placed, traceEntries) {
    const heading = el("div", undefined, "yard-inspector-heading");
    const extra = Math.max(0, stack.tiers.length - stack.capacity);
    const occupancy = el("span", stack.removed ? "Removed" :
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
        panel.append(el("p", description, "yard-trace-detail"), heuristicTable(breakdown));
      }
    }
    if (stack.anomaly) panel.append(el("p", "Tier gap below an occupied position.", "yard-gap-note"));
    if (extra) panel.append(el("p", "Over capacity by " + extra + (extra === 1 ? " tier." : " tiers."),
      "yard-overcapacity"));
    if (stack.tiers.some(tier => tier.dummy)) {
      panel.append(el("p", "Occupied tiers with missing container records.", "yard-gap-note"));
    }
    const footprint = stack.tiers.find(tier => tier.size === "40");
    if (partner) panel.append(el("p", "40 ft stack", "yard-caption"));
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
    if (stack.removed) return;

    panel.append(el("h4", "Tier contents"));
    const tiers = new Map(stack.tiers.map(tier => [tier.tier, tier]));
    const highestTier = stack.tiers.reduce((highest, tier) => Math.max(highest, tier.tier), stack.capacity);
    const rows = [];
    for (let number = highestTier; number >= 1; number--) {
      const tier = tiers.get(number);
      if (!tier || tier.dummy) {
        rows.push([number, tier ? "Occupied · Missing record" : "Empty", "—", "—", "—", "—"]);
        continue;
      }
      rows.push([
        number, tier.container_id, tier.size + " ft", {F: "Full", E: "Empty"}[tier.fill] ?? tier.fill,
        tier.grade, tier.weight == null ? "—" : tier.weight.toLocaleString(),
      ]);
    }
    const contents = table(["Tier", "Container", "Size", "Fill", "Grade", "Weight"], rows);
    contents.classList.add("yard-tier-table");
    if (placed) contents.querySelectorAll("tbody tr")[highestTier - placed.tier].classList.add("yard-placed-tier");
    panel.append(contents);
    if (stack.tiers.some(tier => tier.weight != null)) {
      panel.append(el("p", "Weight values use the source units.", "yard-caption"));
    }
  }

  const {blocks, parameters} = branch.yard_map;
  const {rectangles, width, height} = layoutYardBlocks(blocks);
  const mapPanel = el("div", undefined, "yard-panel");
  const toolbar = el("div", undefined, "yard-map-toolbar");
  const legend = el("div", undefined, "yard-legend");
  legend.setAttribute("aria-label", "Map legend");
  const controls = el("div", undefined, "yard-map-controls");
  const fit = button("Fit yard", "yard-map-zoom");
  const full = button("Show yard at 100%", "yard-map-zoom");
  fit.textContent = "Fit yard";
  full.textContent = "100%";
  controls.append(fit, full);
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
    ["Tier gap or missing record", "yard-gap", "!"],
  ]) {
    const item = el("div");
    item.append(el("span", mark, style), el("span", label));
    legend.append(item);
  }

  let selection;
  let placement;
  let historicalTrace = false;
  const marked = new Set();
  const traceTiles = new Map();

  function pairPartner(view, index) {
    return view.tiles[index] === view.tiles[index - 1] ? view.block.stacks[index - 1] : null;
  }

  function mergePair(view, index) {
    const {block, tiles} = view;
    const anchor = block.stacks[index];
    const partner = block.stacks[index - 1];
    if (pairPartner(view, index)) return partner;
    if (!anchor.tiers.some(tier => tier.size === "40") || anchor.removed || partner.removed || anchor.capacity !== partner.capacity ||
        anchor.tiers.length !== partner.tiers.length || !anchor.tiers.every((tier, i) => {
          const other = partner.tiers[i];
          if (tier.tier !== other.tier) return false;
          if (tier.dummy || other.dummy) return tier.dummy && other.dummy;
          return tier.size === "40" && other.size === "40" && tier.anchor_slot === anchor.slot &&
            other.anchor_slot === anchor.slot && tier.container_id === other.container_id;
        })) return null;

    const tile = tiles[index];
    const previous = tiles[index - 1];
    tile.parentElement.colSpan = 2;
    tile.tabIndex = previous.tabIndex === 0 ? 0 : tile.tabIndex;
    if (view.focusIndex === index - 1) view.focusIndex = index;
    if (selection?.view === view && selection.index === index - 1) {
      selection.index = index;
      tile.setAttribute("aria-pressed", "true");
    }
    previous.parentElement.remove();
    tiles[index - 1] = tile;
    return partner;
  }

  function selectStack(view, index) {
    if (selection) {
      selection.view.tiles[selection.index].setAttribute("aria-pressed", "false");
    }

    const {block, tiles} = view;
    if (tiles[index] === tiles[index + 1]) index++;
    const stack = block.stacks[index];
    const partner = pairPartner(view, index);
    tiles[view.focusIndex].tabIndex = -1;
    tiles[index].tabIndex = 0;
    tiles[index].setAttribute("aria-pressed", "true");
    view.focusIndex = index;
    selection = {view, index};
    const placed = !historicalTrace && placement?.block === block.code &&
      placement.stacks.some(item => item.row === stack.row && item.slot === stack.slot);
    renderInspector(inspector, block, stack, partner, placed ? placement : null, traceTiles.get(tiles[index]));
  }

  function paintStack(tile, block, stack, partner) {
    const occupied = stack.tiers.length;
    const overcapacity = occupied > stack.capacity;
    const missingRecords = stack.tiers.some(tier => tier.dummy);
    const occupancy = occupied + "/" + stack.capacity;
    const assigned = assignedParameters(stack, partner);
    const names = assigned.map(id => "P" + id);
    tile.setAttribute("aria-label", "Block " + block.code + ", row " + stack.row + ", " + slotLabel(stack, partner) + ", " +
      (partner ? "40 ft, " : "") +
      (stack.removed ? "removed" : occupancy + " tiers occupied") +
      (overcapacity ? ", over capacity" : "") +
      (names.length ? ", " + names.join(", ") : ", unassigned") +
      (stack.anomaly ? ", tier gap" : "") +
      (missingRecords ? ", missing container records" : ""));
    tile.replaceChildren();
    if (stack.removed) {
      tile.append(el("strong", "x"));
    } else {
      paint(tile, assigned);
      const count = el("strong", occupancy, occupied ? "yard-count" : "yard-count yard-count-empty");
      if (overcapacity) count.classList.add("yard-overcapacity");
      else if (occupied) count.style.color = occupancyColor(occupied / stack.capacity);
      const code = names[0] ? names[0] + (names.length > 1 ? " +" + (names.length - 1) : "") : "-";
      tile.append(count, el("small", code));
    }
    if (stack.anomaly || missingRecords) tile.append(el("span", "!", "yard-gap"));
    if (stack.tiers.some(tier => tier.size === "40")) tile.append(el("span", "40 ft", "yard-pair"));
  }

  const percent = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
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
    heading.append(el("h4", "Block " + block.code), summary, occupancy, compliance);
    const grid = el("table", undefined, "yard-grid");
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

    const view = {block, summary, occupancy, compliance, tiles: [], focusIndex: 0};
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
        const tile = el("button", undefined, "yard-tile" + (stack.removed ? " yard-removed" : ""));
        tile.type = "button";
        tile.tabIndex = index === 0 ? 0 : -1;
        tile.setAttribute("aria-pressed", "false");
        tile.addEventListener("click", () => selectStack(view, index));
        tile.addEventListener("keydown", event => {
          const direction = {ArrowLeft:[0,-1], ArrowRight:[0,1], ArrowUp:[-1,0], ArrowDown:[1,0]}[event.key];
          if (!direction) return;
          event.preventDefault();
          const nextRow = row + direction[0];
          const leftOfPair = direction[1] === -1 && pairPartner(view, index);
          const nextSlot = slot + direction[1] - (leftOfPair ? 1 : 0);
          if (nextRow < 0 || nextRow >= block.rows || nextSlot < 0 || nextSlot >= block.slots) return;
          const next = nextRow * block.slots + nextSlot;
          selectStack(view, next);
          view.tiles[next].focus();
        });
        view.tiles.push(tile);
        const cell = el("td");
        cell.append(tile);
        line.append(cell);
        const partner = stack.slot % 2 === 0 ? mergePair(view, index) : null;
        paintStack(tile, block, stack, partner);
      }
      rows.append(line);
    }
    grid.append(head, rows);
    panel.append(heading, grid);
    stage.append(panel);
    views.push(view);
  }

  const initial = views.reduce((current, view) =>
    view.block.occupied_tiers > current.block.occupied_tiers ? view : current);
  selectStack(initial, Math.max(0, initial.block.stacks.findIndex(stack => stack.tiers.length)));

  let fitted = true;
  function resizeMap() {
    const scale = fitted ? Math.min(1, (viewport.clientWidth || width) / width,
      (viewport.clientHeight || height) / height) : 1;
    stage.style.transform = "scale(" + scale + ")";
    extent.style.width = Math.floor(width * scale) + "px";
    extent.style.height = Math.floor(height * scale) + "px";
    fit.setAttribute("aria-pressed", String(fitted));
    full.setAttribute("aria-pressed", String(!fitted));
  }
  fit.addEventListener("click", () => {
    fitted = true;
    resizeMap();
    viewport.scrollTop = 0;
    viewport.scrollLeft = 0;
  });
  function centerSelection() {
    const tile = selection.view.tiles[selection.index].getBoundingClientRect();
    const frame = viewport.getBoundingClientRect();
    viewport.scrollLeft += tile.left - frame.left + (tile.width - viewport.clientWidth) / 2;
    viewport.scrollTop += tile.top - frame.top + (tile.height - viewport.clientHeight) / 2;
  }
  full.addEventListener("click", () => {
    if (!fitted) return;
    fitted = false;
    resizeMap();
    centerSelection();
  });
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => {
      if (viewport.isConnected) resizeMap();
      else observer.disconnect();
    });
    observer.observe(viewport);
  }
  resizeMap();
  header.append(el("p", branchLabel(branch), "yard-caption"));

  function showTrace(trace, historical = false) {
    for (const tile of traceTiles.keys()) {
      tile.classList.remove("yard-trace-candidate", "yard-trace-winner",
        "yard-trace-pair", "yard-trace-pair-anchor");
      tile.querySelector(".yard-trace-rank")?.remove();
      tile.removeAttribute("aria-description");
    }
    traceTiles.clear();
    historicalTrace = historical;
    root.classList.toggle("yard-trace-history", historical);
    traceKey.hidden = !trace;
    if (!trace) {
      selectStack(selection.view, selection.index);
      return;
    }

    const {row, calculation} = trace;
    const candidates = calculation?.candidates ?? [];
    let target;
    for (const candidate of candidates) {
      const view = views.find(item => item.block.code === candidate.block);
      const anchor = (candidate.row - 1) * view.block.slots + candidate.slot - 1;
      const anchorTile = view.tiles[anchor];
      const footprint = new Set([anchorTile]);
      if (row.size === "40") footprint.add(view.tiles[anchor - 1]);
      const chosen = candidate.selected && row.status === "placed";
      const slots = row.size === "40" ? "Slots " + two(candidate.slot - 1) + "–" + two(candidate.slot) :
        "Slot " + two(candidate.slot);
      const state = chosen ? "Placed" : "Passed parameter selection";
      const rankLabel = candidate.rank == null ? "" : "Rank " + candidate.rank + " · ";
      const description = rankLabel + slots + " · Tier " + candidate.tier + " · " + candidate.equipment + " · " + state;
      const breakdown = heuristicRows(candidate, calculation.enabled_multipliers);
      for (const tile of footprint) {
        if (!traceTiles.has(tile)) traceTiles.set(tile, []);
        traceTiles.get(tile).push({chosen, description, breakdown, badgeRank: tile === anchorTile ? candidate.rank : null});
        if (footprint.size === 2) tile.classList.add("yard-trace-pair");
      }
      if (footprint.size === 2) anchorTile.classList.add("yard-trace-pair-anchor");
      if (!target || candidate.selected) target = {view, anchor};
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
      el("strong", "Trace #" + row.position + " · " + (row.container_id || "Missing container ID")),
      el("span", context + (historical ? " · Earlier trace on the current yard" : "")),
      el("span", candidates.length ?
        candidates.length + " passed parameter selection · Badges mark the top five · Select a location for its score" +
          (row.status === "placed" ? " · Purple marks the placement" : "") :
        "No locations passed parameter selection")
    );
    if (target) {
      selectStack(target.view, target.anchor);
      if (!fitted) centerSelection();
    } else {
      selectStack(selection.view, selection.index);
    }
  }


  function markPlacement(placed, reveal = false) {
    for (const tile of marked) {
      tile.classList.remove("yard-placed");
      tile.querySelector(".yard-placement-badge")?.remove();
      tile.removeAttribute("title");
    }
    marked.clear();
    placement = placed;
    if (!placed) {
      selectStack(selection.view, selection.index);
      return;
    }
    const view = views.find(item => item.block.code === placed.block);
    const index = (placed.row - 1) * view.block.slots + placed.slot - 1;
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
    selectStack(view, index);
    if (reveal) {
      if (!fitted) centerSelection();
      anchor.scrollIntoView({block: "nearest", inline: "nearest"});
    }
  }

  function applyPlacement(placed) {
    const view = views.find(item => item.block.code === placed.block);
    const {block, tiles} = view;
    for (const stack of placed.stacks) {
      const index = (stack.row - 1) * block.slots + stack.slot - 1;
      block.occupied_tiers += stack.tiers.length - block.stacks[index].tiers.length;
      block.stacks[index] = stack;
    }
    if (placed.stacks.length === 2) mergePair(view, (placed.row - 1) * block.slots + placed.slot - 1);
    for (const stack of placed.stacks) {
      const index = (stack.row - 1) * block.slots + stack.slot - 1;
      if (tiles[index] !== tiles[index + 1]) paintStack(tiles[index], block, stack, pairPartner(view, index));
    }
    block.container_count++;
    block.parameter_compliance = placed.parameter_compliance;
    updateBlockSummary(view);
  }
  return {element: root, applyPlacement, markPlacement, showTrace};
}
