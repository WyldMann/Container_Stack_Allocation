"use strict";

function createPlacementGraphs(read, keys) {
  const format = new Intl.NumberFormat("en", {maximumSignificantDigits: 4});
  const label = value => value !== 0 && (Math.abs(value) < 0.001 || Math.abs(value) >= 1e5)
    ? value.toExponential(2) : format.format(value);
  const score = value => label(value) + "×";
  const counts = Array.from({length: 9}, (_, index) => index);
  const modes = ["off", "heuristic", "feasibility"];

  function invalid(key) {
    throw new Error("Enter a valid value for " + key.replaceAll("_", " ") + " to preview the score.");
  }

  function number(key, fallback, minimum = Number.MIN_VALUE, maximum = Number.MAX_VALUE, integer = false, section = "heuristic") {
    const literal = read(section + "." + key);
    if (literal === undefined) return typeof fallback === "function" ? fallback() : fallback;
    const text = literal.trim();
    const decimal = /^[+-]?(?:0|[1-9](?:_?\d)*)(?:\.\d(?:_?\d)*)?(?:e[+-]?\d(?:_?\d)*)?$/i;
    const radix = /^(?:0x[\da-fA-F](?:_?[\da-fA-F])*|0o[0-7](?:_?[0-7])*|0b[01](?:_?[01])*)$/;
    if (!(decimal.test(text) || radix.test(text)) || (integer && /[.e]/i.test(text) && !radix.test(text))) invalid(key);
    const value = Number(text.replaceAll("_", ""));
    if (!Number.isFinite(value) || value < minimum || value > maximum) invalid(key);
    return value;
  }

  function flag(path, fallback) {
    const value = read(path)?.trim();
    if (value === undefined) return fallback;
    if (value === "true" || value === "false") return value === "true";
    return invalid(path.split(".")[1]);
  }

  function mode(key, fallback) {
    const raw = read("feasibility." + key)?.trim();
    if (raw === undefined) return typeof fallback === "function" ? fallback() : fallback;
    const value = raw.match(/^("{1,3}|'{1,3})(off|heuristic|feasibility|combined)\1$/)?.[2];
    if (modes.includes(value) || (key === "stacking_safety_mode" && value === "combined")) return value;
    return invalid(key);
  }

  const sharedAccess = () => mode("equipment_access_mode", () => flag("feasibility.equipment_access", true) ? "feasibility" : "off");
  const occupiedMode = () => mode("preserve_occupied_access_mode", sharedAccess);
  const fallback = () => number("min_value", 0.001);
  const series = (points, style = "", dots = false) => ({points, style, dots});
  const neutral = (start, end, note = "Scoring off · 1× at every value.") =>
    ({lines: [series([[start, 1], [end, 1]])], note});

  function sample(start, end, fn, segments = 60) {
    return Array.from({length: segments + 1}, (_, index) => {
      const x = start + (end - start) * (index / segments);
      return [x, fn(x)];
    });
  }

  function decay(weight, half, end) {
    const at = distance => weight * 2 ** (-distance / half);
    return series([...sample(0, half, at, 20), ...sample(half, end, at).slice(1)]);
  }

  function rangeEnd(half, minimum) {
    return Math.max(minimum, half, Math.min(Number.MAX_VALUE / 4, half * 2));
  }

  function rule(current, positions, factor, fails) {
    const rejected = current === "feasibility" ? positions.filter(fails) : [];
    const points = positions.filter(x => !rejected.includes(x))
      .map(x => [x, current === "heuristic" ? factor(x) : 1]);
    return {lines: [series(points, "", true)], rejected};
  }

  function binary(current, labels, penalty) {
    const multiplier = current === "heuristic" ? penalty() : 1;
    return {start: -0.35, end: 1.35, ticks: [0, 1], labels, step: true,
      ...rule(current, [0, 1], x => x === 1 ? multiplier : 1, x => x === 1),
      note: labels[0] + " 1× · " + labels[1] + " " + (current === "feasibility" ? "rejected" : score(multiplier))};
  }

  function access(current, weight) {
    const factor = count => weight === 0 ? 1 : 1 / (1 + weight * count);
    let note = "Rule off · 1× for all counts.";
    if (current === "heuristic") note = "At zero " + score(factor(0)) + " · At four " + score(factor(4));
    if (current === "feasibility") note = "No access lost 1× · Any loss rejected.";
    return {start: 0, end: 8, ticks: counts, ...rule(current, counts, factor, count => count > 0), note};
  }

  const models = {
    capacity: {axis: "Tiers above the stack limit", calculate() {
      const current = mode("stack_capacity_mode", "feasibility");
      const perTier = current === "heuristic" ? number("overcapacity_tier_multiplier", 0.01, 0, 1) : 1;
      return {start: 0, end: 8, ticks: counts, ...rule(current, counts, n => perTier ** n, n => n > 0),
        note: current === "feasibility" ? "At limit 1× · Extra tiers rejected."
          : current === "off" ? "Rule off · 1× for all tier counts."
          : "One extra tier " + score(perTier) + " · Two extra tiers " + score(perTier ** 2)};
    }},
    pyramid: {title: "Pyramid stacking", axis: "Height above the tallest considered neighbor after placement (tiers)", calculate() {
      const current = mode("stacking_safety_mode", () => flag("feasibility.stacking_safety", true) ? "feasibility" : "off");
      const hard = number("stacking_safety_maxima", 2, 1, Number.MAX_VALUE, true, "feasibility");
      const soft = number("stacking_safety_penalty_start", 0, 0, hard - 1, true, "feasibility");
      const end = Math.max(3, hard + 1, hard * 1.2);
      const ticks = [...new Set([0, soft, hard, end])];
      if (current === "off") return {start: 0, end, ticks, ...neutral(0, end, "Rule off · No pyramid score or height rejection.")};
      const scored = current === "heuristic" || current === "combined";
      const cutoff = current === "feasibility" || current === "combined";
      const floor = scored ? number("stacking_safety_limit_multiplier", () => number("unsafe_stacking_multiplier", 0.25, 0, 1), 0, 1) : 1;
      const points = [[0, 1], [soft, 1], [hard, floor]];
      if (!cutoff) points.push([end, floor]);
      return {start: 0, end, ticks, lines: [series(points)],
        guides: [...(scored ? [[soft, "Penalty starts"]] : []), [hard, "Maximum"]],
        markers: [...(scored ? [[soft, 1, "Full score through " + label(soft) + " tiers"]] : []),
          [hard, floor, "At maximum · " + score(floor)]],
        zones: cutoff ? [[hard, end]] : [], rejected: cutoff ? [end] : [],
        note: (scored ? "Full score through " + label(soft) + " tiers · Linear decline to " + score(floor) + " at " + label(hard) + " tiers. " : "No pyramid score penalty. ") +
          (cutoff ? "Above " + label(hard) + " tiers: rejected." : "Above " + label(hard) + " tiers: keep " + score(floor) + ".")};
    }},
    destination: {title: "Destination access", axis: "Equipment reachability", calculate() {
      return binary(mode("destination_access_mode", sharedAccess), ["Reachable", "Unreachable"],
        () => number("unreachable_destination_multiplier", 0.25, 0, 1));
    }},
    occupied: {title: "Occupied-stack access", axis: "Occupied stacks losing access", calculate() {
      const current = occupiedMode();
      return access(current, current === "heuristic" ? number("occupied_access_loss_weight", 1, 0) : 0);
    }},
    future: {title: "Future receiving access", axis: "Receiving options losing access", calculate() {
      const current = mode("preserve_future_access_mode",
        () => flag("feasibility.preserve_future_access", true) ? occupiedMode() : "off");
      return access(current, current === "heuristic" ? number("future_access_loss_weight", 1, 0) : 0);
    }},
    stackingStart: {title: "Start location", axis: "Distance from the preferred row or slot", calculate() {
      const setting = read("heuristic.stacking_start_axis");
      const axis = setting?.match(/^("{1,3}|'{1,3})(off|row|slot)\1$/)?.[2] ?? (setting === undefined ? "off" : null);
      if (!axis) invalid("stacking_start_axis");
      if (axis === "off") return {start: 0, end: 8, ticks: [0, 2, 4, 6, 8], ...neutral(0, 8)};
      const position = number("stacking_start_position", 1, 1, Number.MAX_VALUE, true);
      const half = number("hl_stacking_start_distance", 2);
      const end = rangeEnd(half, 8);
      return {start: 0, end, ticks: [0, end / 4, end / 2, end * 0.75, end],
        lines: [decay(1, half, end)], markers: [[half, 0.5, "Half score " + score(0.5)]],
        note: (axis === "row" ? "Row " : "Slot ") + label(position) + " " + score(1) + " · " +
          label(half) + " " + axis + (half === 1 ? "" : "s") + " away " + score(0.5)};
    }},
    weight: {axis: "Supporting − incoming weight (CSV units)", calculate() {
      const on = flag("heuristic.enable_delta_container_mass", true);
      if (!on) return {start: -5000, end: 20000, ticks: [-5000, 0, 10000, 20000], narrowTicks: [0, 10000, 20000],
        ...neutral(-5000, 20000), specials: [["Unknown", 1]]};
      const peak = number("w_delta_container_mass", 10);
      const half = number("hl_delta_container_mass", 5000);
      const end = rangeEnd(half, 20000);
      const start = -end / 4;
      const heavier = number("heavier_container_fallback_score", fallback, 0);
      return {start, end, ticks: [start, 0, end / 2, end], narrowTicks: [0, end / 2, end],
        lines: [series([[start, heavier], [0, heavier]]), decay(peak, half, end)],
        markers: [[0, heavier, "Heavier incoming " + score(heavier), "", true], [0, peak, "Equal weights " + score(peak)],
          [half, peak / 2, "Half score " + score(peak / 2)]],
        specials: [["Unknown", number("no_delta_container_mass_value", 0.1, 0)]],
        note: "Equal weights " + score(peak) + " · Half-score difference " + score(peak / 2) + " · Heavier incoming " + score(heavier)};
    }},
    equipment: {axis: "Equipment distance (yard grid units)", calculate() {
      const on = flag("heuristic.enable_equipment_distance", true);
      if (!on) return {start: 0, end: 20, ticks: [0, 5, 10, 15, 20], ...neutral(0, 20), specials: [["Outside block", 1]]};
      const peak = number("w_equipment_distance", 10);
      const half = number("hl_equipment_distance", 5);
      const end = rangeEnd(half, 20);
      return {start: 0, end, ticks: [0, end / 4, end / 2, end * 0.75, end],
        lines: [decay(peak, half, end)], markers: [[half, peak / 2, "Half score " + score(peak / 2)]],
        specials: [["Outside block", number("equipment_outside_block_fallback_score", fallback)]],
        note: "Zero distance " + score(peak) + " · Half-score distance " + score(peak / 2)};
    }},
    cluster: {axis: "Distance to one neighboring stack (yard grid units)", calculate() {
      const legacyOn = flag("heuristic.enable_size_cluster", true);
      const neighbors = [
        {term: "reward", name: "Same-size reward", sign: 1, style: ""},
        {term: "penalty", name: "Different-size penalty", sign: -1, style: "other"}
      ].map(neighbor => {
        const {term} = neighbor;
        const on = flag("heuristic.enable_size_cluster_" + term, legacyOn);
        const radius = on ? number("size_cluster_" + term + "_radius",
          () => number("size_cluster_radius", 3, 0, Number.MAX_VALUE, true), 0, Number.MAX_VALUE, term === "penalty") : 0;
        return {...neighbor, on, radius,
          bias: radius ? number("size_cluster_" + term + "_bias", () => number("size_cluster_bias", 1, 0), 0) : 0,
          half: on ? number("hl_size_cluster_" + term + "_distance", () => number("hl_size_cluster_distance", 1.5)) : 1,
          prior: on ? number("size_cluster_" + term + "_prior", () => number("size_cluster_prior", 2)) : 1};
      });
      const radius = Math.max(...neighbors.map(neighbor => neighbor.radius));
      const end = Math.max(4, radius, Math.min(Number.MAX_VALUE, radius * 1.25));
      const ticks = end <= 12 ? [0, 1, 2, end] : [0, end / 2, end];
      const base = {start: 0, end, ticks};
      if (neighbors.every(neighbor => !neighbor.on) || radius === 0 || neighbors.every(neighbor => neighbor.bias === 0)) {
        const state = neighbors.every(neighbor => !neighbor.on) ? "Reward and penalty switches are off" :
          radius === 0 ? "Active search radii are zero" : "Reward and penalty effects are off";
        return {...base, ...neutral(1, end, state + " · 1× for any neighbor.")};
      }
      const factor = (distance, {radius, bias, half, prior, sign}) => {
        if (distance > radius || bias === 0) return 1;
        const evidence = 2 ** (-distance / half);
        return 2 ** (sign * bias * (evidence / (evidence + prior)));
      };
      // Preview fractional cutoffs with separate curves on either side of the cutoff.
      const outsideStart = radius => Number.isInteger(radius) ? Math.hypot(radius, 1) : radius;
      const lines = neighbors.flatMap(neighbor => {
        const {radius, bias, style} = neighbor;
        if (radius < 1 || bias === 0) return [series([[1, 1], [end, 1]], style)];
        const inside = radius === 1 ? [[1, factor(1, neighbor)]] : sample(1, radius, distance => factor(distance, neighbor));
        const outside = outsideStart(radius);
        return [series(inside, style), ...(outside < end ? [series([[outside, 1], [end, 1]], style)] : [])];
      });
      const firstOutside = Math.max(1, outsideStart(radius));
      if (firstOutside < end) lines.push(series([[firstOutside, 1], [end, 1]], "neutral"));
      const markers = [];
      const comparison = [1, 2].map(distance => {
        const results = neighbors.map(neighbor => {
          const {name, radius, style, on} = neighbor;
          const value = factor(distance, neighbor);
          const description = name + " " + score(value) + (!on ? " (off)" : distance > radius ? " (outside radius)" : "");
          markers.push([distance, value, "Distance " + distance + " · " + description, style]);
          return description;
        });
        return "At " + distance + " · " + results.join(", ");
      });
      const guides = neighbors[0].radius === neighbors[1].radius ? [[radius, "Both radii", "neutral"]] :
        neighbors.filter(neighbor => neighbor.radius > 0).map(({term, radius, style}) =>
          [radius, term === "reward" ? "Reward radius" : "Penalty radius", style]);
      return {...base, guides, lines, markers, keys: [...neighbors.map(({name, style}) => [name, style]),
        ["Outside both radii · 1×", "neutral"]], note: comparison.join(". ") + "."};
    }}
  };

  function create(model) {
    const element = el("figure", undefined, "placement-graph");
    element.append(el("figcaption", model.title ? model.title + " score" : "Score model"));
    const axis = el("div", model.axis, "placement-graph-axis");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("role", "img");
    const yTitle = el("div", "Score multiplier", "placement-graph-y-title");
    const keys = el("div", undefined, "placement-graph-keys");
    const note = el("p", undefined, "placement-graph-note");
    note.setAttribute("aria-live", "polite");
    element.append(yTitle, svg, axis, keys, note);
    let data;
    const resize = new ResizeObserver(draw);
    resize.observe(svg);

    function update() {
      try {
        const next = model.calculate();
        const values = [...next.lines.flatMap(line => line.points), ...(next.markers ?? []), ...(next.specials ?? [])];
        if (values.some(([, value]) => !Number.isFinite(value))) throw new Error("These settings exceed the chart’s numeric range.");
        data = next;
        note.textContent = data.note;
        keys.replaceChildren(...(data.keys ?? []).map(([name, style]) => el("span", name, style)));
      } catch (error) {
        data = undefined;
        note.textContent = error.message;
        keys.replaceChildren();
      }
      svg.toggleAttribute("hidden", !data);
      axis.hidden = !data;
      yTitle.hidden = !data;
      draw();
    }

    function draw() {
      if (!data || !svg.clientWidth) return;
      const width = svg.clientWidth;
      const left = 49;
      const right = width - (data.specials ? 95 : 22);
      const bottom = 151;
      const top = 12;
      const max = Math.max(1, ...data.lines.flatMap(line => line.points.map(point => point[1])),
        ...(data.specials ?? []).map(point => point[1]));
      const scale = Math.max(Math.abs(data.start), data.end);
      const x = value => left + (value / scale - data.start / scale) / (data.end / scale - data.start / scale) * (right - left);
      const y = value => bottom - value / max * (bottom - top);
      svg.replaceChildren();
      svg.setAttribute("viewBox", "0 0 " + width + " 204");
      svg.setAttribute("aria-label", model.axis + " versus score multiplier. " + data.note +
        (data.specials ?? []).map(([name, value]) => " " + name + " " + score(value) + ".").join(""));
      function add(tag, attrs, content, parent = svg) {
        const node = document.createElementNS(svg.namespaceURI, tag);
        for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
        if (content) node.textContent = content;
        parent.append(node);
        return node;
      }
      const text = (x, y, content, anchor = "middle") =>
        add("text", {x, y, "text-anchor": anchor}, content);
      const line = (x1, y1, x2, y2, style = "") => add("line", {x1, y1, x2, y2, class: style});
      function dot(a, b, title, style = "", hollow = false) {
        const mark = add("circle", {cx: x(a), cy: y(b), r: 3.5, class: "point " + style + (hollow ? " hollow" : "")});
        add("title", {}, title, mark);
      }
      for (const [start, end] of data.zones ?? []) {
        add("rect", {x: x(start), y: top, width: x(end) - x(start), height: bottom - top, class: "rejected-zone"});
      }
      for (const portion of [0, 0.25, 0.5, 0.75, 1]) {
        const value = max * portion;
        line(left, y(value), right, y(value));
        text(left - 7, y(value) + 4, label(value), "end");
      }
      for (const [position, caption, style] of data.guides ?? []) {
        line(x(position), top, x(position), bottom, "guide " + style);
        const shortCaption = width < 320 ? ({"Penalty starts": "Start", "Maximum": "Limit"}[caption] ?? caption) : caption;
        text(x(position), bottom + 37, shortCaption);
      }
      const ticks = width < 320 && data.narrowTicks ? data.narrowTicks :
        data.ticks.filter((_, index) => right - left > 300 || data.ticks.length < 5 || index % 2 === 0);
      for (const tick of ticks) {
        line(x(tick), bottom, x(tick), bottom + 4);
        const caption = data.labels?.[tick] ?? label(tick);
        text(x(tick), bottom + 18, caption, tick === data.end && !data.specials && caption.length > 5 ? "end" : "middle");
      }
      for (const {points, style, dots} of data.lines) {
        if (points.length > 1) {
          const coordinates = data.step && points.length === 2
            ? [points[0], [0.5, points[0][1]], [0.5, points[1][1]], points[1]] : points;
          add("polyline", {points: coordinates.map(([a, b]) => x(a) + "," + y(b)).join(" "), class: style});
        }
        if (dots) for (const [a, b] of points) dot(a, b, (data.labels?.[a] ?? label(a)) + " · " + score(b), style);
      }
      for (const marker of data.markers ?? []) dot(...marker);
      if (data.rejected?.length) {
        text(left - 7, bottom + 39, "Reject", "end");
        for (const failure of data.rejected) {
          const mark = add("path", {d: "M" + (x(failure) - 3) + " " + (bottom + 32) + "l6 6m0 -6l-6 6", class: "reject"});
          add("title", {}, (data.labels?.[failure] ?? label(failure)) + " · Rejected", mark);
        }
      }
      for (const [name, value] of data.specials ?? []) {
        const position = right + 49;
        line(right + 9, top, right + 9, bottom);
        add("circle", {cx: position, cy: y(value), r: 3.5, class: "point"});
        text(position, bottom + 18, name);
        text(position, bottom + 36, score(value));
      }
    }
    return {element, update, disconnect: () => resize.disconnect()};
  }

  return Object.fromEntries((keys ?? Object.keys(models)).map(key => [key, create(models[key])]));
}
