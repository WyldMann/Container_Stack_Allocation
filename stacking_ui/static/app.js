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
const loaderModes = ["off", "heuristic", "feasibility"];
const loaderModeKeys = ["loader_access_mode", "preserve_future_loader_access_mode"];
const loaderScoringOptions = [
  {key: "loader_inaccessible_destination_multiplier", mode: "current", defaultValue: "0.25",
    label: "Unreachable destination multiplier",
    description: "Multiply the current access score by this value (0–1) when the loader cannot reach the destination."},
  {key: "loader_occupied_access_loss_weight", mode: "current", defaultValue: "1.0",
    label: "Occupied access loss weight",
    description: "Higher values penalize cutting off occupied stacks more. Zero removes this score penalty."},
  {key: "loader_future_access_loss_weight", mode: "future", defaultValue: "1.0",
    label: "Future access loss weight",
    description: "Higher values penalize cutting off future receiving options more. Zero removes this score penalty."}
];
const placementGroups = [
  {title: "Stacking safety", options: {
    "feasibility.stacking_safety": ["Enforce pyramid stacking",
      "Reject placements that would exceed the safe stack height for the location."]
  }},
  {title: "Loader access", description:
    "Off skips the check. Heuristic uses access to rank placements. Feasibility rejects placements that block access. These checks apply to loader-served blocks.",
  options: {
    "feasibility.loader_access_mode": ["Current loader access",
      "Protect access to the placement location and to containers already in the yard."],
    "feasibility.preserve_future_loader_access_mode": ["Future loader access",
      "Keep locations with room for more containers reachable."],
    "feasibility.ignore_full_stacks_for_loader_access": ["Ignore full stacks",
      "Exclude fully occupied stacks from the current access check."],
    ...Object.fromEntries(loaderScoringOptions.map(({key, label, description}) =>
      ["heuristic." + key, [label, description]]))
  }},
  {title: "Weight compatibility", toggle: "heuristic.enable_delta_container_mass", options: {
    "heuristic.enable_delta_container_mass": ["Score weight compatibility",
      "Use the weight difference between the incoming container and its support to rank placements."],
    "heuristic.w_delta_container_mass": ["Maximum weight score",
      "Score for placing a container on one of the same weight."],
    "heuristic.hl_delta_container_mass": ["Weight difference for half score",
      "The score halves when the supporting container is heavier by this amount. Uses the CSV weight units."],
    "heuristic.no_delta_container_mass_value": ["Unknown weight score",
      "Use this score when either container's weight is unavailable."]
  }},
  {title: "Equipment distance", toggle: "heuristic.enable_equipment_distance", options: {
    "heuristic.enable_equipment_distance": ["Score equipment distance",
      "Use the distance from the serving equipment to rank placements."],
    "heuristic.w_equipment_distance": ["Maximum distance score",
      "Score when the equipment is already at the placement location."],
    "heuristic.hl_equipment_distance": ["Distance for half score",
      "The distance score halves at this distance, measured in yard grid units."]
  }},
  {title: "Container size clustering", toggle: "heuristic.enable_size_cluster", options: {
    "heuristic.enable_size_cluster": ["Score nearby container sizes",
      "Favor placements near containers of the same size."],
    "heuristic.size_cluster_radius": ["Search radius",
      "Check nearby stacks within this many yard grid units. Zero turns off the clustering effect."],
    "heuristic.hl_size_cluster_distance": ["Distance for half influence",
      "A neighbor's influence halves at this distance, measured in yard grid units."],
    "heuristic.size_cluster_prior": ["Clustering smoothing",
      "Higher values reduce the influence of nearby container sizes."],
    "heuristic.size_cluster_bias": ["Clustering strength",
      "Controls the reward for matching sizes and penalty for different sizes. Zero turns off the clustering effect."]
  }},
  {title: "Scoring fallback", options: {
    "heuristic.min_value": ["Fallback score",
      "Use this score when the incoming container is heavier than its support or serving equipment is outside the block."]
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
    const {loaderAccess, placementRows} = tomlDocuments.config;
    updateLoaderAccess(loaderAccess, placementRows);
    updatePlacementDependencies(placementRows);
    Object.keys(tomlEditors).forEach(updateTomlSave);
  }
}

async function readText(file) {
  return new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
}

function onFile(input, handler) {
  input.addEventListener("change", () => action(async () => {
    const file = input.files[0];
    if (!file) return;
    input.value = "";
    await handler(file);
  }));
}

function tomlValueEnd(source, start) {
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
    } else if (character === "\n" && !depth) {
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

function showPlacementGroups(editor, rows) {
  const groups = el("div", undefined, "placement-groups");
  for (const {title, description, options} of placementGroups) {
    const entries = Object.keys(options).flatMap(path => rows.get(path) ?? []);
    if (!entries.length) continue;
    const group = el("fieldset", undefined, "placement-group");
    group.append(el("legend", title));
    if (description) group.append(el("p", description, "placement-help"));
    const list = el("div", undefined, "placement-options");
    list.append(...entries);
    group.append(list);
    groups.append(group);
  }
  if (editor.childElementCount) {
    const other = el("fieldset", undefined, "placement-group");
    other.append(el("legend", "Other TOML settings"), ...editor.children);
    groups.append(other);
  }
  editor.replaceChildren(groups);
}

function setPlacementInactive(option, inactive) {
  option.classList.toggle("is-inactive", inactive);
  option.querySelector("input, textarea").disabled = busy || inactive;
}

function updatePlacementDependencies(rows) {
  const isOff = path => rows.get(path)?.[0].querySelector('input[type="checkbox"]')?.checked === false;
  for (const {toggle, options} of placementGroups) {
    if (!toggle) continue;
    const inactive = isOff(toggle);
    for (const path of Object.keys(options)) {
      if (path === toggle) continue;
      for (const option of rows.get(path) ?? []) setPlacementInactive(option, inactive);
    }
  }
  const fallbackInactive = isOff("heuristic.enable_delta_container_mass") &&
    isOff("heuristic.enable_equipment_distance");
  for (const option of rows.get("heuristic.min_value") ?? []) setPlacementInactive(option, fallbackInactive);
}

function loaderAccessSwitch(access, rows, key, prefix, value) {
  const future = key.startsWith("preserve_future_");
  const legacy = !key.endsWith("_mode");
  const modeKey = legacy ? key + "_mode" : key;
  const fallback = future ? null : "feasibility";
  const original = value === null ? "" : prefix + value;
  const initial = value === null || (legacy && value === "true") ? fallback :
    legacy ? "off" : value.match(/^["']{1,3}(off|heuristic|feasibility)["']{1,3}$/)?.[1];
  if (initial === undefined || (legacy && value !== "true" && value !== "false")) return null;

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
  control.select = mode => {
    control.mode = mode;
    input.value = mode === initial ? original :
      modePrefix + JSON.stringify(mode) + (value === null ? "\n" : "");
  };
  for (const mode of loaderModes) {
    const choice = el("input");
    choice.type = "radio";
    choice.name = modeKey;
    choice.value = mode;
    const option = el("label");
    option.append(choice, el("span", mode[0].toUpperCase() + mode.slice(1)));
    group.append(option);
    control.choices.push(choice);
    choice.addEventListener("change", () => {
      control.select(mode);
      updateLoaderAccess(access, rows, !future);
      updateTomlSave("config");
      changed();
    });
  }
  row.append(label, group);
  access[modeKey] = control;
  return control;
}

function updateLoaderAccess(access, rows, currentChanged = false) {
  const current = access.loader_access_mode;
  const future = access.preserve_future_loader_access_mode;
  const mode = current?.mode ?? "feasibility";
  const limit = loaderModes.indexOf(mode);
  if (currentChanged && future && loaderModes.indexOf(future.mode) > limit) future.select(mode);
  const futureInactive = mode === "off" && (future?.mode ?? mode) === "off";
  for (const choice of current?.choices ?? []) {
    choice.checked = choice.value === mode;
    choice.disabled = busy;
  }
  for (const [index, choice] of (future?.choices ?? []).entries()) {
    choice.checked = choice.value === (future.mode ?? mode);
    choice.disabled = busy || futureInactive || index > limit;
  }
  future?.option.classList.toggle("is-inactive", futureInactive);
  if (access.ignoreFull) setPlacementInactive(access.ignoreFull, mode === "off");
  const effectiveModes = {current: mode, future: future?.mode ?? mode};
  for (const {key, mode: scoringMode} of loaderScoringOptions) {
    for (const option of rows.get("heuristic." + key) ?? []) {
      setPlacementInactive(option, effectiveModes[scoringMode] !== "heuristic");
    }
  }
  if (access.note) {
    access.note.textContent = mode === "heuristic" && (future.mode ?? mode) === "heuristic" ?
      "Current loader access ranks first when both modes are Heuristic." :
      "Future loader access can use the current mode or a weaker mode.";
  }
}

function addMissingLoaderWeights(rows, fields, source, offset) {
  const separator = offset && source[offset - 1] !== "\n" ? "\n" : "";
  for (const {key, defaultValue} of loaderScoringOptions) {
    const path = "heuristic." + key;
    if (rows.has(path)) continue;
    const prefix = separator + (offset ? key : path) + " = ";
    const input = el("input");
    input.type = "text";
    input.inputMode = "decimal";
    input.spellcheck = false;
    input.value = defaultValue;
    input.addEventListener("input", () => {
      updateTomlSave("config");
      changed();
    });
    const row = el("label", undefined, "toml-setting");
    row.append(el("span"), input);
    addPlacementOption(rows, path, row, input);
    fields.push({start: offset, end: offset, input,
      format: value => value === defaultValue ? "" : prefix + value + "\n"});
  }
}

function showToml(kind, text, loadedFrom) {
  const source = text.replace(/\r\n?/g, "\n");
  const fields = [];
  const csvPaths = new Map();
  const loaderAccess = {};
  const placementRows = new Map();
  const editor = $(kind + "-toml");
  editor.replaceChildren();
  tomlDocuments[kind] = {
    source, fields, csvPaths, loaderAccess, placementRows,
    usesProject: loadedFrom == null, projectText: projectTomls[tomlEditors[kind]]
  };

  let section = "";
  let statementStart = 0;
  let feasibilityStart = 0;
  let heuristicStart = 0;
  let inlineFeasibility = false;
  let inlineHeuristic = false;
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
      loaderModeKeys.find(mode => mode === key || mode === key + "_mode");
    const optionPath = [root, modeKey || key].join(".");
    const knownOption = kind === "config" && parts.length === 2 && Object.hasOwn(placementOptions, optionPath);
    const knownTable = kind === "config" && table && parts.length === 1 &&
      (root === "feasibility" || root === "heuristic");
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
    if (visible && !knownOption && !knownTable) {
      for (const comment of comments) editor.append(el("p", comment, "toml-comment"));
    }
    comments.length = 0;

    if (match) {
      const start = offset + match[1].length;
      const boundary = tomlValueEnd(source, start);
      lineEnd = source.indexOf("\n", boundary);
      if (lineEnd === -1) lineEnd = source.length;
      if (visible || isCsvPath) {
        const value = source.slice(start, boundary).trimEnd();
        if (modeKey) {
          seenModes.add(modeKey);
          const control = loaderAccessSwitch(loaderAccess, placementRows, key, match[1], value);
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
              loaderAccess.ignoreFull = option;
            }
          } else {
            editor.append(label);
          }
        }
        fields.push({start, end: start + value.length, input});
      }
    } else if (visible && !knownTable) {
      editor.append(el(table ? "h4" : "p", trimmed, table ? "toml-section" : "toml-comment"));
    }
    offset = lineEnd + 1;
    if (omitted) fields.push({start: statementStart, end: Math.min(offset, source.length)});
    statementStart = Math.min(offset, source.length);
  }
  if (omittedTomlPath(kind, tomlParts(section))) {
    fields.push({start: statementStart, end: source.length});
  } else {
    for (const comment of comments) editor.append(el("p", comment, "toml-comment"));
  }
  if (kind === "config") {
    if (!inlineFeasibility) {
      const separator = feasibilityStart && source[feasibilityStart - 1] !== "\n" ? "\n" : "";
      for (const key of loaderModeKeys.filter(key => !seenModes.has(key))) {
        const prefix = separator + (feasibilityStart ? key : "feasibility." + key) + " = ";
        const control = loaderAccessSwitch(loaderAccess, placementRows, key, prefix, null);
        control.option = addPlacementOption(placementRows, "feasibility." + key, control.row, control.group);
        fields.push({start: feasibilityStart, end: feasibilityStart, input: control.input});
      }
    }
    if (!inlineHeuristic) addMissingLoaderWeights(placementRows, fields, source, heuristicStart);
    fields.sort((a, b) => a.start - b.start || a.end - b.end);
    const future = loaderAccess.preserve_future_loader_access_mode;
    if (future) {
      loaderAccess.note = el("p", undefined, "placement-help");
      loaderAccess.note.id = "loader-access-note";
      future.group.setAttribute("aria-describedby",
        future.group.getAttribute("aria-describedby") + " " + loaderAccess.note.id);
      future.option.append(loaderAccess.note);
    }
    showPlacementGroups(editor, placementRows);
    updateLoaderAccess(loaderAccess, placementRows);
    updatePlacementDependencies(placementRows);
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

function updateTomlSave(kind) {
  const document = tomlDocuments[kind];
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
}

function buildDraft() {
  const useFolder = $("source-folder").checked;
  const draft = {
    version: 1,
    file_source: standalone ? "bundle" : useFolder ? "folder" : "upload",
    files: useFolder ? Object.fromEntries(Object.entries(files).filter(([, upload]) => upload.empty === true)) : files
  };
  for (const [kind, key] of Object.entries(tomlEditors)) {
    draft[key] = editedToml(tomlDocuments[kind]);
  }
  return draft;
}

function showDatasets() {
  const grid = $("datasets");
  const useFolder = $("source-folder").checked;
  $("source-description").textContent = standalone
    ? (useFolder ? "Use the CSVs included in this package." : "Choose replacement UTF-8 CSVs. Datasets without a replacement use their bundled CSV.")
    : (useFolder
      ? "Use the prefilled CSV paths or edit them below. Relative paths start in config/container_stacking. Keep the quotes around each path."
      : "Choose a UTF-8 CSV for each dataset, or mark it explicitly empty.");
  grid.replaceChildren();
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
    for (const value of row) tr.append(el("td", String(value ?? "")));
    body.append(tr);
  }
  grid.append(head, body);
  wrap.append(grid);
  return wrap;
}

function issues(items) {
  if (!items.length) return el("p", "No issues detected.", "ready");
  return table(["Severity", "Dataset / field", "Source", "Issue"], items.map(item => [
    item.severity,
    item.dataset + (item.field ? " / " + item.field : ""),
    item.sources.map(source => source.file + ":" + source.line).join(", ") || "Dataset-level check",
    item.message
  ]));
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
    el("span", (row.size ? row.size + " ft · " : "") + row.status, "inbound-meta"));
  if (row.reason) card.append(el("span", row.reason, "inbound-reason"));
}

function inboundQueue(branch) {
  const panel = el("div", undefined, "inbound-queue");
  panel.append(el("h3", "Inbound queue"));
  if (branch.inbound_available === false) {
    panel.append(el("p", "Inbound queue unavailable. Review the inbound CSV issue below."));
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

function previewOverview(branches, simulation) {
  const overview = el("div");
  const selectedView = el("div");
  const runs = new Map();
  function showBranch(branch) {
    if (simulation?.branches.includes(branch.branch_code)) {
      if (!runs.has(branch)) {
        runs.set(branch, {branch: structuredClone(branch), processed: 0, placed: 0, invalid: 0, last: null, traces: []});
      }
      selectedView.replaceChildren(simulationView(runs.get(branch), branches, simulation.id));
      return;
    }
    const map = createYardMap(branch, branches);
    selectedView.replaceChildren(inboundQueue(branch), ...(map ? [map.element] : []));
    if (map && branch.queue.length && branch.inbound_available !== false) {
      const hint = simulation ? "Resolve the yard input errors below before running this branch." :
        "Generate a fresh preview in the setup launcher to run the simulation.";
      selectedView.append(el("p", hint, "note"));
    }
  }
  if (branches.length > 1) {
    const label = el("label", "Preview branch ", "preview-branch");
    const select = el("select");
    for (const [index, branch] of branches.entries()) {
      const name = branch.branch_name ? " · " + branch.branch_name : "";
      const option = el("option", branch.branch_code + name);
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
  if (result.branches.length) content.push(previewOverview(result.branches, simulation));
  content.push(table(["Dataset", "File", "Source rows"], Object.entries(result.datasets).map(([name, data]) => [
      descriptions[name]?.[0] ?? name, data.file, data.rows
    ])));
  if (result.issues.length) content.push(issues(result.issues));

  for (const branch of result.branches) {
    const section = el("div", undefined, "branch-result");
    section.append(el("h3", branch.branch_code + (branch.branch_name ? " | " + branch.branch_name : "")));
    const metrics = el("div", undefined, "metrics");
    for (const [key, value] of Object.entries(branch.summary)) {
      const metric = el("div", undefined, "metric");
      metric.append(el("strong", value), el("span", key.replaceAll("_", " ")));
      metrics.append(metric);
    }
    section.append(metrics, issues(branch.issues));
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
  });
}
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

