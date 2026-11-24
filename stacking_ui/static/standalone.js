"use strict";

(() => {
  // Blob workers can start from a local HTML page without fetching sibling files.
  function workerMain() {
    const indexURL = "https://stacking.invalid/";
    const nativeFetch = self.fetch.bind(self);
    const nativeImportScripts = self.importScripts.bind(self);
    let ready;

    async function loadRuntime(assets) {
      const urls = {};
      function bytes(name) {
        const encoded = assets[name][1];
        return Uint8Array.fromBase64?.(encoded) ?? Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
      }
      for (const [name, [type]] of Object.entries(assets)) {
        if (name !== "project.zip") urls[indexURL + name] = URL.createObjectURL(new Blob([bytes(name)], {type}));
      }
      function assetURL(url) {
        if (!urls[url]) throw new Error("Missing bundled Python runtime asset: " + url);
        return urls[url];
      }
      self.fetch = (url, options) => nativeFetch(assetURL(url), options);
      self.importScripts = (...paths) => nativeImportScripts(...paths.map(assetURL));
      try {
        self.importScripts(indexURL + "pyodide.js");
        const python = await self.loadPyodide({indexURL, fullStdLib: false});
        python.unpackArchive(bytes("project.zip"), "zip", {extractDir: "/stacking"});
        return python.runPython([
          "import sys",
          "sys.path.insert(0, '/stacking')",
          "from stacking_ui.session import SimulationSession",
          "SimulationSession().handle_json",
        ].join("\n"));
      } finally {
        for (const url of Object.values(urls)) URL.revokeObjectURL(url);
      }
    }

    self.onmessage = async ({data: {id, input, assets}}) => {
      try {
        ready ??= loadRuntime(assets);
        const handle = await ready;
        const response = JSON.parse(handle(JSON.stringify(input)));
        self.postMessage({id, ...response});
      } catch (error) {
        self.postMessage({id, error: error.message});
      }
    };
  }

  const pending = new Map();
  let worker;
  let nextId = 0;
  let stopped;

  function startWorker() {
    const url = URL.createObjectURL(new Blob(["(", workerMain.toString(), ")();"], {type: "text/javascript"}));
    try {
      worker = new Worker(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    worker.onmessage = ({data: {id, result, error}}) => {
      const request = pending.get(id);
      pending.delete(id);
      if (error !== undefined) request.reject(new Error(error));
      else request.resolve(result);
    };
    worker.onerror = () => {
      stopped = new Error("The browser simulation stopped. Reopen container-stacking-simulator.html to try again.");
      for (const {reject} of pending.values()) reject(stopped);
      pending.clear();
    };
  }

  async function request(input) {
    if (stopped) throw stopped;
    if (!worker) startWorker();
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      worker.postMessage({id, input, assets: STACKING_RUNTIME});
      STACKING_RUNTIME = null;
      pending.set(id, {resolve, reject});
    });
  }

  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], {type}));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    return name;
  }

  globalThis.stackingStandalone = true;
  const accessStorageKey = "container-stacking:block-access:" + STACKING_BUNDLE_ID;
  let restoredAccess;
  function restoreAccess() {
    return restoredAccess ??= (async () => {
      let text;
      try { text = localStorage.getItem(accessStorageKey); } catch { return; }
      if (text) await request({op: "restore_block_access", text});
    })();
  }
  globalThis.generateStackingPreview = async draft => {
    await restoreAccess();
    return request({op: "preview", draft});
  };
  globalThis.updateStackingBlockAccess = access => request({...access, op: "update_block_access"});
  globalThis.saveStackingBlockAccess = async access => {
    const saved = await request({...access, op: "save_block_access"});
    try { localStorage.setItem(accessStorageKey, saved.text); }
    catch { throw new Error("Could not remember block access in this browser. Allow local storage and save again."); }
    return saved;
  };
  globalThis.downloadStackingBundledCsvs = async () => {
    await restoreAccess();
    const archive = await request({op: "bundled_csvs"});
    const bytes = Uint8Array.fromBase64?.(archive.base64) ??
      Uint8Array.from(atob(archive.base64), char => char.charCodeAt(0));
    return download(archive.name, bytes, "application/zip");
  };
  globalThis.stepStackingSimulation = step => request({...step, op: "step"});
  globalThis.suggestStackingAssignment = input => request({...input, op: "suggest"});
  globalThis.getStackingManualEquipment = input => request({...input, op: "manual_equipment"});
  globalThis.reorderStackingQueue = edit => request({...edit, op: "reorder_queue"});
  globalThis.addStackingQueueRow = edit => request({...edit, op: "add_queue_row"});
  globalThis.deleteStackingQueueRow = edit => request({...edit, op: "delete_queue_row"});
  globalThis.repairStackingTierGaps = repair => request({...repair, op: "repair_tier_gaps"});
  globalThis.addStackingDummy = placement => request({...placement, op: "add_stack_dummy"});
  globalThis.removeStackingTop = removal => request({...removal, op: "remove_stack_top"});
  globalThis.compareStackingYard = comparison => request({...comparison, op: "compare_yard"});
  const defaultStorageKey = key => "container-stacking:default:" + STACKING_BUNDLE_ID + ":" + key;
  globalThis.readStackingTomlDefault = key => {
    try {
      return localStorage.getItem(defaultStorageKey(key));
    } catch {
      return null;
    }
  };
  globalThis.setStackingTomlDefault = async document => {
    const {text} = await request({...document, op: "export_toml"});
    try {
      localStorage.setItem(defaultStorageKey(document.key), text);
    } catch {
      throw new Error("Could not save settings in this browser.");
    }
    return text;
  };
  globalThis.saveStackingToml = async document => {
    const {name, text} = await request({...document, op: "export_toml"});
    download(name, text, "text/plain;charset=utf-8");
    return text;
  };
  globalThis.saveStackingYard = async () =>
    download("containers.csv", await request({op: "yard_csv"}), "text/csv;charset=utf-8");
})();
