/* ------------------------------------------------------------------
   磁盘调度仿真 · 前端逻辑（无框架、无构建步骤）
   ------------------------------------------------------------------ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ALGO_SLOTS = ["--a0", "--a1", "--a2", "--a3", "--a4", "--a5"];
const LS_KEY = "disksched.v1";

const state = {
  tracks: 200,
  start: 53,
  direction: "up",
  seqText: "98, 183, 37, 122, 14, 124, 65, 67",
  algos: ["FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"],
  seekMs: 0.15,
  rotMs: 4.17,
  scanToEnd: true,
  countReturn: true,
  view: "trace",
  focus: "all",
  mode: "static",
  stream: "hotspot",
  streamCount: 120,
  span: 600,
  streamSeed: null,
  theme: "night",
  accent: "",
  density: "cozy",
  meta: null,
  data: null,
  anim: { playing: false, p: 1, raf: 0, t0: 0 },
};

/* ------------------------------------------------------------- 工具 */

const fmt = (n, d = 0) =>
  Number(n).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });

const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const colorOf = (algo) => {
  const idx = (state.meta?.algos || []).findIndex((a) => a.id === algo);
  return cssVar(ALGO_SLOTS[idx >= 0 ? idx % 6 : 0]);
};

function parseSeq(text) {
  const nums = String(text).match(/-?\d+/g) || [];
  return nums.map(Number);
}

function saveState() {
  const { tracks, start, direction, seqText, algos, seekMs, rotMs, scanToEnd,
          countReturn, theme, accent, density, focus, mode, stream, streamCount, span,
          streamSeed } = state;
  localStorage.setItem(LS_KEY, JSON.stringify({
    tracks, start, direction, seqText, algos, seekMs, rotMs, scanToEnd,
    countReturn, theme, accent, density, focus, mode, stream, streamCount, span, streamSeed,
  }));
}

function loadState() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    Object.assign(state, JSON.parse(raw));
  } catch (_) { /* 忽略损坏的本地状态 */ }
}

/* ------------------------------------------------------------- 主题 */

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  document.documentElement.dataset.density = state.density;
  if (state.accent) {
    document.documentElement.style.setProperty("--accent", state.accent);
    document.documentElement.style.setProperty("--accent-ink", pickInk(state.accent));
  } else {
    document.documentElement.style.removeProperty("--accent");
    document.documentElement.style.removeProperty("--accent-ink");
  }
  $("#themeSelect").value = state.theme;
  $("#densitySelect").value = state.density;
  $$("#accentSwatches .sw").forEach((b) =>
    b.classList.toggle("active", b.dataset.accent === state.accent));
}

function pickInk(hex) {
  const c = hex.replace("#", "");
  const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.62 ? "#101417" : "#ffffff";
}

/* ------------------------------------------------------------- 初始化 */

async function init() {
  loadState();
  applyTheme();
  bindUI();

  try {
    const res = await fetch("/api/meta");
    state.meta = await res.json();
  } catch (e) {
    $("#fileWarn").hidden = false;
    return;
  }

  buildAlgoChips();
  buildPatternOptions();
  buildPresetOptions();
  buildStreamOptions();
  syncInputs();
  applyModeUI();
  await run();
}

function buildAlgoChips() {
  const box = $("#algoChips");
  box.innerHTML = "";
  state.meta.algos.forEach((a, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (state.algos.includes(a.id) ? " on" : "");
    btn.style.setProperty("--c", `var(${ALGO_SLOTS[i]})`);
    btn.textContent = a.id;
    btn.title = `${a.name}：${a.short}`;
    btn.setAttribute("aria-pressed", state.algos.includes(a.id));
    btn.addEventListener("click", () => {
      const on = btn.classList.toggle("on");
      btn.setAttribute("aria-pressed", on);
      state.algos = $$("#algoChips .chip.on").map((c) => c.textContent);
      saveState();
    });
    box.appendChild(btn);
  });
}

function buildPatternOptions() {
  const sel = $("#pattern");
  sel.innerHTML = state.meta.patterns
    .map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  updatePatternHint();
  sel.addEventListener("change", updatePatternHint);
}

function updatePatternHint() {
  const id = $("#pattern").value;
  const p = state.meta?.patterns.find((x) => x.id === id);
  $("#patternHint").textContent = p ? p.desc : "";
}

function buildPresetOptions() {
  const sel = $("#preset");
  sel.innerHTML = '<option value="">自定义</option>' + state.meta.presets
    .map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
}

function buildStreamOptions() {
  const sel = $("#stream");
  sel.innerHTML = state.meta.streams
    .map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
  sel.value = state.stream;
  updateStreamHint();
  sel.addEventListener("change", () => {
    state.stream = sel.value;
    updateStreamHint();
    saveState();
  });
  $("#streamCount").addEventListener("change", (e) => {
    state.streamCount = Math.max(2, Math.min(2000, Number(e.target.value) || 120));
    e.target.value = state.streamCount;
    updateStreamHint();
    saveState();
  });
  $("#span").addEventListener("change", (e) => {
    state.span = Math.max(10, Number(e.target.value) || 600);
    e.target.value = state.span;
    updateStreamHint();
    saveState();
  });
  $("#streamSeed").addEventListener("change", (e) => {
    const v = e.target.value.trim();
    state.streamSeed = v === "" ? null : Number(v);
    saveState();
  });
  $("#btnStream").addEventListener("click", () => seedStream());
}

function updateStreamHint() {
  const s = state.meta?.streams.find((x) => x.id === state.stream);
  $("#streamHint").textContent = s ? s.desc : "";
  $("#streamCountLabel").textContent = `${state.streamCount} 个`;
  const est = state.rotMs + state.seekMs * 10;
  const load = (state.streamCount * est) / Math.max(1, state.span);
  const el = $("#loadHint");
  el.innerHTML = `估算负载 ρ ≈ <b>${load.toFixed(1)}</b>` +
    (load > 1 ? "　队列会持续增长，适合看饥饿" : "　队列基本能排空，延迟偏低");
  el.classList.toggle("hot", load > 1);
}

function seedStream() {
  const el = $("#streamSeed");
  const v = el.value.trim();
  if (v === "") {
    el.value = String(Math.floor(Math.random() * 9000) + 100);
  }
  state.streamSeed = Number(el.value) || null;
  saveState();
  run();
}

/* ------------------------------------------------------------- 表单绑定 */

function syncInputs() {
  $("#tracks").value = state.tracks;
  $("#tracksRange").value = state.tracks;
  $("#tracksRange").max = Math.max(1000, state.tracks);
  $("#start").value = state.start;
  $("#startRange").max = state.tracks - 1;
  $("#startRange").value = state.start;
  $("#seq").value = state.seqText;
  $("#seekMs").value = state.seekMs;
  $("#rotMs").value = state.rotMs;
  $("#scanToEnd").checked = state.scanToEnd;
  $("#countReturn").checked = state.countReturn;
  $("#streamCount").value = state.streamCount;
  $("#span").value = state.span;
  if (state.streamSeed !== null && state.streamSeed !== undefined) {
    $("#streamSeed").value = state.streamSeed;
  }
  $$(".seg[data-dir]").forEach((b) => {
    const on = b.dataset.dir === state.direction;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", on);
  });
  updateSeqCount();
}

function applyModeUI() {
  $$(".modeswitch .seg").forEach((b) => {
    const on = b.dataset.mode === state.mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", on);
  });
  $("#staticBlock").hidden = state.mode !== "static";
  $("#dynBlock").hidden = state.mode !== "dynamic";
  $("#tableNote").textContent = state.mode === "dynamic"
    ? "点击某行可切换上方轨迹；注意最坏等待才是饥饿指标"
    : "点击某行可切换上方轨迹";
}

function updateSeqCount() {
  const n = parseSeq(state.seqText).length;
  $("#seqCount").textContent = `${n} 个`;
}

function bindUI() {
  // 主题 / 密度 / 强调色
  $("#themeSelect").addEventListener("change", (e) => {
    state.theme = e.target.value;
    applyTheme(); saveState(); draw();
  });
  $("#densitySelect").addEventListener("change", (e) => {
    state.density = e.target.value;
    applyTheme(); saveState(); draw();
  });
  $$("#accentSwatches .sw").forEach((b) =>
    b.addEventListener("click", () => {
      state.accent = state.accent === b.dataset.accent ? "" : b.dataset.accent;
      applyTheme(); saveState(); draw();
    }));

  // 磁道数 / 起始位置
  const onTracks = (v) => {
    state.tracks = Math.max(2, Math.min(2000, Number(v) || 200));
    state.start = Math.min(state.start, state.tracks - 1);
    syncInputs(); saveState();
  };
  $("#tracks").addEventListener("change", (e) => onTracks(e.target.value));
  $("#tracksRange").addEventListener("input", (e) => {
    onTracks(e.target.value);
    draw();
  });
  const onStart = (v) => {
    state.start = Math.max(0, Math.min(state.tracks - 1, Number(v) || 0));
    $("#start").value = state.start;
    $("#startRange").value = state.start;
    saveState();
  };
  $("#start").addEventListener("change", (e) => onStart(e.target.value));
  $("#startRange").addEventListener("input", (e) => {
    onStart(e.target.value);
    draw();
  });

  // 方向
  $$(".seg[data-dir]").forEach((b) =>
    b.addEventListener("click", () => {
      state.direction = b.dataset.dir;
      $$(".seg[data-dir]").forEach((x) => {
        x.classList.toggle("active", x === b);
        x.setAttribute("aria-checked", x === b);
      });
      saveState();
    }));

  // 模式切换
  $$(".modeswitch .seg").forEach((b) =>
    b.addEventListener("click", async () => {
      if (state.mode === b.dataset.mode) return;
      state.mode = b.dataset.mode;
      saveState();
      applyModeUI();
      await run();
    }));

  // 序列
  $("#seq").addEventListener("input", (e) => {
    state.seqText = e.target.value;
    updateSeqCount(); saveState();
  });

  // 生成
  $("#btnGen").addEventListener("click", generateSeq);
  $("#preset").addEventListener("change", async (e) => {
    const id = e.target.value;
    if (!id) return;
    const p = state.meta.presets.find((x) => x.id === id);
    if (!p) return;
    state.tracks = p.tracks;
    state.start = p.start;
    state.direction = p.direction;
    state.seqText = p.sequence.join(", ");
    syncInputs(); saveState();
    await run();
  });

  // 模型参数
  $("#seekMs").addEventListener("change", (e) => {
    state.seekMs = Math.max(0, Number(e.target.value) || 0); saveState();
  });
  $("#rotMs").addEventListener("change", (e) => {
    state.rotMs = Math.max(0, Number(e.target.value) || 0); saveState();
  });
  $("#scanToEnd").addEventListener("change", (e) => {
    state.scanToEnd = e.target.checked; saveState();
  });
  $("#countReturn").addEventListener("change", (e) => {
    state.countReturn = e.target.checked; saveState();
  });

  // 全选 / 全不选
  $$("[data-algo-all]").forEach((b) =>
    b.addEventListener("click", () => {
      const all = b.dataset.algoAll === "1";
      $$("#algoChips .chip").forEach((c, i) => {
        c.classList.toggle("on", all);
        c.setAttribute("aria-pressed", all);
      });
      state.algos = all ? state.meta.algos.map((a) => a.id) : [];
      saveState();
    }));

  // 运行
  $("#btnRun").addEventListener("click", run);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
  });

  // 视图切换
  $$("#viewTabs .tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view)));

  // 播放
  $("#btnPlay").addEventListener("click", togglePlay);

  // 导出
  $("#btnExportPng").addEventListener("click", exportPng);
  $("#btnCopyMd").addEventListener("click", copyMd);
  $("#btnDownloadMd").addEventListener("click", () => download("磁盘调度报告.md", state.data?.report_md || "", "text/markdown"));
  $("#btnDownloadCsv").addEventListener("click", downloadCsv);
  $("#btnDownloadJson").addEventListener("click", () =>
    download("disk-sched.json", JSON.stringify(state.data, null, 2), "application/json"));

  window.addEventListener("resize", debounce(() => draw(), 120));
}

function debounce(fn, ms) {
  let t = 0;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ------------------------------------------------------------- 运行 */

async function run() {
  const algos = state.algos.length ? state.algos : state.meta.algos.map((a) => a.id);
  const base = {
    tracks: state.tracks,
    start: state.start,
    direction: state.direction,
    seek_ms_per_track: state.seekMs,
    rotational_ms: state.rotMs,
    scan_to_end: state.scanToEnd,
    count_return: state.countReturn,
    algorithms: algos,
  };

  let body;
  if (state.mode === "dynamic") {
    body = { ...base, mode: "dynamic", stream: state.stream,
             count: state.streamCount, span_ms: state.span, seed: state.streamSeed };
  } else {
    const seq = parseSeq(state.seqText);
    if (!seq.length) { showErr("请先输入访问序列"); return; }
    body = { ...base, mode: "static", sequence: seq };
  }

  $("#btnRun").disabled = true;
  try {
    const res = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    if (!data.results || !data.results.length) throw new Error("没有有效请求（检查磁道范围）");
    state.data = data;
    if (!algos.includes(state.focus)) state.focus = "all";
    $("#errBox").hidden = true;
    renderAll();
    startAnim();
  } catch (err) {
    showErr(String(err.message || err));
  } finally {
    $("#btnRun").disabled = false;
  }
}

function showErr(msg) {
  const box = $("#errBox");
  box.textContent = msg;
  box.hidden = false;
}

/* ------------------------------------------------------------- 渲染 */

function renderAll() {
  renderAlgoTabs();
  renderReport();
  if (state.mode === "dynamic") {
    renderKpisDyn();
    renderTableDyn();
    renderBarsDyn();
    renderDetailsDyn();
    drawDynamic();
  } else {
    renderKpis();
    renderTable();
    renderBars();
    renderDetails();
    draw();
  }
}

function renderKpis() {
  const d = state.data;
  const rs = d.results;
  const best = rs.reduce((a, b) => (b.metrics.total_seek < a.metrics.total_seek ? b : a));
  const resp = rs.reduce((a, b) => (b.metrics.avg_response_ms < a.metrics.avg_response_ms ? b : a));
  const fcfs = rs.find((r) => r.algo === "FCFS");
  const save = fcfs && fcfs.metrics.total_seek
    ? Math.round((1 - best.metrics.total_seek / fcfs.metrics.total_seek) * 100) : 0;

  const cards = [
    { label: "请求 / 磁道", value: `${d.sequence.length}<small>个</small>`, sub: `0 – ${d.config.tracks - 1} 磁道` },
    { label: "总寻道最短", value: `${fmt(best.metrics.total_seek)}<small>条</small>`, sub: best.algo + " · " + best.name },
    { label: "平均响应最快", value: `${fmt(resp.metrics.avg_response_ms, 1)}<small>ms</small>`, sub: resp.algo + " · " + resp.name },
    { label: "相对 FCFS 节省", value: `${save}<small>%</small>`, sub: fcfs ? `FCFS ${fmt(fcfs.metrics.total_seek)} 条` : "未选 FCFS" },
  ];
  $("#kpis").innerHTML = cards.map((c) => `
    <div class="kpi">
      <div class="label">${c.label}</div>
      <div class="value">${c.value}</div>
      <div class="sub">${c.sub}</div>
    </div>`).join("");
}

function renderAlgoTabs() {
  const box = $("#algoTabs");
  const rs = state.data.results;
  const items = [{ id: "all", label: "全部" }].concat(rs.map((r) => ({ id: r.algo, label: r.algo })));
  box.innerHTML = "";
  items.forEach((it) => {
    const b = document.createElement("button");
    b.className = "abadge" + (state.focus === it.id ? " on" : "");
    b.textContent = it.label;
    b.style.setProperty("--c", it.id === "all" ? cssVar("--accent") : colorOf(it.id));
    b.addEventListener("click", () => {
      state.focus = it.id;
      saveState();
      renderAlgoTabs();
      renderTable();
      draw();
      if (it.id !== "all") startAnim();
    });
    box.appendChild(b);
  });
}

function renderTable() {
  const rs = state.data.results;
  const best = Math.min(...rs.map((r) => r.metrics.total_seek));
  const head = `<thead><tr>
      <th>算法</th><th>总寻道</th><th>平均/次</th><th>最大单次</th><th>换向</th>
      <th>估算耗时 ms</th><th>平均响应 ms</th><th>最坏响应 ms</th><th>相对最优</th>
    </tr></thead>`;
  const rows = rs.map((r) => {
    const m = r.metrics;
    const ratio = best ? m.total_seek / best : 1;
    const isBest = Math.abs(ratio - 1) < 1e-9;
    return `<tr data-algo="${r.algo}" class="${state.focus === r.algo ? "sel" : ""}">
      <td><span class="algo-cell" style="--c:${colorOf(r.algo)}"><i></i><b>${r.algo}</b>
        <span class="muted">${r.name}</span></span></td>
      <td class="${isBest ? "best-cell" : ""}">${fmt(m.total_seek)}</td>
      <td>${fmt(m.avg_seek, 1)}</td>
      <td>${fmt(m.max_step)}</td>
      <td>${m.reversals}</td>
      <td>${fmt(m.makespan_ms, 1)}</td>
      <td>${fmt(m.avg_response_ms, 1)}</td>
      <td>${fmt(m.max_response_ms, 1)}</td>
      <td class="${isBest ? "ratio-best" : "ratio-pos"}">${isBest ? "最优" : "+" + Math.round((ratio - 1) * 100) + "%"}</td>
    </tr>`;
  }).join("");

  const table = $("#metricsTable");
  table.innerHTML = head + `<tbody>${rows}</tbody>`;
  $$("tbody tr", table).forEach((tr) =>
    tr.addEventListener("click", () => {
      state.focus = tr.dataset.algo;
      saveState(); renderAlgoTabs(); renderTable(); draw(); startAnim();
    }));
}

function renderBars() {
  const rs = [...state.data.results].sort((a, b) => a.metrics.total_seek - b.metrics.total_seek);
  const max = Math.max(...rs.map((r) => r.metrics.total_seek)) || 1;
  $("#barMeta").textContent =
    `总寻道长度（条）· 起点 ${state.data.config.start} · 方向 ${state.data.config.direction === "up" ? "增大" : "减小"} · ` +
    `条长 = 磁头实际移动的磁道数，右侧为总寻道与平均响应`;
  $("#bars").innerHTML = rs.map((r, i) => `
    <div class="bar-row ${i === 0 ? "best" : ""}" style="--c:${colorOf(r.algo)}">
      <div class="name">${r.algo}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(r.metrics.total_seek / max) * 100}%"></div></div>
      <div class="num">${fmt(r.metrics.total_seek)} · ${fmt(r.metrics.avg_response_ms, 1)}ms</div>
    </div>`).join("");
}

function renderDetails() {
  const box = $("#details");
  box.innerHTML = state.data.results.map((r) => {
    const segs = r.segments.filter((s) => s.dist > 0 || s.kind !== "seek");
    const segHtml = segs.map((s) => {
      const cls = s.kind === "turn" ? "turn" : (s.kind === "wrap" || s.kind === "wrap_seek") ? "wrap" : "";
      const tag = s.kind === "turn" ? "空走" : (s.kind === "wrap" || s.kind === "wrap_seek") ? "返回" : "";
      return `<span class="${cls}">${s.from}→${s.to} · ${s.dist}${tag ? " · " + tag : ""}${!("counted" in s) || s.counted ? "" : " · 不计"}</span>`;
    }).join("");
    return `<div class="detail" style="--c:${colorOf(r.algo)}">
      <h3><i></i>${r.algo}<em>${r.name} · ${r.metrics.total_seek} 条 · 换向 ${r.metrics.reversals} 次</em></h3>
      <div class="lbl">服务顺序</div>
      <div class="seq">${r.order.map((x) => `<b>${x}</b>`).join(" → ")}</div>
      <div class="lbl">分段（含空走 / 返回）</div>
      <div class="seg">${segHtml || '<span>无移动</span>'}</div>
    </div>`;
  }).join("");
}

/* ------------------------------------------------------------- 报告 */

function renderReport() {
  $("#reportBody").innerHTML = mdToHtml(state.data.report_md || "");
}

function mdToHtml(md) {
  const lines = md.split("\n");
  const out = [];
  let i = 0;
  const inline = (s) => s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${buf.join("\n").replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code></pre>`);
      continue;
    }
    if (/^\|/.test(line) && /^\|[\s:|-]+\|?$/.test(lines[i + 1] || "")) {
      const cells = (row) => row.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const body = [];
      while (i < lines.length && /^\|/.test(lines[i])) body.push(cells(lines[i++]));
      out.push(`<div class="mdtable"><table><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>` +
        body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("") +
        "</tbody></table></div>");
      continue;
    }
    if (/^###\s/.test(line)) { out.push(`<h3>${inline(line.slice(4))}</h3>`); i++; continue; }
    if (/^##\s/.test(line)) { out.push(`<h2>${inline(line.slice(3))}</h2>`); i++; continue; }
    if (/^#\s/.test(line)) { out.push(`<h1>${inline(line.slice(2))}</h1>`); i++; continue; }
    if (/^>\s?/.test(line)) { out.push(`<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`); i++; continue; }
    if (/^---+$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^\s*[-*]\s/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) buf.push(`<li>${inline(lines[i++].replace(/^\s*[-*]\s/, ""))}</li>`);
      out.push(`<ul>${buf.join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+\.\s/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) buf.push(`<li>${inline(lines[i++].replace(/^\s*\d+\.\s/, ""))}</li>`);
      out.push(`<ol>${buf.join("")}</ol>`);
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    out.push(`<p>${inline(line)}</p>`);
    i++;
  }
  return out.join("\n");
}

/* ------------------------------------------------------------- 绘图 */

function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 800;
  const h = canvas.clientHeight || 460;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function seriesPoints(result) {
  // 纵轴 = 累计寻道磁道数，终点高度即总寻道
  const pts = [{ x: result.path[0], y: 0 }];
  let acc = 0;
  result.segments.forEach((s) => {
    if (s.counted) acc += s.dist;
    pts.push({ x: s.to, y: acc });
  });
  return pts;
}

function draw() {
  if (!state.data) return;
  if (state.mode === "dynamic") return drawDynamic();
  const canvas = $("#traceCanvas");
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);

  const rs = state.focus === "all"
    ? state.data.results
    : state.data.results.filter((r) => r.algo === state.focus);
  if (!rs.length) return;

  const tracks = state.data.config.tracks;
  const series = rs.map((r) => ({ r, pts: seriesPoints(r) }));
  if (state.focus === "all") {
    series.sort((a, b) => b.pts[b.pts.length - 1].y - a.pts[a.pts.length - 1].y);
  }
  const yMax = Math.max(...series.map((s) => s.pts[s.pts.length - 1].y), 1);

  const padL = 56, padR = 96, padT = 18, padB = 36;
  const x = (t) => padL + (t / Math.max(1, tracks - 1)) * (w - padL - padR);
  const y = (v) => padT + (v / yMax) * (h - padT - padB);

  const ink = cssVar("--ink");
  const muted = cssVar("--muted");
  const grid = cssVar("--grid");

  // 网格：横轴磁道
  ctx.save();
  ctx.font = '10px "Cascadia Mono", Consolas, monospace';
  ctx.fillStyle = muted;
  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;

  const stepX = niceStep(tracks, 10);
  for (let t = 0; t < tracks; t += stepX) {
    const px = x(t);
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    ctx.moveTo(px, padT - 6);
    ctx.lineTo(px, h - padB);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.textAlign = "center";
    ctx.fillText(String(t), px, h - padB + 14);
  }
  ctx.textAlign = "center";
  ctx.fillText("磁道号", padL + (w - padL - padR) / 2, h - 4);

  // 纵轴：累计寻道
  const stepY = niceStep(yMax, 5);
  for (let v = 0; v <= yMax + 0.001; v += stepY) {
    const py = y(v);
    ctx.globalAlpha = 0.45;
    ctx.beginPath();
    ctx.moveTo(padL, py);
    ctx.lineTo(w - padR, py);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.textAlign = "right";
    ctx.fillText(fmt(v), padL - 8, py + 3);
  }
  ctx.save();
  ctx.translate(13, (padT + h - padB) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText("累计寻道磁道数", 0, 0);
  ctx.restore();
  ctx.restore();

  // 起点参考线
  const sx = x(state.data.config.start);
  ctx.save();
  ctx.setLineDash([4, 5]);
  ctx.strokeStyle = cssVar("--accent");
  ctx.globalAlpha = 0.5;
  ctx.beginPath();
  ctx.moveTo(sx, padT - 4);
  ctx.lineTo(sx, h - padB);
  ctx.stroke();
  ctx.restore();
  ctx.save();
  ctx.fillStyle = cssVar("--accent");
  ctx.font = '10px "Cascadia Mono", Consolas, monospace';
  ctx.textAlign = "center";
  ctx.fillText(`起点 ${state.data.config.start}`, sx, h - padB - 7);
  ctx.restore();

  // 轨迹
  series.forEach(({ r, pts }, idx) => {
    const color = colorOf(r.algo);
    const single = state.focus !== "all";
    const alpha = single ? 1 : 0.42 + (idx === 0 ? 0.18 : 0);
    const progress = single && state.anim.playing ? state.anim.p : 1;
    const cut = Math.max(2, Math.ceil(pts.length * progress));
    const visible = pts.slice(0, cut);

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = single ? 2.1 : 1.5;
    ctx.lineJoin = "round";
    ctx.beginPath();
    visible.forEach((p, i) => {
      const px = x(p.x), py = y(p.y);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();

    // 服务点
    let lastLabelY = -999;
    visible.forEach((p, i) => {
      if (i === 0) return;
      const px = x(p.x), py = y(p.y);
      const isEnd = i === visible.length - 1 && progress < 1;
      ctx.beginPath();
      ctx.arc(px, py, single ? 3.4 : 2.2, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      if (single) {
        ctx.strokeStyle = cssVar("--panel");
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      if (single && pts.length <= 24 && Math.abs(py - lastLabelY) > 13) {
        ctx.save();
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.85;
        ctx.font = '9.5px "Cascadia Mono", Consolas, monospace';
        ctx.textAlign = p.x > tracks * 0.86 ? "right" : "left";
        ctx.fillText(String(i), px + (p.x > tracks * 0.86 ? -7 : 7), py - 6);
        ctx.restore();
        lastLabelY = py;
      }
      if (isEnd) {
        // 磁头
        ctx.beginPath();
        ctx.arc(px, py, 7, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.globalAlpha = alpha;
      }
    });
    ctx.restore();
  });

  // 右侧终点标签：按总寻道排序，重叠时自动错开
  if (state.focus === "all") {
    const labels = series.map((s) => ({
      algo: s.r.algo,
      color: colorOf(s.r.algo),
      y0: y(s.pts[s.pts.length - 1].y),
      total: s.pts[s.pts.length - 1].y,
    })).sort((a, b) => a.y0 - b.y0);

    let cursor = padT + 4;
    labels.forEach((l) => { l.ly = Math.max(l.y0, cursor); cursor = l.ly + 12; });
    const overflow = labels.length ? labels[labels.length - 1].ly - (h - padB) : 0;
    if (overflow > 0) labels.forEach((l) => { l.ly -= overflow; });

    ctx.save();
    ctx.font = '10px "Cascadia Mono", Consolas, monospace';
    ctx.textAlign = "left";
    labels.forEach((l) => {
      ctx.strokeStyle = l.color;
      ctx.globalAlpha = 0.45;
      ctx.beginPath();
      ctx.moveTo(w - padR + 1, l.y0);
      ctx.lineTo(w - padR + 6, l.ly);
      ctx.stroke();
      ctx.globalAlpha = 0.95;
      ctx.fillStyle = l.color;
      ctx.fillText(`${l.algo} ${fmt(l.total)}`, w - padR + 8, l.ly + 3);
    });
    ctx.restore();
  }

  renderLegend(rs);
}

function niceStep(span, ticks) {
  const raw = span / ticks;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  const norm = raw / mag;
  const mult = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return Math.max(1, mult * mag);
}

function renderLegend(rs) {
  const box = $("#traceLegend");
  if (state.focus === "all") {
    box.innerHTML = rs.map((r) =>
      `<span style="color:${colorOf(r.algo)}"><i></i>${r.algo} · ${fmt(r.metrics.total_seek)} 条</span>`).join("");
  } else {
    const r = rs[0];
    box.innerHTML = `<span style="color:${colorOf(r.algo)}"><i></i>${r.algo}（${r.name}）</span>` +
      `<span>总寻道 ${fmt(r.metrics.total_seek)} 条 · 平均 ${fmt(r.metrics.avg_seek, 1)} 条/次</span>` +
      `<span>纵轴为累计寻道量，曲线向下走到底的位置就是总寻道</span>`;
  }
}

/* ------------------------------------------------------------- 动画 */

function startAnim() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (state.focus === "all") { state.anim.playing = false; $("#btnPlay").textContent = "▶ 播放"; draw(); return; }
  cancelAnimationFrame(state.anim.raf);
  state.anim.playing = true;
  state.anim.p = 0;
  state.anim.t0 = performance.now();
  $("#btnPlay").textContent = "❚❚ 暂停";
  const dur = state.mode === "dynamic"
    ? 2600
    : Math.min(3200, 700 + (state.data.sequence ? state.data.sequence.length : 8) * 120);
  const tick = (now) => {
    const p = Math.min(1, (now - state.anim.t0) / dur);
    state.anim.p = easeOut(p);
    draw();
    if (p < 1) state.anim.raf = requestAnimationFrame(tick);
    else { state.anim.playing = false; $("#btnPlay").textContent = "▶ 重播"; }
  };
  state.anim.raf = requestAnimationFrame(tick);
}

function easeOut(t) { return 1 - Math.pow(1 - t, 2.2); }

function togglePlay() {
  if (state.anim.playing) {
    cancelAnimationFrame(state.anim.raf);
    state.anim.playing = false;
    $("#btnPlay").textContent = "▶ 继续";
    return;
  }
  if (state.focus === "all") {
    const first = state.data.results[0];
    if (first) { state.focus = first.algo; renderAlgoTabs(); renderTable(); }
  }
  startAnim();
}

/* ------------------------------------------------------------- 视图 */

function switchView(view) {
  state.view = view;
  $$("#viewTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  $("#viewTrace").hidden = view !== "trace";
  $("#viewBars").hidden = view !== "bars";
  $("#viewReport").hidden = view !== "report";
  $("#traceTools").style.visibility = view === "trace" ? "visible" : "hidden";
  if (view === "trace") draw();
}

/* ------------------------------------------------------------- 生成 */

async function generateSeq() {
  const pattern = $("#pattern").value;
  const count = Math.max(2, Math.min(200, Number($("#genCount").value) || 12));
  const seedRaw = $("#genSeed").value.trim();
  const seed = seedRaw === "" ? undefined : Number(seedRaw);
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pattern, count, seed, tracks: state.tracks, start: state.start }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    state.seqText = data.sequence.join(", ");
    $("#seq").value = state.seqText;
    $("#preset").value = "";
    updateSeqCount();
    saveState();
    await run();
  } catch (e) {
    showErr(String(e.message || e));
  }
}

/* ------------------------------------------------------------- 动态模式渲染 */

function dynResults() {
  return state.data.results.filter((r) => r.metrics && r.metrics.total);
}

function renderKpisDyn() {
  const rs = dynResults();
  if (!rs.length) return;
  const bestAvg = rs.reduce((a, b) => (b.metrics.avg_wait < a.metrics.avg_wait ? b : a));
  const bestMax = rs.reduce((a, b) => (b.metrics.max_wait < a.metrics.max_wait ? b : a));
  const bestTp = rs.reduce((a, b) => (b.metrics.throughput > a.metrics.throughput ? b : a));
  const first = rs[0].metrics;
  const cards = [
    { label: "请求 / 完成", value: `${first.served}<small>/${first.total}</small>`,
      sub: `${state.data.stream_name || ""} · 窗口 ${state.data.span_ms} ms` },
    { label: "平均等待最短", value: `${fmt(bestAvg.metrics.avg_wait, 1)}<small>ms</small>`, sub: bestAvg.algo },
    { label: "最坏等待最低", value: `${fmt(bestMax.metrics.max_wait, 1)}<small>ms</small>`, sub: bestMax.algo },
    { label: "吞吐最高", value: `${fmt(bestTp.metrics.throughput, 1)}<small>/s</small>`, sub: bestTp.algo },
  ];
  $("#kpis").innerHTML = cards.map((c) => `
    <div class="kpi">
      <div class="label">${c.label}</div>
      <div class="value">${c.value}</div>
      <div class="sub">${c.sub}</div>
    </div>`).join("");
}

function renderTableDyn() {
  const rs = state.data.results;
  const bestAvg = Math.min(...rs.map((r) => r.metrics.avg_wait));
  const head = `<thead><tr>
      <th>算法</th><th>完成</th><th>平均等待 ms</th><th>P95 等待</th><th>最大等待</th>
      <th>平均响应</th><th>完成用时 ms</th><th>吞吐 /s</th><th>公平性</th>
    </tr></thead>`;
  const rows = rs.map((r) => {
    const m = r.metrics;
    const isBest = Math.abs(m.avg_wait - bestAvg) < 1e-9;
    const fairCls = m.fairness >= 5 ? "ratio-pos" : "";
    return `<tr data-algo="${r.algo}" class="${state.focus === r.algo ? "sel" : ""}">
      <td><span class="algo-cell" style="--c:${colorOf(r.algo)}"><i></i><b>${r.algo}</b>
        <span class="muted">${r.name}</span></span></td>
      <td>${m.served}/${m.total}</td>
      <td class="${isBest ? "best-cell" : ""}">${fmt(m.avg_wait, 1)}</td>
      <td>${fmt(m.p95_wait, 1)}</td>
      <td class="${m.fairness >= 5 ? "ratio-pos" : ""}">${fmt(m.max_wait, 1)}</td>
      <td>${fmt(m.avg_turn, 1)}</td>
      <td>${fmt(m.makespan, 0)}</td>
      <td>${fmt(m.throughput, 1)}</td>
      <td class="${fairCls}">${fmt(m.fairness, 1)}×</td>
    </tr>`;
  }).join("");
  const table = $("#metricsTable");
  table.innerHTML = head + `<tbody>${rows}</tbody>`;
  $$("tbody tr", table).forEach((tr) =>
    tr.addEventListener("click", () => {
      state.focus = tr.dataset.algo;
      saveState(); renderAlgoTabs(); renderTableDyn(); drawDynamic(); startAnim();
    }));
}

function renderBarsDyn() {
  const rs = [...state.data.results].sort((a, b) => a.metrics.max_wait - b.metrics.max_wait);
  const max = Math.max(...rs.map((r) => r.metrics.max_wait)) || 1;
  $("#barMeta").textContent =
    `最坏等待（ms）· ${state.data.stream_name || ""} · 同一负载下谁会把某个请求拖最久`;
  $("#bars").innerHTML = rs.map((r, i) => `
    <div class="bar-row ${i === 0 ? "best" : ""}" style="--c:${colorOf(r.algo)}">
      <div class="name">${r.algo}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(r.metrics.max_wait / max) * 100}%"></div></div>
      <div class="num">${fmt(r.metrics.max_wait, 0)} · 均${fmt(r.metrics.avg_wait, 1)}</div>
    </div>`).join("");
}

function renderDetailsDyn() {
  const box = $("#details");
  box.innerHTML = state.data.results.map((r) => {
    const worst = [...r.records].sort((a, b) => b.wait - a.wait).slice(0, 4);
    const chips = worst.map((x) =>
      `<span>磁道 ${x.track} · 等 ${fmt(x.wait, 0)}ms</span>`).join("");
    return `<div class="detail" style="--c:${colorOf(r.algo)}">
      <h3><i></i>${r.algo}<em>${r.name} · 均 ${fmt(r.metrics.avg_wait, 1)}ms · 最大 ${fmt(r.metrics.max_wait, 1)}ms · ${fmt(r.metrics.fairness, 1)}×</em></h3>
      <div class="lbl">等得最久的四个请求</div>
      <div class="seg">${chips || "<span>无</span>"}</div>
    </div>`;
  }).join("");
}

function drawDynamic() {
  const canvas = $("#traceCanvas");
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  if (!state.data) return;

  const all = state.data.results;
  const rs = state.focus === "all" ? all : all.filter((r) => r.algo === state.focus);
  if (!rs.length) return;
  const single = state.focus !== "all";

  const tracks = state.data.config.tracks;
  const tMax = Math.max(...rs.map((r) => r.metrics.makespan), 1);
  const padL = 58, padR = 84, padT = 20, padB = 36;
  const x = (t) => padL + (t / Math.max(1, tracks - 1)) * (w - padL - padR);
  const y = (v) => padT + (v / tMax) * (h - padT - padB);

  const muted = cssVar("--muted");
  const grid = cssVar("--grid");

  ctx.save();
  ctx.font = '10px "Cascadia Mono", Consolas, monospace';
  ctx.fillStyle = muted;
  ctx.strokeStyle = grid;

  const stepX = niceStep(tracks, 10);
  for (let t = 0; t < tracks; t += stepX) {
    const px = x(t);
    ctx.globalAlpha = 0.45;
    ctx.beginPath(); ctx.moveTo(px, padT - 6); ctx.lineTo(px, h - padB); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.textAlign = "center";
    ctx.fillText(String(t), px, h - padB + 14);
  }
  ctx.fillText("磁道号", padL + (w - padL - padR) / 2, h - 4);

  const stepY = niceStep(tMax, 5);
  for (let v = 0; v <= tMax + 1e-6; v += stepY) {
    const py = y(v);
    ctx.globalAlpha = 0.45;
    ctx.beginPath(); ctx.moveTo(padL, py); ctx.lineTo(w - padR, py); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.textAlign = "right";
    ctx.fillText(fmt(v), padL - 8, py + 3);
  }
  ctx.save();
  ctx.translate(14, (padT + h - padB) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText("时间 (ms)", 0, 0);
  ctx.restore();
  ctx.restore();

  const cutoff = (single && state.anim.playing) ? state.anim.p * tMax : Infinity;

  rs.forEach((r) => {
    const color = colorOf(r.algo);
    const alpha = single ? 1 : 0.32;

    // 等待竖线只在单算法视图画：六个算法叠一起会变成一张密网
    if (single) {
      ctx.save();
      ctx.globalAlpha = 0.3;
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      r.records.forEach((rec) => {
        if (rec.start > cutoff) return;
        const px = x(rec.track);
        ctx.beginPath();
        ctx.moveTo(px, y(rec.at));
        ctx.lineTo(px, y(Math.min(rec.start, cutoff)));
        ctx.stroke();
      });
      ctx.restore();
    }

    // 磁头轨迹
    const pts = r.points.filter((p) => p.t <= cutoff);
    if (pts.length > 1) {
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = color;
      ctx.lineWidth = single ? 2 : 1.2;
      ctx.lineJoin = "round";
      ctx.beginPath();
      pts.forEach((p, i) => {
        const px = x(p.track), py = y(p.t);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      ctx.stroke();
      ctx.restore();
    }
  });

  // 单算法时标出最坏等待
  if (single) {
    const r = rs[0];
    const worst = r.records.reduce((a, b) => (b.wait > a.wait ? b : a), r.records[0]);
    if (worst) {
      const px = x(worst.track);
      ctx.save();
      ctx.strokeStyle = cssVar("--warn");
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(px, y(worst.at));
      ctx.lineTo(px, y(worst.start));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = cssVar("--warn");
      ctx.font = '10px "Cascadia Mono", Consolas, monospace';
      ctx.textAlign = worst.track > tracks * 0.7 ? "right" : "left";
      ctx.fillText(`最坏 ${fmt(worst.wait, 0)}ms`, px + (worst.track > tracks * 0.7 ? -6 : 6), y(worst.start) - 4);
      ctx.restore();
    }
  }

  renderLegendDyn(rs);
}

function renderLegendDyn(rs) {
  const box = $("#traceLegend");
  if (state.focus === "all") {
    box.innerHTML = rs.map((r) =>
      `<span style="color:${colorOf(r.algo)}"><i></i>${r.algo} · 最大 ${fmt(r.metrics.max_wait, 0)}ms</span>`).join("") +
      `<span>点单个算法可看每个请求的等待竖线</span>`;
  } else {
    const r = rs[0];
    box.innerHTML = `<span style="color:${colorOf(r.algo)}"><i></i>${r.algo}（${r.name}）</span>` +
      `<span>平均等待 ${fmt(r.metrics.avg_wait, 1)}ms · P95 ${fmt(r.metrics.p95_wait, 1)}ms · 最大 ${fmt(r.metrics.max_wait, 1)}ms</span>` +
      `<span>竖线长度 = 等待时间</span>`;
  }
}

/* ------------------------------------------------------------- 导出 */

function exportPng() {
  const canvas = $("#traceCanvas");
  canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `磁盘轨迹_${state.focus === "all" ? "全部" : state.focus}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }, "image/png");
}

function copyMd() {
  const text = state.data?.report_md || "";
  navigator.clipboard.writeText(text).then(() => {
    const btn = $("#btnCopyMd");
    const old = btn.textContent;
    btn.textContent = "已复制 ✓";
    setTimeout(() => { btn.textContent = old; }, 1400);
  });
}

function downloadCsv() {
  let rows;
  if (state.mode === "dynamic") {
    rows = [["算法", "名称", "完成", "总数", "平均等待", "P95等待", "最大等待", "平均响应", "完成用时", "吞吐", "公平性"]];
    state.data.results.forEach((r) => {
      const m = r.metrics;
      rows.push([r.algo, r.name, m.served, m.total, m.avg_wait, m.p95_wait, m.max_wait,
        m.avg_turn, m.makespan, m.throughput, m.fairness]);
    });
  } else {
    rows = [["算法", "名称", "总寻道", "平均寻道", "最大单次", "换向", "估算耗时ms",
      "平均响应ms", "最坏响应ms", "服务顺序"]];
    state.data.results.forEach((r) => {
      const m = r.metrics;
      rows.push([r.algo, r.name, m.total_seek, m.avg_seek, m.max_step, m.reversals,
        m.makespan_ms, m.avg_response_ms, m.max_response_ms, r.order.join(" ")]);
    });
  }
  const csv = "\ufeff" + rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
  download("磁盘调度指标.csv", csv, "text/csv");
}

function download(name, text, type) {
  const blob = new Blob([text], { type: type + ";charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ------------------------------------------------------------- 启动 */

init();
