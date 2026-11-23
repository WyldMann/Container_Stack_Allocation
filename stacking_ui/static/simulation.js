"use strict";

function enableQueueReordering({summary, track, focusCard, report}, run, id, accessBusy, onCurrentChange) {
  const hint = el("span", " · Hold a dragged card near either edge to scroll. Release at the insertion marker. Use Alt + ← or → on a focused card to move it one place.");
  summary.append(hint);
  let dragged = null;
  let target = null;
  let dragX = null;
  let scrollSpeed = 0;
  let scrollFrame = null;
  let lastScrollTime = null;

  // A gap is the number of cards to its left, including any processed cards.
  function insertionGap(x) {
    let left = 0;
    let right = track.children.length;
    while (left < right) {
      const index = Math.floor((left + right) / 2);
      const card = track.children[index];
      const bounds = card.getBoundingClientRect();
      const center = Math.floor(bounds.left + bounds.width / 2);
      // Directly over the center, dropping takes the hovered card's position.
      if (x < center || (x === center && card.value < dragged.value)) right = index;
      else left = index + 1;
    }
    return left >= run.processed ? left : null;
  }

  function markGap(gap) {
    const end = track.children.length;
    const card = gap === null ? null : track.children[Math.min(gap, end - 1)];
    if (card !== target) target?.removeAttribute("data-drop-edge");
    target = card;
    if (card) card.dataset.dropEdge = gap === end ? "after" : "before";
  }

  function scrollQueue(time) {
    scrollFrame = null;
    if (!dragged || !scrollSpeed || !track.isConnected) return;
    const elapsed = lastScrollTime === null ? 16 : Math.min(time - lastScrollTime, 32);
    lastScrollTime = time;
    const before = track.scrollLeft;
    const distance = Math.max(1, Math.round(Math.abs(scrollSpeed) * elapsed)) * Math.sign(scrollSpeed);
    track.scrollLeft += distance;
    if (track.scrollLeft !== before) scrollFrame = requestAnimationFrame(scrollQueue);
    else lastScrollTime = null;
  }

  function stopScrolling() {
    if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
    scrollFrame = lastScrollTime = dragX = null;
    scrollSpeed = 0;
  }

  function endDrag() {
    stopScrolling();
    markGap(null);
    track.classList.remove("inbound-drag-active");
    dragged?.classList.remove("inbound-dragging");
    dragged = null;
  }

  function move(from, to) {
    const {queue} = run.branch;
    if (from === to || from <= run.processed || to <= run.processed || to > queue.length || accessBusy()) return;
    return action(async () => {
      const reordered = queue.slice();
      const [moved] = reordered.splice(from - 1, 1);
      reordered.splice(to - 1, 0, moved);
      const order = reordered.slice(run.processed).map(row => row.input_position);
      await globalThis.reorderStackingQueue({id, branch: run.branch.branch_code, order});
      run.branch.queue = reordered;
      for (let position = Math.min(from, to); position <= Math.max(from, to); position++) {
        const row = reordered[position - 1];
        row.position = position;
        renderInboundCard(track.children[position - 1], row);
      }
      focusCard(track.children[to - 1]);
      report((moved.container_id || "Inbound row") + " moved to #" + to + ".");
      if (reordered[run.processed] !== queue[run.processed]) await onCurrentChange();
    }, report);
  }

  track.addEventListener("keydown", event => {
    const card = event.target.closest(".inbound-card");
    if (!card?.draggable || !event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    move(card.value, card.value + (event.key === "ArrowLeft" ? -1 : 1));
  });
  track.addEventListener("dragstart", event => {
    const card = event.target.closest(".inbound-card");
    if (!card?.draggable || busy || accessBusy()) {
      event.preventDefault();
      return;
    }
    dragged = card;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", String(card.value));
    card.classList.add("inbound-dragging");
    track.classList.add("inbound-drag-active");
  });
  track.addEventListener("dragover", event => {
    if (!dragged) return;
    dragX = event.clientX;
    const {left, right, width} = track.getBoundingClientRect();
    const edge = Math.min(64, width / 4);
    const towardLeft = Math.max(0, 1 - (dragX - left) / edge);
    const towardRight = Math.max(0, 1 - (right - dragX) / edge);
    scrollSpeed = 1.2 * (towardRight - towardLeft);
    if (scrollSpeed && scrollFrame === null) {
      lastScrollTime = null;
      scrollFrame = requestAnimationFrame(scrollQueue);
    }
    const gap = insertionGap(dragX);
    markGap(gap);
    if (gap === null) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  });
  track.addEventListener("dragleave", event => {
    if (track.contains(event.relatedTarget)) return;
    stopScrolling();
    markGap(null);
  });
  track.addEventListener("scroll", () => {
    if (dragX !== null) markGap(insertionGap(dragX));
  });
  track.addEventListener("drop", event => {
    if (!dragged) return;
    event.preventDefault();
    const gap = insertionGap(event.clientX);
    const from = dragged.value;
    endDrag();
    if (gap !== null) move(from, gap < from ? gap + 1 : gap);
  });
  track.addEventListener("dragend", endDrag);

  function refresh() {
    const canMove = run.branch.queue.length - run.processed >= 2;
    hint.hidden = !canMove;
    for (const card of track.children) {
      card.draggable = canMove && card.value > run.processed;
    }
    report("");
  }
  return {move, refresh};
}

function alternateLocationPicker(branch, onSelect) {
  const element = el("div", undefined, "simulation-alternate");
  element.id = "alternate-location";
  element.hidden = true;
  element.append(el("p", "Select a stack on the map or choose its block, row, slot, and tier below."));
  const fields = el("div", undefined, "simulation-alternate-fields");
  const [block, row, slot, tier] = ["Block", "Row", "Slot", "Tier"].map(name => {
    const label = el("label", name);
    const select = el("select");
    label.append(select);
    fields.append(label);
    return select;
  });
  const warning = el("p", undefined, "not-ready");
  warning.setAttribute("aria-live", "polite");
  element.append(fields, warning);
  const blocks = new Map(branch.yard_map.blocks.map(item => [item.code, item]));
  let containerSize;
  const numbers = count => Array.from({length: count}, (_, index) => index + 1);
  const currentBlock = () => blocks.get(block.value);
  const footprintSize = () => containerSize === "40" ? 2 : 1;

  function options(select, prompt, values) {
    const placeholder = el("option", prompt);
    placeholder.value = "";
    const choices = document.createDocumentFragment();
    choices.append(placeholder);
    for (const [value, label] of values) {
      const option = el("option", label);
      option.value = value;
      choices.append(option);
    }
    select.replaceChildren(choices);
    select.disabled = values.length === 0;
    select.dataset.accessLocked = String(select.disabled);
  }

  function updateTiers() {
    const yardBlock = currentBlock();
    options(tier, "Select tier", !slot.value ? [] : numbers(yardBlock.tier_limit).map(value => [value, value]));
    if (!slot.value) return;
    const stacks = footprintStacks(yardBlock, Number(row.value), Number(slot.value), containerSize);
    const highest = stacks.reduce((height, stack) => stack.tiers.reduce(
      (top, item) => Math.max(top, item.tier), height), 0);
    tier.value = Math.min(highest + 1, yardBlock.tier_limit);
  }

  function updateSlots() {
    const size = footprintSize();
    const count = row.value ? Math.floor(currentBlock().slots / size) : 0;
    options(slot, "Select slot", numbers(count).map(index => [
      index * size, size === 2 ? (index * size - 1) + "–" + index * size : index
    ]));
    updateTiers();
  }

  function updateRows() {
    options(row, "Select row", numbers(currentBlock()?.rows ?? 0).map(value => [value, value]));
    updateSlots();
  }

  function selectCoordinate() {
    onSelect(tier.value ? {block: block.value, row: Number(row.value), slot: Number(slot.value), tier: Number(tier.value)} : null);
  }
  block.addEventListener("change", () => { updateRows(); selectCoordinate(); });
  row.addEventListener("change", () => { updateSlots(); selectCoordinate(); });
  slot.addEventListener("change", () => { updateTiers(); selectCoordinate(); });
  tier.addEventListener("change", selectCoordinate);
  return {
    element,
    open(suggestion) {
      containerSize = suggestion.row.size;
      options(block, "Select block", [...blocks.values()].filter(item => item.slots >= footprintSize())
        .map(item => [item.code, item.code]));
      updateRows();
      element.hidden = false;
      block.focus();
    },
    warn(displaced) {
      warning.textContent = displaced.length ? "This placement would replace " + displaced.join(", ") + "." : "";
    },
    select(location) {
      const destinationSlot = footprintSize() === 2 ? location.slot + location.slot % 2 : location.slot;
      if (destinationSlot > blocks.get(location.block).slots) return;
      block.value = location.block;
      updateRows();
      row.value = location.row;
      updateSlots();
      slot.value = destinationSlot;
      updateTiers();
      selectCoordinate();
    }
  };
}

function footprintStacks(block, row, slot, size) {
  const anchor = (row - 1) * block.slots + slot - 1;
  return size === "40" ? block.stacks.slice(anchor - 1, anchor + 1) : [block.stacks[anchor]];
}

async function simulationView(run, branches, id, onStart) {
  const {branch} = run;
  const root = el("div");
  const canReorder = typeof globalThis.reorderStackingQueue === "function";
  const queue = inboundQueue(branch, {
    firstPendingPosition: () => run.processed + 1,
    onMove: canReorder ? (from, to) => reorder.move(from, to) : null,
    onDelete: typeof globalThis.deleteStackingQueueRow === "function" ? deleteContainer : null,
    onAdd: typeof globalThis.addStackingQueueRow === "function" ? addContainer : null
  });
  const {panel: queuePanel, track, refreshDetails} = queue;
  const mapOptions = {
    editable: run.processed === 0 && typeof globalThis.updateStackingBlockAccess === "function",
    onChange: async (block, side, value) => {
      await globalThis.updateStackingBlockAccess({
        id, branch: branch.branch_code, policies: [{block_id: block.id, ...block.loader_access, [side]: value}]
      });
      await loadSuggestion();
    },
    onSave: block => globalThis.saveStackingBlockAccess({id, branch: branch.branch_code, block_id: block.id}),
    onStackClick: chooseMapStack
  };
  let map = createYardMap(branch, branches, mapOptions);
  const reorder = canReorder ?
    enableQueueReordering(queue, run, id, () => map.accessBusy(), loadSuggestion) : null;
  const controls = el("div", undefined, "simulation-controls actions");
  const progress = el("strong");
  progress.setAttribute("aria-live", "polite");
  const next = el("button");
  next.type = "button";
  const chooseAlternate = el("button", "Choose alternate location", "secondary");
  chooseAlternate.type = "button";
  chooseAlternate.setAttribute("aria-controls", "alternate-location");
  const picker = alternateLocationPicker(branch, selectAlternate);
  const runToEnd = el("button", "Run to end", "run-to-end");
  runToEnd.type = "button";
  const viewTrace = el("button", "View trace", "secondary");
  viewTrace.type = "button";
  const compare = el("button", "Compare yard", "secondary");
  compare.type = "button";
  const snapshotPicker = el("input");
  snapshotPicker.type = "file";
  snapshotPicker.accept = ".csv";
  snapshotPicker.hidden = true;
  const buttons = el("div", undefined, "actions");
  buttons.append(next, chooseAlternate, viewTrace, runToEnd, compare);
  controls.append(progress, buttons);
  const outcome = el("div", undefined, "simulation-outcome");
  const traceLabel = el("label", undefined, "simulation-trace-picker");
  const tracePicker = el("select");
  const currentOption = el("option", "Current container");
  currentOption.value = "current";
  tracePicker.append(currentOption);
  traceLabel.append(el("strong", "View assignment"), tracePicker);
  const heading = el("h3");
  const status = el("p");
  status.setAttribute("role", "status");
  const details = el("div");
  outcome.append(heading, traceLabel, picker.element, status, details);
  const comparison = el("div", undefined, "yard-comparison");
  const comparisonStatus = el("p");
  comparisonStatus.setAttribute("role", "status");
  const comparisonResult = el("div");
  comparison.append(el("h3", "Yard comparison"), comparisonStatus, comparisonResult);
  comparison.hidden = !run.comparison;
  if (run.comparison) comparisonResult.append(yardComparisonResults(run.comparison));
  root.append(queuePanel, controls, outcome, snapshotPicker, comparison, map.element);

  function reportComparison(text, error = false) {
    comparison.hidden = false;
    comparisonStatus.textContent = text;
    comparisonStatus.classList.toggle("not-ready", error);
  }

  compare.addEventListener("click", () => snapshotPicker.click());
  onFile(snapshotPicker, async file => {
    reportComparison("Comparing yards…");
    comparison.scrollIntoView({block: "start"});
    const result = await globalThis.compareStackingYard({
      id, branch: branch.branch_code, name: file.name, text: await readText(file)
    });
    run.comparison = result;
    comparisonResult.replaceChildren(yardComparisonResults(result));
    reportComparison("");
  }, reportComparison);

  const finished = () => run.processed === branch.queue.length;

  function appendTraceOption({row}) {
    const option = el("option", "#" + row.position + " " + (row.container_id || "Missing container ID"));
    option.value = String(row.position - 1);
    tracePicker.append(option);
  }
  run.traces.forEach(appendTraceOption);

  let suggestionError = "";
  let choosingAlternate = false;
  let manualDestination = null;
  async function loadSuggestion() {
    run.suggestion = null;
    choosingAlternate = false;
    manualDestination = null;
    suggestionError = "";
    tracePicker.value = "current";
    showTrace();
    try {
      run.suggestion = await globalThis.suggestStackingAssignment({id, branch: branch.branch_code});
    } catch (error) {
      suggestionError = error.message;
    }
    showTrace();
  }

  function selectAlternate(destination) {
    manualDestination = destination;
    showTrace();
  }

  function chooseMapStack(location) {
    if (!choosingAlternate || tracePicker.value !== "current" || busy || map.accessBusy()) return;
    picker.select(location);
  }

  function displacedContainers() {
    if (!manualDestination) return [];
    const {block, row, slot, tier} = manualDestination;
    const yardBlock = branch.yard_map.blocks.find(item => item.code === block);
    const ids = footprintStacks(yardBlock, row, slot, run.suggestion.row.size)
      .flatMap(stack => stack.tiers.filter(item => item.tier === tier && item.container_id).map(item => item.container_id));
    return [...new Set(ids)];
  }

  chooseAlternate.addEventListener("click", () => {
    if (busy || map.accessBusy()) return;
    choosingAlternate = !choosingAlternate;
    if (choosingAlternate) picker.open(run.suggestion);
    else manualDestination = null;
    showTrace();
  });

  function showTrace() {
    const current = tracePicker.value === "current";
    const trace = current ? run.suggestion : run.traces[Number(tracePicker.value)];
    const winner = current ? trace?.calculation?.candidates.find(candidate => candidate.selected) : null;
    const manual = current ? manualDestination : trace?.manual_destination;
    const alternate = manual ?? trace?.calculation?.candidates.find(candidate => candidate.candidate_rank === trace.alternate_rank);
    const canChoose = current && Boolean(trace?.calculation);
    chooseAlternate.hidden = !canChoose;
    chooseAlternate.textContent = !choosingAlternate ? "Choose alternate location" :
      winner ? "Use engine recommendation" : "Cancel manual placement";
    chooseAlternate.setAttribute("aria-expanded", String(canChoose && choosingAlternate));
    picker.element.hidden = !canChoose || !choosingAlternate;
    picker.warn(displacedContainers());
    heading.textContent = current ? "Suggested assignment" : "Assignment trace";
    next.hidden = !current || (!trace && !suggestionError);
    next.classList.toggle("secondary", Boolean(manual || winner));
    runToEnd.hidden = !current || !trace;
    if (!trace) {
      next.textContent = "Retry suggestion";
      status.classList.toggle("not-ready", Boolean(suggestionError));
      status.textContent = suggestionError || "Calculating the suggested assignment…";
      details.replaceChildren();
      map.showTrace(null);
      return;
    }
    const {row, location, calculation} = trace;
    const label = "#" + row.position + " " + (row.container_id || "Missing container ID");
    status.classList.remove("not-ready");
    if (current) {
      next.textContent = manual ? "Place at manual location" : winner ? "Place container" : "Skip container";
      status.textContent = manual || winner ? label + (alternate ? " · Alternate selected · " : " · ") +
        placementLocation(alternate ?? winner, row.size) :
        label + " · " + row.reason;
    } else {
      status.textContent = location ? label + (alternate ? " placed at alternate · " : " placed · ") + location :
        label + (row.status === "invalid" ? " skipped · " : " unplaced · ") + row.reason;
    }
    details.replaceChildren(...(calculation ? [placementTrace(calculation, row.status, row.size, alternate, manual, trace.displaced)] : []));
    map.showTrace(current ? {...trace, manual_destination: manualDestination} : trace, !current && row.position !== run.processed);
  }
  tracePicker.addEventListener("change", showTrace);
  viewTrace.addEventListener("click", () => {
    outcome.scrollIntoView({block: "start"});
    tracePicker.focus({preventScroll: true});
  });

  function updateProgress() {
    const unplaced = run.processed - run.placed - run.invalid;
    progress.textContent = !branch.queue.length ? "No containers to process." : finished() ?
      "Simulation complete · " + run.placed + " placed · " + unplaced + " unplaced · " + run.invalid + " invalid" :
      run.processed + " of " + branch.queue.length + " processed · " + run.placed + " placed";
  }

  async function update() {
    reorder?.refresh();
    refreshDetails();
    map.setAccessEditable(run.processed === 0 && typeof globalThis.updateStackingBlockAccess === "function");
    const done = finished();
    updateProgress();
    compare.hidden = !done || !run.last || typeof globalThis.compareStackingYard !== "function";
    map.element.querySelector("h3").textContent = done && run.last ? "Final yard map" : "Yard map";
    const card = track.children[done ? run.processed - 1 : run.processed];
    if (card) {
      if (!done) card.setAttribute("aria-current", "step");
      const revealCurrent = () => {
        track.scrollLeft += card.getBoundingClientRect().left - track.getBoundingClientRect().left -
          parseFloat(getComputedStyle(track).paddingLeft);
      };
      if (track.isConnected) revealCurrent();
      else requestAnimationFrame(revealCurrent);
    }
    viewTrace.hidden = traceLabel.hidden = !run.last;
    outcome.hidden = done && !run.last;
    if (outcome.hidden) {
      next.hidden = chooseAlternate.hidden = runToEnd.hidden = true;
      map.showTrace(null);
      return;
    }
    currentOption.hidden = done;
    tracePicker.value = done ? String(run.processed - 1) : "current";
    if (!done && !run.suggestion) await loadSuggestion();
    else showTrace();
  }

  async function addContainer(fields) {
    if (map.accessBusy()) throw new Error("Wait for the yard access change to finish.");
    const row = await globalThis.addStackingQueueRow({id, branch: branch.branch_code, ...fields});
    queue.appendCard(row);
    if (run.comparison) {
      run.comparison = null;
      comparison.hidden = true;
      comparisonResult.replaceChildren();
    }
    await update();
    return row;
  }

  function deleteContainer(row) {
    if (busy || map.accessBusy() || row.position <= run.processed) return;
    const {position, input_position, container_id} = row;
    const label = container_id ? "container " + container_id : "row #" + position;
    if (!window.confirm("Delete " + label + " from the inbound queue?")) return;
    return action(async () => {
      await globalThis.deleteStackingQueueRow({id, branch: branch.branch_code, input_position});
      queue.removeCard(position);
      if (position === run.processed + 1) run.suggestion = null;
      await update();
      queue.focusAfterRemoval(position);
      queue.report((container_id || "Row #" + position) + " deleted from the inbound queue.");
    }, queue.report);
  }

  async function stepForward() {
    let step;
    try {
      step = await globalThis.stepStackingSimulation({
        id, branch: branch.branch_code, position: run.processed + 1, suggestion_id: run.suggestion?.suggestion_id,
        manual_destination: manualDestination
      });
    } catch (error) {
      if (manualDestination !== null) run.suggestion = null;
      throw error;
    }
    const card = track.children[run.processed];
    card.removeAttribute("aria-current");
    renderInboundCard(card, step.row);
    branch.queue[run.processed] = step.row;
    run.suggestion = null;
    choosingAlternate = false;
    manualDestination = null;
    run.processed++;
    if (run.processed === 1) onStart();
    run.placed += Number(step.row.status === "placed");
    run.invalid += Number(step.row.status === "invalid");
    run.last = step;
    const trace = {row: step.row, calculation: step.calculation, alternate_rank: step.alternate_rank,
      manual_destination: step.manual_destination, displaced: step.placement?.displaced,
      location: step.placement && placementLocation(step.placement)};
    run.traces.push(trace);
    appendTraceOption(trace);
    if (step.placement) {
      map.applyPlacement(step.placement);
      if (step.placement.manual) {
        const previousMap = map.element;
        map = createYardMap(branch, branches, mapOptions);
        previousMap.replaceWith(map.element);
      }
    }
  }

  function advance(toEnd) {
    if (busy || map.accessBusy()) return;
    const displaced = displacedContainers();
    if (displaced.length && !window.confirm("Replace " + displaced.join(", ") + " in this simulation?")) return;
    return action(async () => {
      map.setAccessEditable(false);
      track.inert = true;
      const start = run.processed;
      if (toEnd) {
        runToEnd.textContent = "Running…";
        map.showTrace(null);
      }
      try {
        while (!finished()) {
          await stepForward();
          if (!toEnd) break;
          updateProgress();
        }
      } finally {
        track.inert = false;
        runToEnd.textContent = "Run to end";
        if (run.processed > start) map.markPlacement(run.last.placement);
        await update();
      }
    }, (text, error) => {
      outcome.hidden = false;
      status.textContent = text;
      status.classList.toggle("not-ready", error);
    });
  }

  next.addEventListener("click", () => run.suggestion ? advance(false) : action(loadSuggestion));
  runToEnd.addEventListener("click", () => advance(true));
  if (run.last?.placement) map.markPlacement(run.last.placement);
  await update();
  return root;
}

const comparisonStatuses = {
  moved: "Different placement",
  simulated_only: "Simulation only",
  reference_only: "CSV only"
};
const comparisonPercent = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
const comparisonDelta = new Intl.NumberFormat(undefined, {signDisplay: "exceptZero", maximumFractionDigits: 1});
const comparisonMetrics = [
  ["Containers", "containers"],
  ["Occupied tier positions", "occupied_tiers"],
  ["Tier capacity", "tier_capacity"],
  ["Occupancy rate", "occupancy_rate", true],
  ["Parameter compliance", "parameter_compliance", true],
  ["Stack slots with tier gaps", "anomalous_stacks"],
  ["Dummy tier positions", "dummy_tiers"]
];

function comparisonValue(value, isPercent) {
  if (value == null) return "—";
  return isPercent ? comparisonPercent.format(value) : value.toLocaleString();
}

function comparisonRate(value, side) {
  if (value == null) return comparisonValue(value, true);
  const rate = el("div", undefined, "comparison-rate comparison-rate-" + side);
  const meter = el("meter");
  meter.min = 0;
  meter.max = 1;
  meter.value = value;
  meter.setAttribute("aria-hidden", "true");
  rate.append(meter, el("span", comparisonValue(value, true)));
  return rate;
}

function comparisonPlacement(location) {
  if (!location) return "—";
  const slots = location.size === "40" ? (location.slot - 1) + "–" + location.slot : location.slot;
  return "Block " + location.block + " · Row " + location.row + " · Slot " + slots +
    " · Tier " + location.tier + " · " + location.size + " ft";
}

function comparisonOccupancy(metrics) {
  return comparisonValue(metrics.occupied_tiers) + " / " + comparisonValue(metrics.tier_capacity) +
    " · " + comparisonValue(metrics.occupancy_rate, true);
}

function placementDifferences(differences) {
  const panel = el("div");
  if (!differences.length) {
    panel.append(el("p", "All container placements match."));
    return panel;
  }
  const filters = el("div", undefined, "actions comparison-filters");
  const search = el("input");
  search.type = "search";
  search.placeholder = "Find a container ID";
  search.setAttribute("aria-label", "Find a container ID");
  const status = el("select");
  status.setAttribute("aria-label", "Placement difference type");
  for (const [value, text] of [["", "All differences"], ...Object.entries(comparisonStatuses)]) {
    const option = el("option", text);
    option.value = value;
    status.append(option);
  }
  filters.append(search, status);
  const results = el("div");
  const pages = el("div", undefined, "actions comparison-pages");
  const previous = el("button", "Previous", "secondary");
  const next = el("button", "Next", "secondary");
  previous.type = next.type = "button";
  const position = el("span");
  position.setAttribute("role", "status");
  pages.append(previous, position, next);
  panel.append(filters, results, pages);

  const pageSize = 100;
  let offset = 0;
  function render() {
    const query = search.value.trim().toUpperCase();
    const matches = differences.filter(item => (!status.value || item.status === status.value) &&
      item.container.includes(query));
    results.replaceChildren(matches.length ?
      table(["Container", "Difference", "Simulation placement", "CSV placement"],
        matches.slice(offset, offset + pageSize).map(item => [
          item.container, comparisonStatuses[item.status], comparisonPlacement(item.simulated),
          comparisonPlacement(item.reference)
        ])) : el("p", "No matching placement differences."));
    pages.hidden = matches.length <= pageSize;
    position.textContent = (offset + 1) + "–" + Math.min(offset + pageSize, matches.length) + " of " + matches.length;
    previous.disabled = offset === 0;
    next.disabled = offset + pageSize >= matches.length;
  }
  function filter() {
    offset = 0;
    render();
  }
  search.addEventListener("input", filter);
  status.addEventListener("change", filter);
  previous.addEventListener("click", () => { offset -= pageSize; render(); });
  next.addEventListener("click", () => { offset += pageSize; render(); });
  render();
  return panel;
}

function yardComparisonResults(result) {
  const panel = el("div");
  panel.append(el("p", result.branch + " · " + result.file));
  if (result.excluded) panel.append(el("p", "CSV rows outside the selected branch: " + result.excluded, "note"));
  if (result.issues.length) {
    const details = el("details");
    details.append(el("summary", "Skipped CSV records (" + result.issues.length + ")"),
      table(["CSV line", "Container", "Reason"], result.issues.map(item => [
        item.line, item.container || "—", item.message
      ])));
    panel.append(details);
  }
  panel.append(el("h4", "Yard overview"),
    table(["Metric", "Simulation", "Imported CSV", "Simulation − CSV"],
      comparisonMetrics.map(([label, key, percent]) => {
        const actual = result.simulated[key];
        const reference = result.reference[key];
        const delta = actual == null || reference == null ? "—" :
          comparisonDelta.format((actual - reference) * (percent ? 100 : 1)) + (percent ? " pp" : "");
        return [label,
          percent ? comparisonRate(actual, "simulated") : comparisonValue(actual),
          percent ? comparisonRate(reference, "reference") : comparisonValue(reference),
          delta];
      })));
  if (result.simulated.dummy_tiers) {
    panel.append(el("p", "Simulation occupancy includes temporary dummy tiers. CSV occupancy counts the imported containers.", "note"));
  }
  const blocks = el("details");
  blocks.append(el("summary", "Overview by block"),
    table(["Block", "Simulation containers", "CSV containers", "Simulation occupancy", "CSV occupancy",
      "Simulation compliance", "CSV compliance"], result.blocks.map(({block, simulated, reference}) => [
      block, simulated.containers, reference.containers,
      comparisonOccupancy(simulated), comparisonOccupancy(reference),
      comparisonValue(simulated.parameter_compliance, true), comparisonValue(reference.parameter_compliance, true)
    ])));
  panel.append(blocks, yardComparisonMap(result.blocks), el("h4", "Container placements"),
    el("p", result.counts.same + " matching · " + result.counts.moved + " different · " +
      result.counts.simulated_only + " simulation only · " + result.counts.reference_only + " CSV only"),
    placementDifferences(result.differences));
  return panel;
}

function placementLocation(placement, size) {
  const slot = placement.stacks?.length === 2 || size === "40" ? "Slots " + (placement.slot - 1) + "–" + placement.slot :
    "Slot " + placement.slot;
  return "Block " + placement.block + " · Row " + placement.row + " · " + slot + " · Tier " + placement.tier;
}

const traceNumberFormat = new Intl.NumberFormat(undefined, {maximumSignificantDigits: 6});
const traceNumber = value => value == null ? "—" : traceNumberFormat.format(value);
const multiplierLabels = {
  mass_multiplier: "Mass multiplier",
  distance_multiplier: "Equipment distance multiplier",
  cluster_multiplier: "Size cluster multiplier",
  loader_destination_multiplier: "Destination reachability multiplier",
  loader_access_multiplier: "Occupied access preservation multiplier",
  future_loader_access_multiplier: "Future access preservation multiplier",
  stacking_safety_multiplier: "Pyramid stacking multiplier",
  capacity_multiplier: "Stack capacity multiplier"
};

const loaderAccessLabels = ["Loader can serve destination", "Occupied stacks losing access",
  "Future receiving options losing access"];

function loaderAccessValues(candidate) {
  const destination = candidate.loader_destination_accessible;
  return [
    destination == null ? "—" : destination ? "Yes" : "No",
    traceNumber(candidate.isolated_occupied_locations),
    traceNumber(candidate.isolated_future_locations)
  ];
}

function heuristicRows(candidate, multipliers = Object.keys(multiplierLabels)) {
  return [
    ...(!hasLoaderAccessDetails(candidate) ? [] :
      loaderAccessValues(candidate).map((value, i) => [loaderAccessLabels[i], value])),
    ...(candidate.overcapacity_tiers ? [["Tiers above capacity", candidate.overcapacity_tiers]] : []),
    ...multipliers.map(key => [multiplierLabels[key], traceNumber(candidate[key])]),
    ["Heuristic score", traceNumber(candidate.score)]
  ];
}

function hasLoaderAccessDetails(candidate) {
  return candidate.loader_destination_accessible != null || candidate.isolated_occupied_locations != null ||
    candidate.isolated_future_locations != null;
}

function heuristicTable(rows) {
  const breakdown = table(["Component", "Value"], rows);
  breakdown.classList.add("heuristic-breakdown");
  return breakdown;
}

function placementTrace(calculation, status, size, alternate, manual, displaced = []) {
  const number = traceNumber;
  const multipliers = calculation.enabled_multipliers ?? Object.keys(multiplierLabels);
  const reasons = {
    no_available_equipment: "No equipment can serve the block",
    unsupported_size: "Unsupported container size",
    invalid_location: "Invalid location",
    stack_unavailable: "Stack full or removed",
    size_conflict: "Stack serves a different container size",
    invalid_forty_foot_anchor: "Invalid 40 ft anchor slot",
    partner_size_conflict: "Partner slot incompatible",
    partner_tier_mismatch: "Partner slot has no matching tier",
    anomalous_stack: "Tier gap in the footprint",
    unsafe_stacking: "Stacking safety limit",
    loader_destination_inaccessible: "Loader cannot reach the destination",
    loader_occupied_access_blocked: "Placement would block access to existing containers",
    loader_access_blocked: "Placement would block access to future receiving locations"
  };
  const rejections = Object.entries(calculation.rejections).sort((a, b) => b[1] - a[1]);
  const rejected = rejections.reduce((total, [, count]) => total + count, 0);
  const feasible = calculation.checked - rejected;
  const winning = calculation.candidates.find(candidate => candidate.selected);
  const trace = el("div");
  const stages = el("ol", undefined, "simulation-trace-stages");
  stages.append(el("li", "Feasibility · " + number(feasible) + " of " + number(calculation.checked) +
    " locations passed" + (rejected ? " · " + number(rejected) + " rejected" : "")));
  if (feasible) {
    const rule = calculation.max_parameter_score > 0 ?
      "highest feasible parameter score " + number(calculation.max_parameter_score) :
      "no positive match, so only stacks without assigned parameters qualify";
    stages.append(el("li", "Parameter selection · " + rule + " · " +
      number(calculation.candidate_count) + " of " + number(feasible) + " advanced"));
  }
  if (winning) {
    const label = alternate ? "Engine recommendation" : status === "placed" ? "Selected location" : "Proposed location";
    const decision = el("li", label + " · " + placementLocation(winning, size) + " · " + (winning.equipment ?? "No equipment"));
    decision.append(heuristicTable(heuristicRows(winning, multipliers)));
    stages.append(decision);
    if (calculation.winning_score_ties > 1) {
      stages.append(el("li", "Tie-break · " + number(calculation.winning_score_ties) +
        " candidates tied for first. The engine ranked the first in yard scan order highest."));
    }
  }
  if (alternate) {
    const label = status === "placed" ? "Alternate placement" : "Alternate selected";
    const decision = el("li", label + " · " + placementLocation(alternate, size) +
      (manual ? " · Manual override" : " · " + (alternate.equipment ?? "No equipment")));
    if (manual && displaced.length) decision.append(el("p", "Replaced " + displaced.join(", ") + "."));
    if (!manual) decision.append(heuristicTable(heuristicRows(alternate, multipliers)));
    stages.append(decision);
  }
  trace.append(stages);

  const details = el("details");
  details.append(el("summary", "Show calculation details"));
  if (rejected) {
    details.append(table(["First rule that rejected the location", "Locations"], rejections.map(([reason, count]) =>
      [reasons[reason] ?? reason, number(count)])));
  }
  if (calculation.parameter_scores.length) {
    details.append(table(["Parameter", "Match score"], calculation.parameter_scores.map(parameter => [
      "P" + parameter.id + (parameter.name ? " · " + parameter.name : ""), number(parameter.score)
    ])));
  }
  if (calculation.candidates.length) {
    const showLoaderAccess = calculation.candidates.some(hasLoaderAccessDetails);
    details.append(el("p", "Locations that passed parameter selection, in yard order."));
    if (calculation.prioritize_current_loader_access) {
      details.append(el("p", calculation.prioritize_loader_destination ?
        "Ranking prefers accessible destinations, then fewer occupied stacks losing access, then a higher heuristic score." :
        "Ranking prefers fewer occupied stacks losing access, then a higher heuristic score."));
    }
    if (multipliers.length) {
      details.append(el("p", "Heuristic score = " + multipliers.map(key => multiplierLabels[key].toLowerCase()).join(" × ")));
    }
    details.append(el("p", "Mass difference is the supporting container's weight minus the inbound weight."));
    function showCandidates() {
      if (!details.open) return;
      details.removeEventListener("toggle", showCandidates);
      details.append(table(["Location", "Selection", "Parameters", "Equipment", "Distance", "Mass difference",
        ...(showLoaderAccess ? loaderAccessLabels : []),
        ...multipliers.map(key => multiplierLabels[key]), "Heuristic score"],
      calculation.candidates.map(candidate => [
        placementLocation(candidate, size),
        candidate === alternate ? (status === "placed" ? "Alternate placed" : "Alternate selected") :
          candidate.selected ? (alternate ? "Engine recommendation" : status === "placed" ? "Selected" : "Proposed") : "Alternative",
        candidate.parameters.map(parameter => "P" + parameter).join(", ") || "—", candidate.equipment ?? "No equipment",
        candidate.equipment_outside_block ? "Outside block" : number(candidate.distance),
        number(candidate.mass_difference), ...(showLoaderAccess ? loaderAccessValues(candidate) : []),
        ...multipliers.map(key => number(candidate[key])), number(candidate.score)
      ])));
    }
    details.addEventListener("toggle", showCandidates);
  }
  trace.append(details);
  return trace;
}
