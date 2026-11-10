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
let preview;

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
  preview = undefined;
  $("save-preview").hidden = true;
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

function tomlValueEnd(source, start, inline = false) {
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
    } else if (inline && !depth && (character === "," || character === "}")) {
      return index;
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

function setInlineTomlValue(source, path, value) {
  for (let offset = 1; offset < source.length;) {
    const assignment = tomlAssignment.exec(source.slice(offset));
    if (!assignment) break;
    const key = tomlParts(assignment[2]).join(".");
    const start = offset + assignment[1].length;
    const boundary = tomlValueEnd(source, start, true);
    const previous = source.slice(start, boundary).trimEnd();
    const replacement = path === key ? value :
      path.startsWith(key + ".") && previous.startsWith("{") ?
        setInlineTomlValue(previous, path.slice(key.length + 1), value) : null;
    if (replacement !== null) return source.slice(0, start) + replacement + source.slice(start + previous.length);
    if (source[boundary] !== ",") break;
    offset = boundary + 1;
  }
  const remainder = source.slice(1).trimStart();
  return "{ " + path + " = " + value + (remainder === "}" ? " " : ", ") + remainder;
}

function migrateDraftBranches(text, codes) {
  const source = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const path = "input.filters.branch_code";
  const value = JSON.stringify(codes).replace(/\u007f/g, "\\u007f");
  let section = "";
  let insertion;
  for (let offset = 0; offset < source.length;) {
    let lineEnd = source.indexOf("\n", offset);
    if (lineEnd === -1) lineEnd = source.length;
    const line = source.slice(offset, lineEnd);
    const table = tomlTable.exec(line.trim());
    if (table) {
      section = tomlParts(table[1]).join(".");
      if (section === "input.filters") {
        insertion = {offset: Math.min(lineEnd + 1, source.length), key: "branch_code"};
      }
    }
    const assignment = tomlAssignment.exec(line);
    if (assignment) {
      const key = [section, ...tomlParts(assignment[2])].filter(Boolean).join(".");
      const start = offset + assignment[1].length;
      const boundary = tomlValueEnd(source, start);
      const previous = source.slice(start, boundary).trimEnd();
      const replacement = key === path ? value :
        path.startsWith(key + ".") && previous.startsWith("{") ?
          setInlineTomlValue(previous, path.slice(key.length + 1), value) : null;
      if (replacement !== null) return source.slice(0, start) + replacement + source.slice(start + previous.length);
      if (!insertion && key.startsWith("input.filters.")) {
        insertion = {offset, key: section ? path.slice(section.length + 1) : path};
      }
      lineEnd = source.indexOf("\n", boundary);
      if (lineEnd === -1) lineEnd = source.length;
    }
    offset = lineEnd + 1;
  }
  if (!insertion) return source.trimEnd() + "\n\n[input.filters]\nbranch_code = " + value + "\n";
  const prefix = source.slice(0, insertion.offset);
  return prefix + (prefix.endsWith("\n") ? "" : "\n") + insertion.key + " = " + value + "\n" +
    source.slice(insertion.offset);
}

function omittedTomlPath(kind, [root, key]) {
  return root === "sql" || (kind === "input" && (
    (root === "input" && key === "sources") ||
    (root === "csv" && key === "mapping_file") ||
    root === "output"
  ));
}

function showToml(kind, text, loadedFrom) {
  const source = text.replace(/\r\n?/g, "\n");
  const fields = [];
  const csvPaths = new Map();
  const editor = $(kind + "-toml");
  editor.replaceChildren();
  tomlDocuments[kind] = {source, fields, csvPaths, usesProject: loadedFrom == null};

  let section = "";
  let statementStart = 0;
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
        input.addEventListener("input", changed);
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
  const status = $(kind + "-toml-source");
  const origin = projectTomlsLive ? "Loaded project TOML: " :
    projectTomls[tomlEditors[kind]] != null ? "Cached project TOML: " : "Project TOML unavailable: ";
  status.textContent = loadedFrom ?? (origin + status.dataset.projectFile);
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

function editedToml({source, fields}) {
  // Replace edited values and omit settings that the page manages itself.
  let cursor = 0;
  let result = "";
  for (const {start, end, input} of fields) {
    result += source.slice(cursor, start) + (input ? tomlFieldValue(input) : "");
    cursor = end;
  }
  return result + source.slice(cursor);
}

function buildDraft() {
  const useFolder = $("source-folder").checked;
  const draft = {
    version: 1,
    file_source: useFolder ? "folder" : "upload",
    files: useFolder ? Object.fromEntries(Object.entries(files).filter(([, upload]) => upload.empty === true)) : files
  };
  for (const [kind, key] of Object.entries(tomlEditors)) {
    draft[key] = editedToml(tomlDocuments[kind]);
  }
  return draft;
}

function downloadJson(value, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: "application/json"}));
  const link = el("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadDraft() {
  downloadJson(buildDraft(), "stacking-scenario-draft.json");
  message("Draft downloaded.");
}

function loadDraft(draft) {
  if (draft?.version !== 1 || !draft.files || typeof draft.files !== "object" || Array.isArray(draft.files)) {
    throw new Error("Choose a saved stacking scenario draft.");
  }
  for (const [name, upload] of Object.entries(draft.files)) {
    if (!Object.hasOwn(descriptions, name) || !upload || typeof upload.name !== "string" ||
        (upload.empty !== true && typeof upload.content !== "string")) {
      throw new Error("Invalid CSV entry in the draft.");
    }
  }
  for (const key of Object.values(tomlEditors)) {
    if (draft[key] != null && typeof draft[key] !== "string") {
      throw new Error("Invalid TOML entry in the draft.");
    }
  }
  if (draft.branch_codes != null && (!Array.isArray(draft.branch_codes) ||
      draft.branch_codes.some(code => typeof code !== "string"))) {
    throw new Error("Invalid branch codes in the draft.");
  }
  const source = draft.file_source ?? "upload";
  if (source !== "folder" && source !== "upload") {
    throw new Error("Invalid CSV source in the draft.");
  }
  files = draft.files;
  $("source-folder").checked = source === "folder";
  $("source-upload").checked = source === "upload";
  for (const [kind, key] of Object.entries(tomlEditors)) {
    const legacyBranches = kind === "input" && draft.branch_codes != null;
    const text = draft[key] ?? projectTomls[key] ?? "";
    const loadedFrom = draft[key] != null || legacyBranches ? "Loaded from saved draft" : undefined;
    showToml(kind, legacyBranches ? migrateDraftBranches(text, draft.branch_codes) : text, loadedFrom);
  }
  if (draft.branch_codes != null) $("stacking-inputs").open = true;
  showDatasets();
  changed();
  message("Draft loaded.");
}

function showDatasets() {
  const grid = $("datasets");
  const useFolder = $("source-folder").checked;
  $("source-description").textContent = useFolder
    ? "Use the prefilled CSV paths or edit them below. Relative paths start in config/container_stacking. Keep the quotes around each path."
    : "Choose a UTF-8 CSV for each dataset, or mark it explicitly empty.";
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
    const csvPath = useFolder ? tomlDocuments.input.csvPaths.get(name) : undefined;
    const sourceLabel = useFolder ? (csvPath ? "" : "Use configured CSV path") : "No file selected";
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

function showPreview(result, status = "Preview loaded.", simulation = null) {
  if (result?.version !== 1 || result.kind !== "stacking-preview") {
    throw new Error("Choose a stacking scenario .preview.json file.");
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
  preview = result;
  $("save-preview").hidden = false;
  previewStatus(status);
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
$("project-toml-cache-note").hidden = canReadProjectTomls;
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
  showPreview(preview, "Preview generated.", simulation);
}, previewStatus));
$("save-preview").addEventListener("click", () => {
  if (preview) downloadJson(preview, "stacking-scenario.preview.json");
});
$("save-draft").addEventListener("click", downloadDraft);
$("choose-draft").addEventListener("click", () => $("load-draft").click());
$("choose-preview").addEventListener("click", () => $("load-preview").click());
onFile($("load-draft"), async file => loadDraft(JSON.parse(await readText(file))));
onFile($("load-preview"), async file => showPreview(JSON.parse(await readText(file))));

