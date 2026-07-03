const eventsList = document.querySelector("#eventsList");
const connection = document.querySelector("#connection");
const logPath = document.querySelector("#logPath");
const lastAsr = document.querySelector("#lastAsr");
const lastLlm = document.querySelector("#lastLlm");
const lastAction = document.querySelector("#lastAction");
const clearButton = document.querySelector("#clearButton");
const turnsList = document.querySelector("#turnsList");
const pipelineStatus = document.querySelector("#pipelineStatus");
const startPipelineButton = document.querySelector("#startPipelineButton");
const stopPipelineButton = document.querySelector("#stopPipelineButton");

const maxEvents = 240;
const turnItems = new Map();
let eventItems = [];
const seenEventKeys = new Set();

function formatTime(value) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(11, 19) || "--:--:--";
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function formatMeta(meta) {
  if (!meta || Object.keys(meta).length === 0) return "";
  return Object.entries(meta)
    .map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`)
    .join("  ");
}

function formatDuration(ms) {
  if (ms === null || ms === undefined || ms === "") return "-";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function latencyClass(ms) {
  if (ms === null || ms === undefined || ms === "") return "";
  if (ms < 2000) return "fast";
  if (ms < 6000) return "medium";
  return "slow";
}

function renderLatency(label, value) {
  const item = document.createElement("div");
  item.className = `latency ${latencyClass(value)}`;
  const name = document.createElement("span");
  name.textContent = label;
  const number = document.createElement("strong");
  number.textContent = formatDuration(value);
  item.append(name, number);
  return item;
}

function createTurnSummaryElement(turn, displayIndex) {
  const item = document.createElement("article");
  item.className = "turn";
  if (!turn.reply) item.classList.add("incomplete");

  const main = document.createElement("div");
  main.className = "turn-main";
  const index = document.createElement("div");
  index.className = "turn-index";
  index.textContent = `Turn ${turn.turn_index || displayIndex}`;

  const text = document.createElement("div");
  text.className = "turn-text";
  const asr = document.createElement("div");
  asr.innerHTML = `<strong>用户：</strong>${turn.asr_text || "-"}`;
  const reply = document.createElement("div");
  reply.innerHTML = `<strong>小浦：</strong>${turn.reply || "-"}`;
  const action = document.createElement("div");
  const actionLabel = turn.action?.label || "无动作";
  const executed = turn.action?.executed;
  action.innerHTML = `<strong>动作：</strong>${actionLabel} ${executed === "" || executed === undefined ? "" : `executed=${executed}`}`;
  text.append(asr, reply, action);
  main.append(index, text);

  const latency = turn.latency_ms || {};
  const grid = document.createElement("div");
  grid.className = "latency-grid";
  grid.append(
    renderLatency("ASR", latency.asr_record),
    renderLatency("LLM", latency.asr_to_llm_reply),
    renderLatency("TTS", latency.llm_to_tts_ready),
    renderLatency("播放", latency.tts_play),
    renderLatency("动作", latency.action_after_tts),
    renderLatency("总计", latency.turn_total),
  );

  item.append(main, grid);
  return item;
}

function turnSortValue(turn) {
  const times = Object.values(turn.stage_times || {}).filter((value) => typeof value === "number");
  return times.length ? Math.max(...times) : Number(turn.turn_index || 0);
}

function renderTurnSummaries(turns) {
  for (const turn of turns || []) {
    if (turn?.turn_id) turnItems.set(turn.turn_id, turn);
  }

  const completeTurns = Array.from(turnItems.values())
    .filter((turn) => turn.reply)
    .sort((a, b) => turnSortValue(b) - turnSortValue(a))
    .slice(0, 20);

  const fragment = document.createDocumentFragment();
  completeTurns.forEach((turn, index) => {
    fragment.appendChild(createTurnSummaryElement(turn, index + 1));
  });

  turnsList.replaceChildren(fragment);
}

function eventKey(event) {
  return [
    event.time || "",
    event.kind || "",
    event.title || "",
    event.message || "",
    JSON.stringify(event.meta || {}),
  ].join("|");
}

function eventSortValue(event) {
  const timestamp = Date.parse(event.time || "");
  if (!Number.isNaN(timestamp)) return timestamp;
  if (event.elapsed_sec !== "" && event.elapsed_sec !== undefined && event.elapsed_sec !== null) {
    const elapsed = Number(event.elapsed_sec);
    if (!Number.isNaN(elapsed)) return elapsed * 1000;
  }
  return 0;
}

function renderEventItem(event) {
  const item = document.createElement("li");
  item.className = `event ${event.kind || "system"}`;

  const time = document.createElement("time");
  time.textContent = formatTime(event.time);

  const badge = document.createElement("div");
  badge.className = "badge";
  badge.textContent = event.title || event.stage || "EVENT";

  const body = document.createElement("div");
  body.className = "event-body";
  const message = document.createElement("div");
  message.className = "message";
  message.textContent = event.message || "";
  body.appendChild(message);

  const metaText = formatMeta(event.meta);
  if (metaText) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaText;
    body.appendChild(meta);
  }

  item.append(time, badge, body);
  return item;
}

function renderEvents() {
  eventItems.sort((a, b) => eventSortValue(b) - eventSortValue(a));
  eventItems = eventItems.slice(0, maxEvents);

  const fragment = document.createDocumentFragment();
  for (const event of eventItems) {
    fragment.appendChild(renderEventItem(event));
  }

  eventsList.replaceChildren(fragment);
  eventsList.scrollTop = 0;
}

function setPipelineBusy(isBusy) {
  startPipelineButton.disabled = isBusy;
  stopPipelineButton.disabled = isBusy;
}

function updatePipelineStatus(payload) {
  const state = payload?.state || "unknown";
  pipelineStatus.textContent = `Pipeline: ${state}`;
  pipelineStatus.className = `status ${state === "running" ? "ok" : state === "partial" ? "partial" : state === "stopped" ? "" : "error"}`;
}

async function refreshPipelineStatus() {
  try {
    const response = await fetch("/api/pipeline/status");
    updatePipelineStatus(await response.json());
  } catch (error) {
    updatePipelineStatus({ state: "error" });
  }
}

async function runPipelineAction(action) {
  setPipelineBusy(true);
  addEvent({ kind: "system", title: "PIPELINE", message: `${action} requested` });
  try {
    const response = await fetch(`/api/pipeline/${action}`, { method: "POST" });
    const payload = await response.json();
    addEvent({
      kind: payload.ok ? "state" : "system",
      title: payload.ok ? "PIPELINE" : "ERROR",
      message: payload.ok ? `${action} ok` : `${action} failed`,
      meta: {
        returncode: payload.returncode,
        output: compactCommandOutput(payload.stdout),
        error: compactCommandOutput(payload.stderr || payload.error),
      },
    });
  } catch (error) {
    addEvent({ kind: "system", title: "ERROR", message: String(error) });
  } finally {
    await refreshPipelineStatus();
    setPipelineBusy(false);
  }
}

function compactCommandOutput(value) {
  if (!value) return "";
  return String(value).split(/\r?\n/).filter(Boolean).slice(-3).join(" | ");
}

function updateSummary(event) {
  if (event.kind === "asr") lastAsr.textContent = event.message || "-";
  if (event.kind === "llm") lastLlm.textContent = event.message || "-";
  if (event.kind === "action") {
    const actionId = Number(event.raw?.action_id ?? -1);
    const executed = event.raw?.executed;
    if (actionId >= 0 || executed === true) {
      lastAction.textContent = event.message || "-";
    }
  }
  if (event.log_path) logPath.textContent = event.log_path;
}

function addEvent(event) {
  updateSummary(event);

  const key = eventKey(event);
  if (!seenEventKeys.has(key)) {
    seenEventKeys.add(key);
    eventItems.push(event);
  }
  renderEvents();
}

async function loadSnapshot() {
  const response = await fetch("/api/events?limit=80");
  const payload = await response.json();
  if (payload.log_path) logPath.textContent = payload.log_path;
  renderTurnSummaries(payload.turn_summaries);
  for (const event of payload.events || []) addEvent(event);
}

async function refreshTurns() {
  try {
    const response = await fetch("/api/turns?limit=30");
    const payload = await response.json();
    renderTurnSummaries(payload.turn_summaries);
  } catch (error) {
    addEvent({ kind: "system", title: "ERROR", message: String(error) });
  }
}

function connectEvents() {
  const source = new EventSource("/events");
  source.onopen = () => {
    connection.textContent = "Live";
    connection.className = "status ok";
  };
  source.onerror = () => {
    connection.textContent = "Reconnecting";
    connection.className = "status error";
  };
  source.onmessage = (message) => {
    try {
      addEvent(JSON.parse(message.data));
    } catch (error) {
      addEvent({ kind: "system", title: "ERROR", message: String(error) });
    }
  };
}

clearButton.addEventListener("click", () => {
  eventItems = [];
  seenEventKeys.clear();
  eventsList.replaceChildren();
});

startPipelineButton.addEventListener("click", () => runPipelineAction("start"));
stopPipelineButton.addEventListener("click", () => runPipelineAction("stop"));

loadSnapshot()
  .catch((error) => addEvent({ kind: "system", title: "ERROR", message: String(error) }))
  .finally(() => {
    refreshPipelineStatus();
    connectEvents();
    setInterval(refreshTurns, 2500);
    setInterval(refreshPipelineStatus, 5000);
  });
