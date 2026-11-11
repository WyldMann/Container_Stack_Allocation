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
      stopped = new Error("The browser simulation stopped. Reopen index.html to try again.");
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
  globalThis.generateStackingPreview = draft => request({op: "preview", draft});
  globalThis.stepStackingSimulation = step => request({...step, op: "step"});
  globalThis.saveStackingToml = async document => {
    const {name, text} = await request({...document, op: "export_toml"});
    download(name, text, "text/plain;charset=utf-8");
    return text;
  };
  globalThis.saveStackingYard = async () =>
    download("containers.csv", await request({op: "yard_csv"}), "text/csv;charset=utf-8");
})();
