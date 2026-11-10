"use strict";

function simulationView(run, branches, id) {
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
  const buttons = el("div", undefined, "actions");
  buttons.append(next, runToEnd, viewTrace);
  controls.append(progress, buttons);
  const outcome = el("div", undefined, "simulation-outcome");
  const traceLabel = el("label", undefined, "simulation-trace-picker");
  const tracePicker = el("select");
  traceLabel.append(el("strong", "Assignment trace"), tracePicker);
  const status = el("p");
  status.setAttribute("role", "status");
  const details = el("div");
  outcome.append(traceLabel, status, details);
  root.append(queue, controls, outcome, map.element);

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
  cluster_multiplier: "Size cluster multiplier"
};

function heuristicRows(candidate, multipliers = Object.keys(multiplierLabels)) {
  return [
    ...multipliers.map(key => [multiplierLabels[key], traceNumber(candidate[key])]),
    ["Heuristic score", traceNumber(candidate.score)]
  ];
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
        " candidates shared the top score. The engine used the first in yard scan order."));
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
    details.append(el("p", "Locations that passed parameter selection, in yard order."));
    if (multipliers.length) {
      details.append(el("p", "Heuristic score = " + multipliers.map(key => multiplierLabels[key].toLowerCase()).join(" × ")));
    }
    details.append(el("p", "Mass difference is the supporting container's weight minus the inbound weight."));
    function showCandidates() {
      if (!details.open) return;
      details.removeEventListener("toggle", showCandidates);
      details.append(table(["Location", "Selection", "Parameters", "Equipment", "Distance", "Mass difference",
        ...multipliers.map(key => multiplierLabels[key]), "Heuristic score"],
      calculation.candidates.map(candidate => [
        placementLocation(candidate),
        candidate.selected ? (status === "placed" ? "Selected" : "Proposed") : "Alternative",
        candidate.parameters.map(parameter => "P" + parameter).join(", ") || "—", candidate.equipment,
        candidate.equipment_outside_block ? "Outside block" : number(candidate.distance),
        number(candidate.mass_difference), ...multipliers.map(key => number(candidate[key])), number(candidate.score)
      ])));
    }
    details.addEventListener("toggle", showCandidates);
  }
  trace.append(details);
  return trace;
}
