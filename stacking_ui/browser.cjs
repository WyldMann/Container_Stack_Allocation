"use strict";

const {spawn} = require("node:child_process");
const {createInterface} = require("node:readline");

function startWorker(python) {
  const worker = spawn(python, ["-X", "utf8", "-B", "-m", "stacking_ui", "--simulation-stdin"], {
    windowsHide: true
  });
  let pending;
  let stopped;
  let errors = "";
  function stop(error) {
    stopped ??= error;
    pending?.reject(stopped);
    pending = undefined;
  }
  worker.stderr.setEncoding("utf8");
  worker.stderr.on("data", chunk => errors = (errors + chunk).slice(-2000));
  worker.on("error", stop);
  worker.stdin.on("error", stop);
  worker.on("close", () => stop(new Error(
    "The local stacking worker stopped. Reopen the setup window to start again." + (errors ? "\n" + errors.trim() : "")
  )));
  createInterface({input: worker.stdout}).on("line", line => {
    if (!pending) return;
    try {
      const response = JSON.parse(line);
      if (response.error) pending.reject(new Error(response.error));
      else pending.resolve(response.result);
      pending = undefined;
    } catch (error) {
      stop(new Error("Python returned an unreadable simulation response.", {cause: error}));
    }
  });
  return {
    request(input) {
      if (stopped) return Promise.reject(stopped);
      if (pending) return Promise.reject(new Error("A stacking request is already running."));
      return new Promise((resolve, reject) => {
        pending = {resolve, reject};
        worker.stdin.write(JSON.stringify(input) + "\n", "utf8");
      });
    },
    close() { worker.stdin.end(); }
  };
}

async function openSetup(python, pageUrl) {
  let chromium;
  try {
    ({chromium} = require("playwright-core"));
  } catch (error) {
    if (error.code !== "MODULE_NOT_FOUND") throw error;
    throw new Error("The setup launcher requires the local playwright-core package.");
  }
  const browser = await chromium.launch({channel: "msedge", headless: false, chromiumSandbox: true});
  let worker;
  try {
    const context = await browser.newContext({offline: true});
    const page = await context.newPage();
    const closed = new Promise(resolve => page.once("close", resolve));
    function request(frame, input) {
      if (frame !== page.mainFrame() || frame.url() !== pageUrl) {
        throw new Error("Open the offline setup page to use the stacking worker.");
      }
      worker ??= startWorker(python);
      return worker.request(input);
    }
    await page.exposeBinding("generateStackingPreview", ({frame}, draft) => request(frame, {op: "preview", draft}));
    await page.exposeBinding("stepStackingSimulation", ({frame}, step) => request(frame, {...step, op: "step"}));
    await page.goto(pageUrl);
    await closed;
  } finally {
    worker?.close();
    await browser.close();
  }
}

module.exports = {startWorker};

if (require.main === module) {
  openSetup(process.argv[2], process.argv[3]).catch(error => {
    process.stderr.write(error.message + "\n");
    process.exitCode = 1;
  });
}
