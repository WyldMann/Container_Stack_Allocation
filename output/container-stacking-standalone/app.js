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
const standalone = globalThis.stackingStandalone === true;
const canReadProjectTomls = typeof globalThis.readStackingTomls === "function";
let projectTomls = typeof TOML_DEFAULTS === "undefined" ? {} : TOML_DEFAULTS;
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
    updateLoaderAccess(tomlDocuments.config.loaderAccess);
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

function loaderAccessSwitch(access, key, prefix, value) {
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
      updateLoaderAccess(access, !future);
      updateTomlSave("config");
      changed();
    });
  }
  row.append(label, group);
  access[modeKey] = control;
  return control;
}

function updateLoaderAccess(access, currentChanged = false) {
  const current = access.loader_access_mode;
  const future = access.preserve_future_loader_access_mode;
  const mode = current?.mode ?? "feasibility";
  const limit = loaderModes.indexOf(mode);
  if (currentChanged && future && loaderModes.indexOf(future.mode) > limit) future.select(mode);
  for (const choice of current?.choices ?? []) {
    choice.checked = choice.value === mode;
    choice.disabled = busy;
  }
  for (const [index, choice] of (future?.choices ?? []).entries()) {
    choice.checked = choice.value === (future.mode ?? mode);
    choice.disabled = busy || index > limit;
  }
  if (access.ignoreFull) access.ignoreFull.disabled = busy || mode === "off";
  if (access.note) {
    access.note.textContent = mode === "heuristic" && (future.mode ?? mode) === "heuristic" ?
      "Current loader access ranks first when both modes are Heuristic." :
      "Future loader access can use the current mode or a weaker mode.";
  }
}

function showToml(kind, text, loadedFrom) {
  const source = text.replace(/\r\n?/g, "\n");
  const fields = [];
  const csvPaths = new Map();
  const loaderAccess = {};
  const editor = $(kind + "-toml");
  editor.replaceChildren();
  tomlDocuments[kind] = {
    source, fields, csvPaths, loaderAccess, usesProject: loadedFrom == null, projectText: projectTomls[tomlEditors[kind]]
  };

  let section = "";
  let statementStart = 0;
  let feasibilityStart = 0;
  let feasibilityHeading;
  let inlineFeasibility = false;
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
    if (kind === "config" && root === "feasibility" && parts.length === 1) {
      if (table) feasibilityStart = Math.min(lineEnd + 1, source.length);
      else if (match) inlineFeasibility = true;
    }
    const omitted = omittedTomlPath(kind, parts);
    const inFileCards = kind === "input" && root === "csv" && key === "files";
    const isCsvPath = inFileCards && match && parts.length === 3 && Object.hasOwn(descriptions, dataset);
    const visible = !omitted && !inFileCards &&
      !(kind === "input" && table && root === "csv" && parts.length === 1);
    if (visible) {
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
        if (kind === "config" && root === "feasibility" && parts.length === 2) {
          const modeKey = key.endsWith("_mode") ? key : key + "_mode";
          if (loaderModeKeys.includes(modeKey)) {
            seenModes.add(modeKey);
            const control = loaderAccessSwitch(loaderAccess, key, match[1], value);
            if (control) {
              const comment = source.slice(boundary, lineEnd);
              if (comment) editor.append(el("p", comment, "toml-comment"));
              editor.append(control.row);
              fields.push({start: offset, end: start + value.length, input: control.input});
              offset = statementStart = lineEnd + 1;
              continue;
            }
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
        if (kind === "config" && root === "feasibility" && key === "ignore_full_stacks_for_loader_access" && boolean) {
          loaderAccess.ignoreFull = input;
        }
        if (!boolean) input.value = value;
        input.addEventListener("input", () => {
          updateTomlSave(kind);
          changed();
        });
        if (isCsvPath) {
          csvPaths.set(dataset, input);
        } else {
          const comment = source.slice(boundary, lineEnd);
          if (comment) editor.append(el("p", comment, "toml-comment"));
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
          editor.append(label);
        }
        fields.push({start, end: start + value.length, input});
      }
    } else if (visible) {
      const heading = el(table ? "h4" : "p", trimmed, table ? "toml-section" : "toml-comment");
      editor.append(heading);
      if (kind === "config" && table && root === "feasibility" && parts.length === 1) {
        feasibilityHeading = heading;
      }
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
        const control = loaderAccessSwitch(loaderAccess, key, prefix, null);
        if (key === "loader_access_mode" && loaderAccess.preserve_future_loader_access_mode) {
          loaderAccess.preserve_future_loader_access_mode.row.before(control.row);
        } else if (key === "preserve_future_loader_access_mode" && loaderAccess.loader_access_mode) {
          loaderAccess.loader_access_mode.row.after(control.row);
        } else if (feasibilityHeading) {
          feasibilityHeading.after(control.row);
        } else {
          editor.prepend(control.row);
        }
        fields.push({start: feasibilityStart, end: feasibilityStart, input: control.input});
      }
      fields.sort((a, b) => a.start - b.start || a.end - b.end);
    }
    const future = loaderAccess.preserve_future_loader_access_mode;
    if (future) {
      loaderAccess.note = el("p", undefined, "note loader-access-note");
      loaderAccess.note.id = "loader-access-note";
      future.group.setAttribute("aria-describedby", loaderAccess.note.id);
      future.row.after(loaderAccess.note);
    }
    updateLoaderAccess(loaderAccess);
  }
  const status = $(kind + "-toml-source");
  const origin = standalone ? "Loaded bundled TOML: " : projectTomlsLive ? "Loaded project TOML: " :
    projectTomls[tomlEditors[kind]] != null ? "Cached project TOML: " : "Project TOML unavailable: ";
  tomlDocuments[kind].sourceLabel = loadedFrom ?? (origin + status.dataset.projectFile);
  updateTomlSave(kind);
}

function tomlFieldValue(input) {
  return input.type === "checkbox" ? String(input.checked) : input.value;
}

async function refreshProjectTomls(replace = false) {
  const fresh = await globalThis.readStackingTomls();
  const wasLive = projectTomlsLive;
  projectTomls = fresh;
  projectTomlsLive = true;
  let refreshed = false;
  for (const [kind, key] of Object.entries(tomlEditors)) {
    const {source, fields, usesProject} = tomlDocuments[kind];
    const unedited = usesProject && fields.every(({start, end, input}) =>
      !input || tomlFieldValue(input) === source.slice(start, end));
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
  for (const {start, end, input} of fields) {
    if (!input && preserveHidden) continue;
    result += source.slice(cursor, start) + (input ? tomlFieldValue(input) : "");
    cursor = end;
  }
  return result + source.slice(cursor);
}

function updateTomlSave(kind) {
  const document = tomlDocuments[kind];
  const persisted = projectTomls[tomlEditors[kind]];
  const dirty = typeof persisted === "string" &&
    editedToml(document, true) !== persisted.replace(/\r\n?/g, "\n");
  $("save-" + kind).disabled = busy || !dirty;
  const status = $(kind + "-toml-source");
  const label = dirty ? document.sourceLabel + " · Unsaved changes" :
    document.saved ? (standalone ? "Exported " : "Saved ") + status.dataset.projectFile : document.sourceLabel;
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
  showToml(kind, projectTomls[key] ?? "");
  const picker = $("load-" + kind);
  const save = $("save-" + kind);
  save.hidden = typeof globalThis.saveStackingToml !== "function";
  save.addEventListener("click", () => action(async () => {
    const document = tomlDocuments[kind];
    const saved = await globalThis.saveStackingToml({
      key, text: editedToml(document, true), expected: document.projectText
    });
    projectTomls[key] = saved;
    if (!standalone) projectTomlsLive = true;
    const name = $(kind + "-toml-source").dataset.projectFile;
    showToml(kind, saved, standalone ? "Exported " + name : undefined);
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

