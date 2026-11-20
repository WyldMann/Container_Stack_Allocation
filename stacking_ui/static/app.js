"use strict";

const $ = id => document.getElementById(id);
const descriptions = {
  terminal_branches: ["Terminal branches", "Branch codes, IDs, and display names."],
  yard_blocks: ["Yard blocks", "Dimensions, tier limits, and block positions."],
  existing_containers: ["Current containers", "The current yard snapshot."],
  inbound_containers: ["Inbound containers", "Containers to assign, in CSV order."],
  removed_slots: ["Removed slots", "Locations unavailable for stacking."],
  parameters: ["Parameters", "Matching criteria and their scores."],
  yard_planning: ["Yard planning", "Parameters assigned to yard locations."],
  master_equipment: ["Master equipment", "Equipment codes and types."],
  equipment_history: ["Equipment locations", "Movement history used to select latest locations."]
};
const tomlEditors = {
  config: "config_toml",
  input: "input_toml",
  mapping: "mapping_toml"
};
const tomlDocuments = {};
const ruleModes = ["off", "heuristic", "feasibility"];
const ruleModeKeys = ["stacking_safety_mode", "stack_capacity_mode", "loader_destination_access_mode",
  "preserve_occupied_loader_access_mode", "preserve_future_loader_access_mode"];
const stackingScoringOption = {key: "stacking_safety_limit_multiplier", mode: "stacking", defaultValue: "0.25",
  label: "Score at maximum difference",
  description: "The score declines linearly to this multiplier (0–1) at the maximum difference. Enable the bound to reject larger differences."};
const capacityScoringOption = {key: "overcapacity_tier_multiplier", mode: "capacity", defaultValue: "0.01",
  label: "Per extra tier multiplier",
  description: "Apply this multiplier (0–1) once per tier above nominal capacity. One removes the penalty."};
const boundedRuleWeights = [stackingScoringOption, capacityScoringOption];
const fallbackScoreKeys = ["heavier_container_fallback_score", "equipment_outside_block_fallback_score"];
const loaderScoringOptions = [
  {key: "loader_inaccessible_destination_multiplier", mode: "destination", defaultValue: "0.25",
    label: "Unreachable destination multiplier",
    description: "Multiply the placement score by this value (0–1) when the loader cannot reach the destination."},
  {key: "loader_occupied_access_loss_weight", mode: "occupied", defaultValue: "1.0",
    label: "Occupied access loss weight",
    description: "Higher values penalize cutting off occupied stacks more. Zero removes this score penalty."},
  {key: "loader_future_access_loss_weight", mode: "future", defaultValue: "1.0",
    label: "Future access loss weight",
    description: "Higher values penalize cutting off future receiving options more. Zero removes this score penalty."}
];
const stackingNeighborDefaults = {up: true, down: true, left: false, right: false};
const stackingNeighborPaths = Object.keys(stackingNeighborDefaults).map(direction => "feasibility.stacking_safety_neighbor_" + direction);
const placementGroups = [
  {title: "Stack capacity", graph: "capacity", options: {
    "feasibility.stack_capacity_mode": ["Enforce stack height limit",
      "Feasibility enforces the tier limit. Heuristic allows overcapacity with a score penalty. Off allows overcapacity without a capacity penalty."],
    "heuristic.overcapacity_tier_multiplier": [capacityScoringOption.label, capacityScoringOption.description]
  }},
  {title: "Stacking safety", graph: "pyramid", neighborSwitches: true, options: {
    "feasibility.stacking_safety_mode": ["Pyramid stacking",
      "Decrease score applies the curve. Enforce maximum difference rejects placements above the maximum. Turn off either one or both."],
    "feasibility.stacking_safety_penalty_start": ["Start reducing score",
      "Full score up to this tier difference after placement. Enter a whole number from 0 to one below the maximum difference."],
    "feasibility.stacking_safety_maxima": ["Maximum tier difference",
      "The curve reaches its endpoint here. With the bound enabled, larger differences are rejected; otherwise the endpoint score continues. Minimum 1."],
    ...Object.fromEntries(Object.keys(stackingNeighborDefaults).map(direction =>
      ["feasibility.stacking_safety_neighbor_" + direction, [direction[0].toUpperCase() + direction.slice(1),
        "Consider the " + direction + " side of the stack footprint for pyramid support."]])),
    "heuristic.stacking_safety_limit_multiplier": [stackingScoringOption.label, stackingScoringOption.description]
  }},
  {title: "Loader reachability and access preservation", description:
    "Off skips the rule. Heuristic scores it. Feasibility rejects placements that fail it. These rules apply to loader-served blocks.",
  rowGraphs: ["destination", "occupied", "future"],
  optionRows: [
    ["feasibility.loader_destination_access_mode", "heuristic.loader_inaccessible_destination_multiplier"],
    ["feasibility.preserve_occupied_loader_access_mode", "heuristic.loader_occupied_access_loss_weight",
      "feasibility.ignore_full_stacks_for_loader_access"],
    ["feasibility.preserve_future_loader_access_mode", "heuristic.loader_future_access_loss_weight"]
  ],
  options: {
    "feasibility.loader_destination_access_mode": ["Currently loader accessible",
      "Check whether the loader can reach this placement location before placing the container."],
    "feasibility.preserve_occupied_loader_access_mode": ["Preserve access to occupied stacks",
      "Check whether this placement cuts off access to containers already in the yard."],
    "feasibility.preserve_future_loader_access_mode": ["Preserve access to future receiving locations",
      "Check whether this placement cuts off access to locations with room for more containers."],
    "feasibility.ignore_full_stacks_for_loader_access": ["Ignore full stacks",
      "Exclude stacks at or above capacity from occupied-stack access preservation."],
    ...Object.fromEntries(loaderScoringOptions.map(({key, label, description}) =>
      ["heuristic." + key, [label, description]]))
  }},
  {title: "Container weight difference", graph: "weight", sideBySide: true, toggle: "heuristic.enable_delta_container_mass", options: {
    "heuristic.enable_delta_container_mass": ["Score container weight difference",
      "Subtract the incoming container's weight from the weight of the container directly beneath it to score the placement."],
    "heuristic.w_delta_container_mass": ["Maximum weight score",
      "Score for placing a container on one of the same weight."],
    "heuristic.hl_delta_container_mass": ["Weight difference for half score",
      "The score halves when the supporting container is heavier by this amount. Uses the CSV weight units."],
    "heuristic.no_delta_container_mass_value": ["Unknown weight score",
      "Use this score when either container's weight is unavailable."],
    "heuristic.heavier_container_fallback_score": ["Heavier incoming container score",
      "Use this score when the incoming container is heavier than the one beneath it."]
  }},
  {title: "Equipment distance", graph: "equipment", sideBySide: true, toggle: "heuristic.enable_equipment_distance", options: {
    "heuristic.enable_equipment_distance": ["Score equipment distance",
      "Use the distance from the serving equipment to rank placements."],
    "heuristic.w_equipment_distance": ["Maximum distance score",
      "Score when the equipment is already at the placement location."],
    "heuristic.hl_equipment_distance": ["Distance for half score",
      "The distance score halves at this distance, measured in yard grid units."],
    "heuristic.equipment_outside_block_fallback_score": ["Equipment outside block score",
      "Use this score when the serving equipment is outside the block."]
  }},
  {title: "Container size clustering", graph: "cluster",
  description: "Encourages compact groups of same-size containers and separation between different sizes.",
  formulaText: "Clustering multiplier = same-size reward × different-size penalty",
  sections: [
    {title: "Same-size reward", style: "reward", formula: "bₛ · S / (S + pₛ)",
      description: "Favors placements near same-size stacks, helping matching containers form compact groups.",
      evidenceDescription: "S is the distance-weighted total of same-size neighboring stacks. This term is at least 1×.",
      toggle: "heuristic.enable_size_cluster_reward",
      paths: ["heuristic.enable_size_cluster_reward", "heuristic.size_cluster_reward_radius", "heuristic.hl_size_cluster_reward_distance",
        "heuristic.size_cluster_reward_bias", "heuristic.size_cluster_reward_prior"]},
    {title: "Different-size penalty", style: "penalty", formula: "−bₒ · O / (O + pₒ)",
      description: "Lowers scores near different-size stacks, encouraging separation between container sizes.",
      evidenceDescription: "O is the distance-weighted total of different-size neighboring stacks. This term is at most 1×.",
      toggle: "heuristic.enable_size_cluster_penalty",
      paths: ["heuristic.enable_size_cluster_penalty", "heuristic.size_cluster_penalty_radius", "heuristic.hl_size_cluster_penalty_distance",
        "heuristic.size_cluster_penalty_bias", "heuristic.size_cluster_penalty_prior"]}
  ], options: {
    "heuristic.enable_size_cluster_reward": ["Enable same-size reward",
      "Reward matching neighbors. Off gives a neutral reward of 1× and keeps these settings for later."],
    "heuristic.enable_size_cluster_penalty": ["Enable different-size penalty",
      "Penalize different-size neighbors. Off gives a neutral penalty of 1× and keeps these settings for later."],
    "heuristic.size_cluster_reward_radius": ["Reward search radius",
      "Reward matching stacks within this many yard grid units. Zero disables only the reward."],
    "heuristic.hl_size_cluster_reward_distance": ["Reward distance for half influence",
      "A matching stack's evidence halves at this distance, measured in yard grid units."],
    "heuristic.size_cluster_reward_bias": ["Reward strength (bₛ)",
      "The reward approaches 2 raised to this value. Zero disables only the same-size reward."],
    "heuristic.size_cluster_reward_prior": ["Reward smoothing (pₛ)",
      "Positive denominator offset for same-size evidence. Higher values make the reward build more slowly."],
    "heuristic.size_cluster_penalty_radius": ["Penalty search radius",
      "Penalize different-size stacks within this many yard grid units. Zero disables only the penalty."],
    "heuristic.hl_size_cluster_penalty_distance": ["Penalty distance for half influence",
      "A different-size stack's evidence halves at this distance, measured in yard grid units."],
    "heuristic.size_cluster_penalty_bias": ["Penalty strength (bₒ)",
      "The penalty approaches 2 raised to the negative of this value. Zero disables only the different-size penalty."],
    "heuristic.size_cluster_penalty_prior": ["Penalty smoothing (pₒ)",
      "Positive denominator offset for different-size evidence. Higher values make the penalty build more slowly."]
  }}
];
const placementOptions = Object.assign({}, ...placementGroups.map(group => group.options));
const standalone = globalThis.stackingStandalone === true;
const canReadProjectTomls = typeof globalThis.readStackingTomls === "function";
const bundledTomls = typeof TOML_DEFAULTS === "undefined" ? {} : TOML_DEFAULTS;
let projectTomls = {...bundledTomls};
const browserDefaults = {};
let projectTomlsLive = false;
const tomlKey = /(?:[A-Za-z0-9_-]+|"(?:\\.|[^"\\])*"|'[^']*')/.source;
const tomlPath = tomlKey + "(?:[ \\t]*\\.[ \\t]*" + tomlKey + ")*";
const tomlAssignment = new RegExp("^([ \\t]*(" + tomlPath + ")[ \\t]*=[ \\t]*)");
const tomlTable = new RegExp("^\\[\\[?[ \\t]*(" + tomlPath + ")[ \\t]*\\]\\]?[ \\t]*(?:#.*)?$");
const tomlPathParts = new RegExp(tomlKey, "g");
let files = {};
let busy = false;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function message(text = "", error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
}

function changed() {
  $("save-yard").hidden = true;
  previewStatus("");
  $("results").replaceChildren(el("div", "Inputs changed. Generate a new preview to review them.", "empty"));
}

async function action(task, report = message) {
  if (busy) return;
  busy = true;
  const controls = document.querySelectorAll("button:enabled,input:enabled,textarea:enabled,select:enabled");
  controls.forEach(node => node.disabled = true);
  try {
    await task();
  } catch (error) {
    report(error.message, true);
  } finally {
    busy = false;
    controls.forEach(node => node.disabled = false);
    const {ruleControls, placementRows} = tomlDocuments.config;
    updateRuleControls(ruleControls, placementRows);
    updatePlacementDependencies(placementRows);
    Object.keys(tomlEditors).forEach(updateTomlSave);
  }
}

async function readText(file) {
  return new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
}

function onFile(input, handler, report) {
  input.addEventListener("change", () => action(async () => {
    const file = input.files[0];
    if (!file) return;
    input.value = "";
    await handler(file);
  }, report));
}

function tomlValueEnd(source, start, stopAtComma = false) {
  // Find the next comment or newline outside strings, arrays, and inline tables.
  let quote = "";
  let depth = 0;
  for (let index = start; index < source.length; index++) {
    const character = source[index];
    if (quote) {
      if (character === "\\" && quote.startsWith('"')) {
        index++;
      } else if (source.startsWith(quote, index)) {
        index += quote.length - 1;
        if (quote.length === 3) {
          // Multiline strings can end in one or two literal quote characters.
          for (let extra = 0; extra < 2 && source[index + 1] === quote[0]; extra++) index++;
        }
        quote = "";
      }
    } else if (character === '"' || character === "'") {
      const triple = character.repeat(3);
      quote = source.startsWith(triple, index) ? triple : character;
      index += quote.length - 1;
    } else if (character === "[" || character === "{") {
      depth++;
    } else if (character === "]" || character === "}") {
      depth = Math.max(0, depth - 1);
    } else if (character === "#") {
      if (!depth) return index;
      const newline = source.indexOf("\n", index);
      if (newline === -1) return source.length;
      index = newline;
    } else if (!depth && (character === "\n" || (stopAtComma && character === ","))) {
      return index;
    }
  }
  return source.length;
}

function tomlParts(path) {
  return (path.match(tomlPathParts) ?? []).map(part => part.replace(/^["']|["']$/g, ""));
}

function omittedTomlPath(kind, [root, key]) {
  return root === "sql" || (kind === "input" && (
    (root === "input" && key === "sources") ||
    (root === "csv" && key === "mapping_file") ||
    root === "output"
  ));
}

function addPlacementOption(rows, path, row, control) {
  const [label, description] = placementOptions[path];
  const options = rows.get(path) ?? [];
  const help = el("p", description, "placement-help");
  help.id = "placement-" + path.replace(".", "-") + "-" + options.length;
  row.firstElementChild.textContent = label;
  control.setAttribute("aria-describedby", help.id);
  const option = el("div", undefined, "placement-option");
  option.append(row, help);
  options.push(option);
  rows.set(path, options);
  return option;
}

function showPlacementGroups(editor, rows, graphs) {
  const groups = el("div", undefined, "placement-groups");
  const weightAndDistance = el("div", undefined, "placement-weight-distance");
  for (const {title, description, formulaText, options, optionRows, sideBySide, graph, rowGraphs, sections, neighborSwitches} of placementGroups) {
    const sectionPaths = new Set(sections?.flatMap(section => section.paths));
    if (neighborSwitches) for (const path of stackingNeighborPaths) sectionPaths.add(path);
    const entries = Object.keys(options).filter(path => !sectionPaths.has(path)).flatMap(path => rows.get(path) ?? []);
    const group = el("fieldset", undefined, "placement-group");
    group.append(el("legend", title));
    if (description) group.append(el("p", description, "placement-help"));
    if (formulaText) group.append(el("p", formulaText, "cluster-formula"));
    if (optionRows) {
      for (const [index, paths] of optionRows.entries()) {
        const related = paths.flatMap(path => rows.get(path) ?? []);
        const list = el("div", undefined, "placement-options placement-related-options");
        list.append(...related, graphs[rowGraphs[index]].element);
        group.append(list);
      }
    } else {
      const list = el("div", undefined, "placement-options");
      list.append(...entries);
      if (neighborSwitches) list.append(pyramidNeighborSwitches(rows));
      group.append(list);
    }
    if (sections) {
      const terms = el("div", undefined, "cluster-terms");
      for (const section of sections) {
        const term = el("section", undefined, "cluster-term " + section.style);
        const formula = el("p", (section.style === "reward" ? "Reward" : "Penalty") + " = 2", "cluster-formula");
        formula.append(el("sup", section.formula));
        const controls = el("div", undefined, "placement-options");
        controls.append(...section.paths.flatMap(path => rows.get(path) ?? []));
        term.append(el("h4", section.title), el("p", section.description, "placement-help"),
          formula, el("p", section.evidenceDescription, "placement-help"), controls);
        terms.append(term);
      }
      group.append(terms);
    }
    if (graph) group.append(graphs[graph].element);
    if (sideBySide) {
      if (!weightAndDistance.parentNode) groups.append(weightAndDistance);
      weightAndDistance.append(group);
    } else {
      groups.append(group);
    }
  }
  editor.replaceChildren(groups);
}

function pyramidNeighborSwitches(rows) {
  const panel = el("div", undefined, "pyramid-neighbor-editor");
  const title = el("h4", "Considered neighbors");
  title.id = "pyramid-neighbor-label";
  const diagram = el("div", undefined, "pyramid-neighbor-grid");
  diagram.setAttribute("role", "group");
  diagram.setAttribute("aria-labelledby", title.id);
  const stack = el("div", "Stack", "pyramid-neighbor-stack");
  stack.setAttribute("aria-hidden", "true");
  diagram.append(stack);
  for (const direction of Object.keys(stackingNeighborDefaults)) {
    for (const option of rows.get("feasibility.stacking_safety_neighbor_" + direction) ?? []) {
      option.classList.add("pyramid-neighbor", "pyramid-neighbor-" + direction);
      option.querySelector("input").setAttribute("aria-label", "Consider " + direction + " neighbor");
      diagram.append(option);
    }
  }
  panel.append(title, el("p", "Any enabled side can provide support. With all sides off, measure height above the ground.", "placement-help"), diagram);
  return panel;
}

function readInlinePlacementOptions(options, section, literal) {
  if (!literal.startsWith("{") || !literal.endsWith("}")) return;
  const body = literal.slice(1, -1);
  for (let cursor = 0; cursor < body.length;) {
    const match = tomlAssignment.exec(body.slice(cursor));
    if (!match) break;
    const start = cursor + match[1].length;
    const end = tomlValueEnd(body, start, true);
    options.set(section + "." + tomlParts(match[2]).join("."), body.slice(start, end).trimEnd());
    cursor = end + 1;
  }
}

function placementGraphValue(rows, inline, path) {
  const option = rows.get(path)?.[0];
  if (!option) return inline.get(path);
  if (path === "feasibility.stacking_safety_mode" && tomlDocuments.config.ruleControls.stacking_safety_mode?.switches) {
    return JSON.stringify(tomlDocuments.config.ruleControls.stacking_safety_mode.mode);
  }
  const selectedMode = option.querySelector("input[type=radio]:checked");
  if (selectedMode) return JSON.stringify(selectedMode.value);
  const number = option.querySelector("input[type=number]");
  if (number?.dataset.currentValue !== undefined) return number.dataset.currentValue;
  if (number) return number.getAttribute("aria-invalid") === "true" ? "" : number.value;
  const input = option.querySelector("input, textarea");
  return input ? tomlFieldValue(input) : undefined;
}

function setPlacementInactive(option, inactive) {
  option.classList.toggle("is-inactive", inactive);
  for (const input of option.querySelectorAll("input, textarea")) input.disabled = busy || inactive;
}

function updatePlacementDependencies(rows) {
  const isOff = path => rows.get(path)?.[0].querySelector('input[type="checkbox"]')?.checked === false;
  for (const {toggle, options, sections} of placementGroups) {
    const dependencies = toggle ? [{toggle, paths: Object.keys(options)}] : sections ?? [];
    for (const {toggle, paths} of dependencies) {
      if (!toggle) continue;
      const inactive = isOff(toggle);
      for (const path of paths) {
        if (path === toggle) continue;
        for (const option of rows.get(path) ?? []) setPlacementInactive(option, inactive);
      }
    }
  }
}

function ruleModeSwitch(controls, rows, key, prefix, value, fallback = "feasibility") {
  const legacy = !key.endsWith("_mode");
  const modeKey = legacy ? key + "_mode" : key;
  if (key.startsWith("preserve_future_")) fallback = null;
  const original = value === null ? "" : prefix + value;
  const initial = value === null || (legacy && value === "true") ? fallback :
    legacy ? "off" : value.match(/^["']{1,3}(off|heuristic|feasibility|combined)["']{1,3}$/)?.[1];
  if (initial === undefined || (legacy && value !== "true" && value !== "false")) return null;
  if (initial === "combined" && modeKey !== "stacking_safety_mode") return null;

  const modePrefix = legacy ? prefix.replace(/(["']?)([ \t]*=[ \t]*)$/, "_mode$1$2") : prefix;
  const input = el("input");
  input.type = "hidden";
  input.value = original;
  const row = el("div", undefined, "toml-setting");
  const label = el("span", modeKey + ":");
  label.id = modeKey + "-label";
  const group = el("div", undefined, "toml-segments");
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-labelledby", label.id);
  const control = {row, group, input, mode: initial, choices: []};
  control.select = (mode, explicit = false) => {
    control.mode = mode;
    input.value = mode === initial && !explicit ? original :
      modePrefix + JSON.stringify(mode) + (value === null ? "\n" : "");
  };
  if (modeKey === "stacking_safety_mode") {
    group.className = "pyramid-rule-switches";
    group.setAttribute("role", "group");
    control.switches = [];
    for (const [feature, title] of [["decay", "Decrease score"], ["bound", "Enforce maximum difference"]]) {
      const choice = el("input");
      choice.type = "checkbox";
      choice.setAttribute("role", "switch");
      choice.dataset.feature = feature;
      const option = el("label", undefined, "pyramid-feature-switch");
      const toggle = el("span", undefined, "toml-switch");
      const track = el("span", undefined, "toml-switch-track");
      track.setAttribute("aria-hidden", "true");
      toggle.append(choice, track);
      option.append(el("span", title), toggle);
      group.append(option);
      control.switches.push(choice);
      choice.addEventListener("change", () => {
        const [decay, bound] = control.switches.map(input => input.checked);
        control.select(decay ? (bound ? "combined" : "heuristic") : (bound ? "feasibility" : "off"));
        updateRuleControls(controls, rows);
        updateTomlSave("config");
        changed();
      });
    }
  } else for (const mode of ruleModes) {
    const choice = el("input");
    choice.type = "radio";
    choice.name = modeKey;
    choice.value = mode;
    const option = el("label");
    option.append(choice, el("span", mode[0].toUpperCase() + mode.slice(1)));
    group.append(option);
    control.choices.push(choice);
    choice.addEventListener("change", () => {
      control.select(mode, modeKey === "preserve_occupied_loader_access_mode" && value === null);
      if (modeKey === "preserve_future_loader_access_mode" && !controls.preserve_occupied_loader_access_mode?.input.value) {
        controls.preserve_occupied_loader_access_mode?.select(controls.preserve_occupied_loader_access_mode.mode, true);
      }
      updateRuleControls(controls, rows);
      updateTomlSave("config");
      changed();
    });
  }
  row.append(label, group);
  controls[modeKey] = control;
  return control;
}

function updateRuleControls(controls, rows) {
  const stacking = controls.stacking_safety_mode;
  const capacity = controls.stack_capacity_mode;
  const destination = controls.loader_destination_access_mode;
  const occupied = controls.preserve_occupied_loader_access_mode;
  const future = controls.preserve_future_loader_access_mode;
  const occupiedMode = occupied?.mode ?? "feasibility";
  for (const control of [stacking, capacity, destination, occupied, future]) {
    for (const choice of control?.choices ?? []) {
      choice.checked = choice.value === (control.mode ?? occupiedMode);
      choice.disabled = busy;
    }
  }
  for (const choice of stacking?.switches ?? []) {
    choice.checked = choice.dataset.feature === "decay" ?
      ["heuristic", "combined"].includes(stacking.mode) : ["feasibility", "combined"].includes(stacking.mode);
    choice.disabled = busy;
  }
  if (controls.ignoreFull) setPlacementInactive(controls.ignoreFull, occupiedMode === "off");
  for (const path of ["feasibility.stacking_safety_maxima", ...stackingNeighborPaths]) {
    for (const option of rows.get(path) ?? []) setPlacementInactive(option, stacking?.mode === "off");
  }
  for (const option of rows.get("feasibility.stacking_safety_penalty_start") ?? []) {
    setPlacementInactive(option, !["heuristic", "combined"].includes(stacking?.mode));
  }
  const effectiveModes = {stacking: stacking?.mode, capacity: capacity?.mode, destination: destination?.mode,
    occupied: occupiedMode, future: future?.mode ?? occupiedMode};
  for (const {key, mode: scoringMode} of [...boundedRuleWeights, ...loaderScoringOptions]) {
    for (const option of rows.get("heuristic." + key) ?? []) {
      setPlacementInactive(option, effectiveModes[scoringMode] !== "heuristic" &&
        !(scoringMode === "stacking" && effectiveModes.stacking === "combined"));
    }
  }
}

function addBoundedRuleWeight(rows, fields, start, end, value, {key, defaultValue, label, previousValue}, prefix = "") {
  const slider = el("input");
  slider.type = "range";
  slider.min = "0";
  slider.max = "1";
  slider.setAttribute("aria-label", label);
  const number = el("input");
  number.type = "number";
  number.min = slider.min;
  number.max = slider.max;
  number.step = "any";
  number.setAttribute("aria-label", label);

  function syncValue(next) {
    slider.step = Number(next.toFixed(2)) === next ? "0.01" : "any";
    slider.value = String(next);
    number.value = slider.value;
  }

  const literal = value ?? defaultValue;
  const initial = Number(literal.replaceAll("_", ""));
  const numeric = /^[+-]?(?:0|[1-9](?:_?\d)*)(?:\.\d(?:_?\d)*)?(?:e[+-]?\d(?:_?\d)*)?$/i.test(literal);
  const valid = numeric && initial >= 0 && initial <= 1;
  const pyramid = key === "stacking_safety_limit_multiplier";
  const fallback = Number(previousValue ?? defaultValue);
  const repaired = numeric && Number.isFinite(initial) ? Math.max(0, Math.min(1, initial)) :
    Number.isFinite(fallback) ? Math.max(0, Math.min(1, fallback)) : 0.25;
  syncValue(valid ? initial : pyramid ? repaired : Number(defaultValue));

  const control = el("span", undefined, "toml-range");
  control.append(slider, number);
  const row = el("div", undefined, "toml-setting");
  row.append(el("span"), control);
  const option = addPlacementOption(rows, "heuristic." + key, row, slider);
  number.setAttribute("aria-describedby", slider.getAttribute("aria-describedby"));
  const warning = el("p", "The TOML value must be a number from 0 to 1. Use either control to replace it.", "placement-help");
  warning.hidden = valid || pyramid;
  if (!valid && !pyramid) number.setAttribute("aria-invalid", "true");
  option.append(warning);

  let edited = pyramid && !valid;
  function applyValue(next) {
    syncValue(next);
    edited = true;
    warning.hidden = true;
    number.removeAttribute("aria-invalid");
    updateTomlSave("config");
    changed();
  }

  slider.addEventListener("input", () => applyValue(slider.valueAsNumber));
  number.addEventListener("input", () => {
    number.removeAttribute("aria-invalid");
    refreshPlacementGraphs();
  });
  function commitNumber() {
    if (!Number.isFinite(number.valueAsNumber)) {
      number.value = slider.value;
      if (!warning.hidden) number.setAttribute("aria-invalid", "true");
      refreshPlacementGraphs();
      return;
    }
    const capped = Math.max(0, Math.min(1, number.valueAsNumber));
    if (capped !== slider.valueAsNumber || !warning.hidden) applyValue(capped);
    else {
      number.value = slider.value;
      refreshPlacementGraphs();
    }
  }
  number.addEventListener("blur", commitNumber);
  number.addEventListener("keydown", event => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    commitNumber();
  });
  fields.push({start, end, input: slider, format: current => {
    if (!edited) return value ?? "";
    if (value !== null) return current;
    return current === defaultValue ? "" : prefix + current + "\n";
  }});
}

function addMissingHeuristicScores(rows, fields, source, offset, legacyFallbackScore, inline) {
  const separator = offset && source[offset - 1] !== "\n" ? "\n" : "";
  const fallbacks = fallbackScoreKeys.map(key => ({key, defaultValue: legacyFallbackScore}));
  const clustering = ["reward", "penalty"].flatMap(term => [
    {key: "enable_size_cluster_" + term, boolean: true, defaultValue: inline.get("heuristic.enable_size_cluster") ?? "true"},
    ...["radius", "bias", "prior"].map(parameter => ({
      key: "size_cluster_" + term + "_" + parameter,
      defaultValue: inline.get("heuristic.size_cluster_" + parameter) ??
        ({radius: "3", bias: "1.0", prior: "2.0"})[parameter]
    })),
    {key: "hl_size_cluster_" + term + "_distance", defaultValue: inline.get("heuristic.hl_size_cluster_distance") ?? "1.5"}
  ]);
  for (const setting of [...boundedRuleWeights, ...loaderScoringOptions, ...fallbacks, ...clustering]) {
    const {key, defaultValue} = setting;
    const path = "heuristic." + key;
    if (rows.has(path)) continue;
    const prefix = separator + (offset ? key : path) + " = ";
    if (boundedRuleWeights.includes(setting)) {
      const fallbackSetting = setting === stackingScoringOption ?
        {...setting, defaultValue: inline.get("heuristic.unsafe_stacking_multiplier") ?? defaultValue} : setting;
      addBoundedRuleWeight(rows, fields, offset, offset, null, fallbackSetting, prefix);
      continue;
    }
    const input = el("input");
    input.type = setting.boolean ? "checkbox" : "text";
    if (setting.boolean) {
      input.checked = defaultValue === "true";
      input.setAttribute("role", "switch");
    } else {
      input.inputMode = "decimal";
      input.value = defaultValue;
    }
    input.spellcheck = false;
    input.addEventListener("input", () => {
      if (setting.boolean) updatePlacementDependencies(rows);
      updateTomlSave("config");
      changed();
    });
    const row = el("label", undefined, "toml-setting");
    row.append(el("span"));
    if (setting.boolean) {
      const toggle = el("span", undefined, "toml-switch");
      const track = el("span", undefined, "toml-switch-track");
      track.setAttribute("aria-hidden", "true");
      toggle.append(input, track);
      row.append(toggle);
    } else {
      row.append(input);
    }
    addPlacementOption(rows, path, row, input);
    fields.push({start: offset, end: offset, input,
      format: value => value === defaultValue ? "" : prefix + value + "\n"});
  }
}

function addStackingSafetyMaxima(rows, fields, start, end, value, prefix = "", previousValue = "2", key = "stacking_safety_maxima") {
  const path = "feasibility." + key;
  const soft = key === "stacking_safety_penalty_start";
  const minimum = soft ? 0n : 1n;
  const hard = rows.get("feasibility.stacking_safety_maxima")?.[0]?.querySelector("input")?.dataset.currentValue ?? "2";
  const defaultValue = soft ? String(Math.min(1, Number(hard) - 1)) : "2";
  const input = el("input");
  input.type = "number";
  input.min = String(minimum);
  input.step = "1";
  input.required = true;
  input.inputMode = "numeric";
  const literal = value ?? defaultValue;
  const integer = /^[+-]?(?:0|[1-9](?:_?\d)*)$|^0x[\da-fA-F](?:_?[\da-fA-F])*$|^0o[0-7](?:_?[0-7])*$|^0b[01](?:_?[01])*$/;
  input.value = integer.test(literal) ? BigInt(literal.replaceAll("_", "")).toString() : literal;
  function normalizedValue() {
    if (input.value !== "" && input.valueAsNumber < Number(minimum)) return String(minimum);
    return /^\d+$/.test(input.value) && BigInt(input.value) >= minimum ? BigInt(input.value).toString() : null;
  }
  let currentValue = normalizedValue() ?? previousValue;
  let edited = !integer.test(literal) || BigInt(literal.replaceAll("_", "")) < minimum;
  input.value = currentValue;
  input.dataset.currentValue = currentValue;
  input.spellcheck = false;
  const row = el("label", undefined, "toml-setting");
  row.append(el("span"), input);
  const option = addPlacementOption(rows, path, row, input);
  const warning = el("p", "Enter a whole number of " + minimum + " or greater.", "placement-help error");
  warning.id = input.getAttribute("aria-describedby") + "-error";
  input.setAttribute("aria-describedby", input.getAttribute("aria-describedby") + " " + warning.id);
  warning.setAttribute("aria-live", "polite");
  option.append(warning);
  function validate() {
    const valid = /^\d+$/.test(input.value) && BigInt(input.value) >= minimum;
    input.setCustomValidity(valid ? "" : warning.textContent);
    input.setAttribute("aria-invalid", String(!valid));
    warning.hidden = valid;
  }
  validate();
  input.commitPyramidValue = next => {
    currentValue = next;
    input.dataset.currentValue = next;
    input.value = next;
    edited = true;
    validate();
  };
  input.addEventListener("input", () => {
    const next = normalizedValue();
    if (next !== null && next !== currentValue) {
      currentValue = next;
      input.dataset.currentValue = currentValue;
      edited = true;
    }
    validate();
    updateTomlSave("config");
    changed();
  });
  function commitNumber() {
    input.value = currentValue;
    validate();
  }
  input.addEventListener("blur", commitNumber);
  input.addEventListener("keydown", event => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    commitNumber();
  });
  fields.push({start, end, input, format: () => {
    if (!edited) return value ?? "";
    if (value !== null) return currentValue;
    return currentValue === defaultValue ? "" : prefix + currentValue + "\n";
  }});
}

function addMissingStackingSafetyMaxima(rows, fields, source, offset) {
  const separator = offset && source[offset - 1] !== "\n" ? "\n" : "";
  for (const key of ["stacking_safety_maxima", "stacking_safety_penalty_start"]) {
    if (rows.has("feasibility." + key)) continue;
    const prefix = separator + (offset ? key : "feasibility." + key) + " = ";
    addStackingSafetyMaxima(rows, fields, offset, offset, null, prefix, key.endsWith("penalty_start") ? "1" : "2", key);
  }
}

function syncPyramidThresholds(rows) {
  const hard = rows.get("feasibility.stacking_safety_maxima")?.[0]?.querySelector("input");
  const soft = rows.get("feasibility.stacking_safety_penalty_start")?.[0]?.querySelector("input");
  if (!hard || !soft) return;
  const maximum = BigInt(hard.dataset.currentValue) - 1n;
  soft.max = String(maximum);
  if (BigInt(soft.dataset.currentValue) > maximum) soft.commitPyramidValue(String(maximum));
}

function addMissingStackingNeighbors(rows, fields, source, offset) {
  const separator = offset && source[offset - 1] !== "\n" ? "\n" : "";
  for (const [direction, enabled] of Object.entries(stackingNeighborDefaults)) {
    const key = "stacking_safety_neighbor_" + direction;
    const path = "feasibility." + key;
    if (rows.has(path)) continue;
    const input = el("input");
    input.type = "checkbox";
    input.checked = enabled;
    input.setAttribute("role", "switch");
    input.addEventListener("input", () => {
      updateTomlSave("config");
      changed();
    });
    const row = el("label", undefined, "toml-setting");
    const toggle = el("span", undefined, "toml-switch");
    const track = el("span", undefined, "toml-switch-track");
    track.setAttribute("aria-hidden", "true");
    toggle.append(input, track);
    row.append(el("span"), toggle);
    addPlacementOption(rows, path, row, input);
    const prefix = separator + (offset ? key : path) + " = ";
    fields.push({start: offset, end: offset, input,
      format: value => value === String(enabled) ? "" : prefix + value + "\n"});
  }
}

function showToml(kind, text, loadedFrom) {
  const previousMaxima = tomlDocuments.config?.placementRows.get("feasibility.stacking_safety_maxima")?.[0]
    .querySelector("input")?.dataset.currentValue ?? "2";
  const previousPenaltyStart = tomlDocuments.config?.placementRows.get("feasibility.stacking_safety_penalty_start")?.[0]
    .querySelector("input")?.dataset.currentValue ?? "1";
  const previousLimitMultiplier = tomlDocuments.config?.placementRows.get("heuristic.stacking_safety_limit_multiplier")?.[0]
    .querySelector('input[type="range"]')?.value ?? "0.25";
  const source = text.replace(/\r\n?/g, "\n");
  const fields = [];
  const csvPaths = new Map();
  const ruleControls = {};
  const placementRows = new Map();
  const inlinePlacement = new Map();
  const editor = $(kind + "-toml");
  if (kind === "config") {
    for (const graph of Object.values(tomlDocuments.config?.graphs ?? {})) graph.disconnect();
  }
  editor.replaceChildren();
  tomlDocuments[kind] = {
    source, fields, csvPaths, ruleControls, placementRows,
    usesProject: loadedFrom == null, projectText: projectTomls[tomlEditors[kind]]
  };

  let section = "";
  let statementStart = 0;
  let feasibilityStart = 0;
  let heuristicStart = 0;
  let inlineFeasibility = false;
  let inlineHeuristic = false;
  let legacyLoaderMode = "feasibility";
  let legacyFallbackScore = "0.001";
  const seenModes = new Set();
  const comments = [];
  for (let offset = 0; offset < source.length;) {
    let lineEnd = source.indexOf("\n", offset);
    if (lineEnd === -1) lineEnd = source.length;
    const line = source.slice(offset, lineEnd);
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      if (trimmed) comments.push(trimmed);
      offset = lineEnd + 1;
      continue;
    }

    const table = tomlTable.exec(trimmed);
    if (table) section = table[1];
    const match = tomlAssignment.exec(line);
    const path = match ? [section, match[2]].filter(Boolean).join(".") : section;
    const parts = tomlParts(path);
    const [root, key, dataset] = parts;
    const modeKey = kind === "config" && root === "feasibility" && parts.length === 2 &&
      ruleModeKeys.find(mode => mode === key || mode === key + "_mode");
    const optionPath = [root, modeKey || key].join(".");
    const knownOption = kind === "config" && parts.length === 2 && Object.hasOwn(placementOptions, optionPath);
    const legacyLoaderOption = kind === "config" && root === "feasibility" && parts.length === 2 &&
      (key === "loader_access" || key === "loader_access_mode");
    const legacyFallbackOption = kind === "config" && parts.length === 2 && optionPath === "heuristic.min_value";
    const legacyStackingOption = kind === "config" && parts.length === 2 && optionPath === "heuristic.unsafe_stacking_multiplier";
    const legacyClusterOption = kind === "config" && root === "heuristic" && parts.length === 2 &&
      ["enable_size_cluster", "size_cluster_radius", "hl_size_cluster_distance", "size_cluster_prior", "size_cluster_bias"].includes(key);
    if (kind === "config" && root === "feasibility" && parts.length === 1) {
      if (table) feasibilityStart = Math.min(lineEnd + 1, source.length);
      else if (match) inlineFeasibility = true;
    }
    if (kind === "config" && root === "heuristic" && parts.length === 1) {
      if (table) heuristicStart = Math.min(lineEnd + 1, source.length);
      else if (match) inlineHeuristic = true;
    }
    const omitted = omittedTomlPath(kind, parts);
    const inFileCards = kind === "input" && root === "csv" && key === "files";
    const isCsvPath = inFileCards && match && parts.length === 3 && Object.hasOwn(descriptions, dataset);
    const visible = !omitted && !inFileCards &&
      !(kind === "input" && table && root === "csv" && parts.length === 1);
    if (visible && kind !== "config") {
      for (const comment of comments) editor.append(el("p", comment, "toml-comment"));
    }
    comments.length = 0;

    if (match) {
      const start = offset + match[1].length;
      const boundary = tomlValueEnd(source, start);
      lineEnd = source.indexOf("\n", boundary);
      if (lineEnd === -1) lineEnd = source.length;
      if ((visible && (kind !== "config" || knownOption || legacyLoaderOption || legacyFallbackOption || legacyClusterOption || legacyStackingOption)) || isCsvPath) {
        const value = source.slice(start, boundary).trimEnd();
        if (legacyFallbackOption || legacyClusterOption || legacyStackingOption) {
          if (legacyFallbackOption) legacyFallbackScore = value;
          inlinePlacement.set(optionPath, value);
          offset = statementStart = lineEnd + 1;
          continue;
        }
        if (legacyLoaderOption) {
          inlinePlacement.set(optionPath, value);
          const legacy = key === "loader_access" ?
            (value === "true" ? "feasibility" : value === "false" ? "off" : null) :
            value.match(/^["']{1,3}(off|heuristic|feasibility)["']{1,3}$/)?.[1];
          if (legacy) {
            legacyLoaderMode = legacy;
          }
          offset = statementStart = lineEnd + 1;
          continue;
        }
        if (knownOption && ["feasibility.stacking_safety_maxima", "feasibility.stacking_safety_penalty_start"].includes(optionPath)) {
          addStackingSafetyMaxima(placementRows, fields, start, start + value.length, value, "",
            key === "stacking_safety_maxima" ? previousMaxima : previousPenaltyStart, key);
          offset = statementStart = lineEnd + 1;
          continue;
        }
        const boundedWeight = knownOption && root === "heuristic" &&
          boundedRuleWeights.find(setting => setting.key === key);
        if (boundedWeight) {
          addBoundedRuleWeight(placementRows, fields, start, start + value.length, value,
            boundedWeight === stackingScoringOption ? {...boundedWeight, previousValue: previousLimitMultiplier} : boundedWeight);
          offset = statementStart = lineEnd + 1;
          continue;
        }
        if (modeKey) {
          seenModes.add(modeKey);
          const control = ruleModeSwitch(ruleControls, placementRows, key, match[1], value);
          if (control) {
            control.option = addPlacementOption(placementRows, optionPath, control.row, control.group);
            fields.push({start: offset, end: start + value.length, input: control.input});
            offset = statementStart = lineEnd + 1;
            continue;
          }
        }
        const multiline = value.includes("\n");
        const boolean = !isCsvPath && (value === "true" || value === "false");
        const input = el(multiline ? "textarea" : "input");
        if (multiline) {
          input.rows = Math.min(8, value.split("\n").length);
        } else if (boolean) {
          input.type = "checkbox";
          input.checked = value === "true";
          input.setAttribute("role", "switch");
        } else {
          input.type = "text";
        }
        input.spellcheck = false;
        if (!boolean) input.value = value;
        input.addEventListener("input", () => {
          if (knownOption && boolean) updatePlacementDependencies(placementRows);
          updateTomlSave(kind);
          changed();
        });
        if (isCsvPath) {
          csvPaths.set(dataset, input);
        } else {
          const comment = source.slice(boundary, lineEnd);
          if (comment && !knownOption) editor.append(el("p", comment, "toml-comment"));
          const label = el("label", undefined, "toml-setting");
          label.append(el("span", match[2] + ":"));
          if (boolean) {
            const toggle = el("span", undefined, "toml-switch");
            const track = el("span", undefined, "toml-switch-track");
            track.setAttribute("aria-hidden", "true");
            toggle.append(input, track);
            label.append(toggle);
          } else {
            label.append(input);
          }
          if (knownOption) {
            const option = addPlacementOption(placementRows, optionPath, label, input);
            if (optionPath === "feasibility.ignore_full_stacks_for_loader_access" && boolean) {
              ruleControls.ignoreFull = option;
            }
          } else {
            editor.append(label);
          }
        }
        fields.push({start, end: start + value.length, input});
      } else if (kind === "config" && parts.length === 1 && (root === "heuristic" || root === "feasibility")) {
        readInlinePlacementOptions(inlinePlacement, root, source.slice(start, boundary).trimEnd());
      }
    } else if (visible && kind !== "config") {
      editor.append(el(table ? "h4" : "p", trimmed, table ? "toml-section" : "toml-comment"));
    }
    offset = lineEnd + 1;
    if (omitted) fields.push({start: statementStart, end: Math.min(offset, source.length)});
    statementStart = Math.min(offset, source.length);
  }
  if (omittedTomlPath(kind, tomlParts(section))) {
    fields.push({start: statementStart, end: source.length});
  } else if (kind !== "config") {
    for (const comment of comments) editor.append(el("p", comment, "toml-comment"));
  }
  if (kind === "config") {
    if (!inlineFeasibility) {
      const separator = feasibilityStart && source[feasibilityStart - 1] !== "\n" ? "\n" : "";
      for (const key of ruleModeKeys.filter(key => !seenModes.has(key))) {
        const prefix = separator + (feasibilityStart ? key : "feasibility." + key) + " = ";
        const fallback = key.includes("loader_") ? legacyLoaderMode : "feasibility";
        const control = ruleModeSwitch(ruleControls, placementRows, key, prefix, null, fallback);
        control.option = addPlacementOption(placementRows, "feasibility." + key, control.row, control.group);
        fields.push({start: feasibilityStart, end: feasibilityStart, input: control.input});
      }
      addMissingStackingSafetyMaxima(placementRows, fields, source, feasibilityStart);
      addMissingStackingNeighbors(placementRows, fields, source, feasibilityStart);
    }
    if (!inlineHeuristic) addMissingHeuristicScores(placementRows, fields, source, heuristicStart, legacyFallbackScore, inlinePlacement);
    fields.sort((a, b) => a.start - b.start || a.end - b.end);
    updateRuleControls(ruleControls, placementRows);
    updatePlacementDependencies(placementRows);
    const graphs = createPlacementGraphs(path => placementGraphValue(placementRows, inlinePlacement, path));
    tomlDocuments.config.graphs = graphs;
    showPlacementGroups(editor, placementRows, graphs);
  }
  const status = $(kind + "-toml-source");
  const origin = standalone ? (browserDefaults[tomlEditors[kind]] == null ?
    "Bundled TOML: " : "Browser default: ") : projectTomlsLive ? "Loaded project TOML: " :
    projectTomls[tomlEditors[kind]] != null ? "Cached project TOML: " : "Project TOML unavailable: ";
  tomlDocuments[kind].sourceLabel = loadedFrom ?? (origin + status.dataset.projectFile);
  updateTomlSave(kind);
}

function tomlFieldValue(input, format) {
  const value = input.type === "checkbox" ? String(input.checked) : input.value;
  return format ? format(value) : value;
}

async function refreshProjectTomls(replace = false) {
  const fresh = await globalThis.readStackingTomls();
  const wasLive = projectTomlsLive;
  projectTomls = fresh;
  projectTomlsLive = true;
  let refreshed = false;
  for (const [kind, key] of Object.entries(tomlEditors)) {
    const {source, fields, usesProject} = tomlDocuments[kind];
    const unedited = usesProject && fields.every(({start, end, input, format}) =>
      !input || tomlFieldValue(input, format) === source.slice(start, end));
    if (replace || (unedited && (!wasLive || source !== fresh[key].replace(/\r\n?/g, "\n")))) {
      showToml(kind, fresh[key]);
      refreshed = true;
    }
  }
  if (refreshed) showDatasets();
  return refreshed;
}

function editedToml({source, fields}, preserveHidden = false) {
  let cursor = 0;
  let result = "";
  for (const {start, end, input, format} of fields) {
    if (!input && preserveHidden) continue;
    result += source.slice(cursor, start) + (input ? tomlFieldValue(input, format) : "");
    cursor = end;
  }
  return result + source.slice(cursor);
}

function refreshPlacementGraphs() {
  for (const graph of Object.values(tomlDocuments.config.graphs ?? {})) graph.update();
}

function updateTomlSave(kind) {
  const document = tomlDocuments[kind];
  if (kind === "config") syncPyramidThresholds(document.placementRows);
  const key = tomlEditors[kind];
  const text = editedToml(document, true);
  const persisted = projectTomls[key];
  const dirty = typeof persisted === "string" &&
    text !== persisted.replace(/\r\n?/g, "\n");
  $("save-" + kind).disabled = busy || !dirty;
  const status = $(kind + "-toml-source");
  if (standalone) {
    const defaultText = browserDefaults[key] ?? bundledTomls[key];
    $("default-" + kind).disabled = busy || text === defaultText?.replace(/\r\n?/g, "\n");
  }
  const modified = standalone ? text !== document.source : dirty;
  const label = modified ? document.sourceLabel + (standalone ? " · Edited" : " · Unsaved changes") :
    document.saved ? "Saved " + status.dataset.projectFile : document.sourceLabel;
  if (status.textContent !== label) status.textContent = label;
  if (kind === "config") refreshPlacementGraphs();
}

function buildDraft() {
  const useFolder = $("source-folder").checked;
  const useBundled = standalone && useFolder;
  let selectedFiles = files;
  if (useFolder) {
    selectedFiles = useBundled ? {} : Object.fromEntries(
      Object.entries(files).filter(([, upload]) => upload.empty === true));
  }
  const draft = {
    version: 1,
    file_source: standalone ? "bundle" : useFolder ? "folder" : "upload",
    files: selectedFiles
  };
  for (const [kind, key] of Object.entries(tomlEditors)) {
    draft[key] = editedToml(tomlDocuments[kind]);
  }
  if (useBundled) {
    const branchCode = $("bundled-branch").value;
    if (!branchCode) throw new Error("No yard branches are available in the bundled CSVs.");
    draft.branch_codes = [branchCode];
    draft.input_toml = bundledTomls.input_toml;
  }
  return draft;
}

function csvFolderPath(value) {
  const literal = value.trim();
  if (literal.length < 2 || literal[0] !== literal.at(-1) || !"\"'".includes(literal[0])) {
    throw new Error("Each CSV path in the input TOML must be a quoted string.");
  }
  return literal.slice(1, -1).replaceAll("\\", "/").replace(/\/+/g, "/").toLowerCase();
}

function matchCsvFolder(selectedFiles) {
  const entries = selectedFiles.filter(file => file.name.toLowerCase().endsWith(".csv")).map(file => ({
    file, path: (file.webkitRelativePath || file.name).replaceAll("\\", "/").toLowerCase()
  }));
  const matches = new Map();
  const missing = [];
  for (const name of Object.keys(descriptions)) {
    const field = tomlDocuments.input.csvPaths.get(name);
    if (!field) throw new Error("The input TOML has no CSV path for " + name + ".");
    const path = csvFolderPath(tomlFieldValue(field));
    const filename = path.split("/").at(-1);
    const exact = entries.filter(entry => path === entry.path || path.endsWith("/" + entry.path));
    const candidates = exact.length ? exact : entries.filter(entry => entry.file.name.toLowerCase() === filename);
    if (candidates.length > 1) throw new Error("Several files match " + name + ". Select a narrower CSV folder.");
    if (!candidates.length) missing.push(name);
    else matches.set(name, candidates[0].file);
  }
  if (missing.length) throw new Error("CSV folder is missing files for: " + missing.join(", ") + ".");
  return matches;
}

function showDatasets() {
  const grid = $("datasets");
  const useFolder = $("source-folder").checked;
  const useBundled = standalone && useFolder;
  const description = $("source-description");
  if (useBundled) {
    description.textContent = "Using the nine CSVs included in this package.";
  } else if (useFolder) {
    description.textContent = "Use the prefilled CSV paths or edit them below. Relative paths start in config/container_stacking. Keep the quotes around each path.";
  } else {
    const individualHelp = standalone
      ? "Choose individual UTF-8 CSVs to replace bundled files."
      : "Choose a UTF-8 CSV for each dataset, or mark it explicitly empty.";
    description.textContent = individualHelp +
      " Selecting a CSV folder replaces all nine input files at once." +
      " The folder must contain all nine CSVs named in Input configuration.";
  }
  $("choose-csv-folder").hidden = useFolder;
  $("bundled-inputs").hidden = !useBundled;
  $("stacking-inputs").hidden = useBundled;
  grid.hidden = useBundled;
  grid.replaceChildren();
  if (useBundled) return;
  for (const [name, [title, description]] of Object.entries(descriptions)) {
    const card = el("div", undefined, "dataset");
    card.append(el("strong", title), el("small", description));

    const input = el("input");
    input.type = "file";
    input.accept = ".csv";
    input.setAttribute("aria-label", title + " CSV");

    const upload = files[name];
    const empty = el("input");
    empty.type = "checkbox";
    empty.checked = upload?.empty === true;
    const pathField = tomlDocuments.input.csvPaths.get(name);
    const csvPath = useFolder && !standalone ? pathField : undefined;
    const sourceLabel = standalone ? (pathField ? tomlFieldValue(pathField) : "Use configured CSV path") :
      useFolder ? (csvPath ? "" : "Use configured CSV path") : "No file selected";
    const filename = el("div", empty.checked ? "Explicitly empty dataset" :
      (useFolder ? sourceLabel : upload?.name ?? sourceLabel), "filename");

    onFile(input, async file => {
      if (!file.name.toLowerCase().endsWith(".csv")) throw new Error("Select a CSV file.");
      files[name] = {name: file.name, content: await readText(file)};
      filename.textContent = file.name;
      empty.checked = false;
      changed();
      message();
    });
    empty.addEventListener("change", () => {
      if (empty.checked) {
        files[name] = {name: name + ".csv", empty: true};
        filename.textContent = "Explicitly empty dataset";
      } else {
        delete files[name];
        filename.textContent = sourceLabel;
      }
      changed();
    });
    const label = el("label", undefined, "empty-choice");
    label.append(empty, el("span", "Use an empty dataset"));
    if (csvPath) {
      const pathLabel = el("label", "CSV path", "dataset-path");
      csvPath.setAttribute("aria-label", title + " CSV path");
      pathLabel.append(csvPath);
      card.append(pathLabel);
    } else if (!useFolder) {
      card.append(input);
    }
    card.append(filename, label);
    grid.append(card);
  }
}

function setupBundledBranches() {
  const select = $("bundled-branch");
  const {branches, default_code: defaultCode} = STACKING_YARD_BRANCHES;
  for (const {code, name} of branches) {
    const option = el("option", name ? code + " · " + name : code);
    option.value = code;
    select.append(option);
  }
  if (defaultCode) select.value = defaultCode;
  if (!branches.length) {
    const option = el("option", "No yard branches available");
    option.value = "";
    select.append(option);
    select.disabled = true;
  }
  select.addEventListener("change", changed);
}

function table(headers, rows) {
  const wrap = el("div", undefined, "table-scroll");
  const grid = el("table");
  const head = el("thead");
  const headerRow = el("tr");
  for (const name of headers) headerRow.append(el("th", name));
  head.append(headerRow);

  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const value of row) {
      const cell = el("td");
      if (value instanceof Node) cell.append(value);
      else cell.textContent = String(value ?? "");
      tr.append(cell);
    }
    body.append(tr);
  }
  grid.append(head, body);
  wrap.append(grid);
  return wrap;
}

function issueCounts(items) {
  const counts = new Map();
  for (const {severity} of items) counts.set(severity, (counts.get(severity) ?? 0) + 1);
  return ["error", "warning"].filter(severity => counts.has(severity)).map(severity => {
    const count = counts.get(severity);
    return count + " " + severity + (count === 1 ? "" : "s");
  }).join(" · ");
}

function issueOverview(items) {
  if (!items.length) return null;
  const groups = new Map();
  for (const item of items) {
    const title = item.category === "overlap" ? "Overlapping containers" :
      descriptions[item.dataset]?.[0] ?? (item.dataset === "scenario" ? "Scenario setup" : item.dataset);
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(item);
  }
  const panel = el("div", undefined, "preview-diagnostics preview-issues");
  panel.append(el("h3", "Input and yard issues"), el("p", issueCounts(items)));
  for (const [title, group] of groups) {
    const details = el("details");
    details.append(el("summary", title + " · " + issueCounts(group)),
      table(["Severity", "Field", "Source", "Issue"], group.map(item => [
        item.severity,
        item.field?.replaceAll("_", " ") || "—",
        item.sources.map(source => source.file + ":" + source.line).join(", ") || "Dataset-level check",
        item.message
      ])));
    panel.append(details);
  }
  return panel;
}

function previewStatus(text, error = false) {
  const status = $("preview-status");
  status.textContent = text;
  status.className = error ? "not-ready" : "";
}

function renderInboundCard(card, row) {
  card.className = "inbound-card inbound-" + row.status;
  card.replaceChildren(el("span", "#" + row.position, "inbound-position"),
    el("strong", row.container_id || "Missing container ID"),
    el("span", (row.size ? row.size + " ft · " : "") +
      "Operation: " + (row.operation || "—") + " · " + row.status, "inbound-meta"));
  if (row.reason && row.status !== "invalid") card.append(el("span", row.reason, "inbound-reason"));
}

function inboundQueue(branch) {
  const panel = el("div", undefined, "inbound-queue");
  panel.append(el("h3", "Inbound queue"));
  if (branch.inbound_available === false) {
    panel.append(el("p", "Inbound queue unavailable."));
    return panel;
  }
  if (!branch.queue.length) {
    panel.append(el("p", "No incoming containers."));
    return panel;
  }
  panel.append(el("p", branch.queue.length + " containers · CSV order"));
  const track = el("ol", undefined, "inbound-track");
  track.setAttribute("aria-label", "Incoming containers in CSV order");
  track.tabIndex = 0;
  for (const row of branch.queue) {
    const card = el("li");
    renderInboundCard(card, row);
    track.append(card);
  }
  panel.append(track);
  return panel;
}

function tierGapOverview(branch, repair) {
  const gaps = branch.tier_gaps ?? [];
  if (!gaps.length) return null;
  const open = branch.summary.anomalous_stacks;
  const filled = branch.summary.stacks_with_dummy_containers;
  const panel = el("div", undefined, "preview-diagnostics tier-gap-overview");
  panel.append(el("h3", "Yard tier gaps"), el("p",
    "Stack slots with open gaps: " + open + " · Stack slots with dummy tiers: " + filled));
  if (open && repair && !branch.tier_gap_repair_attempted) {
    const button = el("button", "Fill gaps with dummy containers", "secondary");
    button.type = "button";
    button.addEventListener("click", repair);
    panel.append(button);
  } else if (open) {
    panel.append(el("p", branch.tier_gap_repair_attempted ? "Some gaps could not be filled safely." :
      "Generate a fresh preview to fill gaps before starting this branch.", "note"));
  }
  panel.append(el("p", "Dummy containers count as occupied for this preview and are excluded from exported CSVs. " +
    "Generate a new preview to clear them.", "note"));
  const details = el("details");
  details.append(el("summary", "View affected stack slots"),
    table(["Block", "Row", "Slot", "Open tiers", "Dummy-filled tiers"], gaps.map(gap => [
      gap.block, gap.row, gap.slot, gap.missing_tiers.join(", ") || "—", gap.dummy_tiers.join(", ") || "—"
    ])));
  panel.append(details);
  return panel;
}

function previewOverview(branches, simulation, sharedIssues) {
  const overview = el("div");
  const selectedView = el("div");
  const runs = new Map();
  function showBranch(branch) {
    const gapPanel = el("div");
    function renderGaps() {
      const canRepair = simulation && !runs.get(branch)?.processed &&
        typeof globalThis.repairStackingTierGaps === "function";
      const repair = canRepair ? () => action(async () => {
        const repaired = await globalThis.repairStackingTierGaps({id: simulation.id, branch: branch.branch_code});
        Object.assign(branch, repaired);
        runs.delete(branch);
        showBranch(branch);
        previewStatus("Updated tier gaps for " + branch.branch_code + ".");
      }, previewStatus) : null;
      const panel = tierGapOverview(branch, repair);
      gapPanel.replaceChildren(...(panel ? [panel] : []));
    }
    renderGaps();
    const branchIssues = issueOverview([...sharedIssues, ...branch.issues]);
    const diagnostics = branchIssues ? [gapPanel, branchIssues] : [gapPanel];
    if (simulation?.branches.includes(branch.branch_code)) {
      if (!runs.has(branch)) {
        runs.set(branch, {branch: structuredClone(branch), processed: 0, placed: 0, invalid: 0, last: null, traces: []});
      }
      selectedView.replaceChildren(...diagnostics, simulationView(runs.get(branch), branches, simulation.id, renderGaps));
      return;
    }
    const map = createYardMap(branch, branches);
    selectedView.replaceChildren(...diagnostics, inboundQueue(branch), ...(map ? [map.element] : []));
    if (map && branch.queue.length && branch.inbound_available !== false) {
      const hint = simulation ? "Resolve the input errors above before running this branch." :
        "Generate a fresh preview in the setup launcher to run the simulation.";
      selectedView.append(el("p", hint, "note"));
    }
  }
  if (branches.length > 1) {
    const label = el("label", "Preview branch ", "preview-branch");
    const select = el("select");
    for (const [index, branch] of branches.entries()) {
      const name = branch.branch_name ? " · " + branch.branch_name : "";
      const issues = issueCounts(branch.issues);
      const option = el("option", branch.branch_code + name + (issues ? " · " + issues : ""));
      option.value = index;
      select.append(option);
    }
    select.addEventListener("change", () => showBranch(branches[Number(select.value)]));
    label.append(select);
    overview.append(label);
  }
  showBranch(branches[0]);
  overview.append(selectedView);
  return overview;
}

function showPreview(result, simulation) {
  if (result?.version !== 1 || result.kind !== "stacking-preview") {
    throw new Error("The preview response has an unexpected format.");
  }

  const heading = result.ready ? "Scenario ready" : "Review the issues below";
  const content = [
    el("h3", heading, result.ready ? "ready" : "not-ready"),
  ];
  if (result.branches.length) {
    content.push(previewOverview(result.branches, simulation, result.issues));
  } else {
    const inputIssues = issueOverview(result.issues);
    if (inputIssues) content.push(inputIssues);
  }
  content.push(table(["Dataset", "File", "Source rows"], Object.entries(result.datasets).map(([name, data]) => [
      descriptions[name]?.[0] ?? name, data.file, data.rows
    ])));

  for (const branch of result.branches) {
    const section = el("div", undefined, "branch-result");
    section.append(el("h3", branch.branch_code + (branch.branch_name ? " | " + branch.branch_name : "")));
    const metrics = el("div", undefined, "metrics");
    for (const [key, value] of Object.entries(branch.summary)) {
      if (key === "anomalous_stacks" || key === "stacks_with_dummy_containers") continue;
      const metric = el("div", undefined, "metric");
      metric.append(el("strong", value), el("span", key.replaceAll("_", " ")));
      metrics.append(metric);
    }
    section.append(metrics);
    if (Object.keys(branch.counts).length) {
      const detail = el("details");
      detail.append(el("summary", "Loaded records after branch filtering"),
        table(["Dataset", "Loaded records"], Object.entries(branch.counts)));
      section.append(detail);
    }
    content.push(section);
  }
  $("results").replaceChildren(...content);
  $("save-yard").hidden = typeof globalThis.saveStackingYard !== "function" ||
    !result.branches.some(branch => branch.yard_map?.blocks.length);
  previewStatus("Preview generated.");
}

for (const source of ["folder", "upload"]) {
  $("source-" + source).addEventListener("change", () => {
    showDatasets();
    changed();
    message();
  });
}
const csvFolderPicker = $("load-csv-folder");
$("choose-csv-folder").addEventListener("click", () => csvFolderPicker.click());
csvFolderPicker.addEventListener("change", () => action(async () => {
  const selectedFiles = Array.from(csvFolderPicker.files);
  csvFolderPicker.value = "";
  if (!selectedFiles.length) return;
  const matches = matchCsvFolder(selectedFiles);
  const selected = await Promise.all(Array.from(matches, async ([name, file]) =>
    [name, {name: file.name, content: await readText(file)}]));
  files = Object.fromEntries(selected);
  $("source-upload").checked = true;
  showDatasets();
  changed();
  message("Replaced all " + selected.length + " input files with CSVs from the selected folder.");
}));
for (const [kind, key] of Object.entries(tomlEditors)) {
  const setDefault = $("default-" + kind);
  if (standalone) {
    browserDefaults[key] = globalThis.readStackingTomlDefault(key);
    setDefault.hidden = false;
    setDefault.addEventListener("click", () => action(async () => {
      const text = editedToml(tomlDocuments[kind], true);
      browserDefaults[key] = await globalThis.setStackingTomlDefault({key, text});
      showToml(kind, browserDefaults[key]);
      const name = $(kind + "-toml-source").dataset.projectFile;
      message("Set " + name + " as the default in this browser.");
    }));
  }
  showToml(kind, browserDefaults[key] ?? projectTomls[key] ?? "");
  const picker = $("load-" + kind);
  const save = $("save-" + kind);
  save.hidden = typeof globalThis.saveStackingToml !== "function";
  if (standalone) save.textContent = "Save as TOML";
  save.addEventListener("click", () => action(async () => {
    const document = tomlDocuments[kind];
    const saved = await globalThis.saveStackingToml({
      key, text: editedToml(document, true), expected: document.projectText
    });
    projectTomls[key] = saved;
    if (standalone) {
      const name = $(kind + "-toml-source").dataset.projectFile;
      message("Downloaded " + name + ".");
      return;
    }
    projectTomlsLive = true;
    showToml(kind, saved);
    tomlDocuments[kind].saved = true;
    if (kind === "input") showDatasets();
    message();
  }));
  $("choose-" + kind).addEventListener("click", () => picker.click());
  onFile(picker, async file => {
    showToml(kind, await readText(file), "Loaded " + file.name);
    if (kind === "input") showDatasets();
    changed();
    message("Loaded " + file.name + ".");
  });
}
if (standalone) setupBundledBranches();
showDatasets();
const tomlActions = $("project-toml-actions");
tomlActions.hidden = !canReadProjectTomls;
$("project-toml-cache-note").hidden = canReadProjectTomls || standalone;
$("reload-project-tomls").addEventListener("click", () => action(async () => {
  await refreshProjectTomls(true);
  changed();
  message("Reloaded the project TOMLs from disk.");
}));
if (canReadProjectTomls) action(() => refreshProjectTomls());
const canGenerate = typeof globalThis.generateStackingPreview === "function";
$("generate-preview").hidden = !canGenerate;
$("preview-launch-note").hidden = canGenerate;
$("generate-preview").addEventListener("click", () => action(async () => {
  if (canReadProjectTomls && await refreshProjectTomls()) changed();
  previewStatus("Generating preview...");
  const {preview, simulation} = await globalThis.generateStackingPreview(buildDraft());
  showPreview(preview, simulation);
}, previewStatus));
$("save-yard").addEventListener("click", () => action(async () => {
  const path = await globalThis.saveStackingYard();
  if (path) previewStatus((standalone ? "Exported " : "Saved ") + path);
}, previewStatus));

