"use strict";

function simulationView(run, branches, id, onStart) {
  const {branch} = run;
  const root = el("div");
  const queue = inboundQueue(branch);
  const track = queue.querySelector(".inbound-track");
  const map = createYardMap(branch, branches);
  const controls = el("div", undefined, "simulation-controls actions");
  const progress = el("strong");
  progress.setAttribute("aria-live", "polite");
  const next = el("button");
  next.type = "button";
  const runToEnd = el("button", "Run to end", "secondary");
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
  buttons.append(next, runToEnd, viewTrace, compare);
  controls.append(progress, buttons);
  const outcome = el("div", undefined, "simulation-outcome");
  const traceLabel = el("label", undefined, "simulation-trace-picker");
  const tracePicker = el("select");
  traceLabel.append(el("strong", "Assignment trace"), tracePicker);
  const status = el("p");
  status.setAttribute("role", "status");
  const details = el("div");
  outcome.append(traceLabel, status, details);
  const comparison = el("div", undefined, "yard-comparison");
  const comparisonStatus = el("p");
  comparisonStatus.setAttribute("role", "status");
  const comparisonResult = el("div");
  comparison.append(el("h3", "Yard comparison"), comparisonStatus, comparisonResult);
  comparison.hidden = !run.comparison;
  if (run.comparison) comparisonResult.append(yardComparisonResults(run.comparison));
  root.append(queue, controls, outcome, snapshotPicker, comparison, map.element);

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

  function showTrace() {
    const trace = run.traces[Number(tracePicker.value)];
    const {row, location, calculation} = trace;
    const label = "#" + row.position + " " + (row.container_id || "Missing container ID");
    status.classList.remove("not-ready");
    status.textContent = location ? label + " placed · " + location :
      label + (row.status === "invalid" ? " skipped · " : " unplaced · ") + row.reason;
    details.replaceChildren(...(calculation ? [placementTrace(calculation, row.status)] : []));
    map.showTrace(trace, row.position !== run.processed);
  }
  tracePicker.addEventListener("change", showTrace);
  viewTrace.addEventListener("click", () => {
    outcome.scrollIntoView({block: "start"});
    tracePicker.focus({preventScroll: true});
  });

  function updateProgress() {
    const unplaced = run.processed - run.placed - run.invalid;
    progress.textContent = finished() ?
      "Simulation complete · " + run.placed + " placed · " + unplaced + " unplaced · " + run.invalid + " invalid" :
      run.processed + " of " + branch.queue.length + " processed · " + run.placed + " placed";
  }

  function update() {
    const done = finished();
    updateProgress();
    next.textContent = run.processed ? "Next container" : "Start simulation";
    next.hidden = runToEnd.hidden = done;
    compare.hidden = !done || typeof globalThis.compareStackingYard !== "function";
    map.element.querySelector("h3").textContent = done ? "Final yard map" : "Yard map";
    const card = track.children[done ? run.processed - 1 : run.processed];
    if (card) {
      if (!done) card.setAttribute("aria-current", "step");
      const revealCurrent = () => {
        track.scrollLeft += card.getBoundingClientRect().left - track.getBoundingClientRect().left - 2;
      };
      if (track.isConnected) revealCurrent();
      else requestAnimationFrame(revealCurrent);
    }
    outcome.hidden = !run.last;
    viewTrace.hidden = traceLabel.hidden = !run.last;
    if (run.last) {
      tracePicker.value = String(run.processed - 1);
      showTrace();
    }
  }

  async function stepForward() {
    const step = await globalThis.stepStackingSimulation({
      id, branch: branch.branch_code, position: run.processed + 1
    });
    const card = track.children[run.processed];
    card.removeAttribute("aria-current");
    renderInboundCard(card, step.row);
    branch.queue[run.processed] = step.row;
    run.processed++;
    if (run.processed === 1) onStart();
    run.placed += Number(step.row.status === "placed");
    run.invalid += Number(step.row.status === "invalid");
    run.last = step;
    const trace = {row: step.row, calculation: step.calculation,
      location: step.placement && placementLocation(step.placement)};
    run.traces.push(trace);
    appendTraceOption(trace);
    if (step.placement) map.applyPlacement(step.placement);
  }

  function advance(toEnd) {
    return action(async () => {
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
        runToEnd.textContent = "Run to end";
        update();
        if (run.processed > start) map.markPlacement(run.last.placement, true);
      }
    }, (text, error) => {
      outcome.hidden = false;
      status.textContent = text;
      status.classList.toggle("not-ready", error);
    });
  }

  next.addEventListener("click", () => advance(false));
  runToEnd.addEventListener("click", () => advance(true));
  update();
  if (run.last?.placement) map.markPlacement(run.last.placement);
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

function placementLocation(placement) {
  const slot = placement.stacks?.length === 2 ? "Slots " + (placement.slot - 1) + "–" + placement.slot :
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

function placementTrace(calculation, status) {
  const number = traceNumber;
  const multipliers = calculation.enabled_multipliers ?? Object.keys(multiplierLabels);
  const reasons = {
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
    const label = status === "placed" ? "Selected location" : "Proposed location";
    const decision = el("li", label + " · " + placementLocation(winning) + " · " + winning.equipment);
    decision.append(heuristicTable(heuristicRows(winning, multipliers)));
    stages.append(decision);
    if (calculation.winning_score_ties > 1) {
      stages.append(el("li", "Tie-break · " + number(calculation.winning_score_ties) +
        " candidates tied for first. The engine used the first in yard scan order."));
    }
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
        placementLocation(candidate),
        candidate.selected ? (status === "placed" ? "Selected" : "Proposed") : "Alternative",
        candidate.parameters.map(parameter => "P" + parameter).join(", ") || "—", candidate.equipment,
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
