const eventsList = document.querySelector("#eventsList");
const connection = document.querySelector("#connection");
const logPath = document.querySelector("#logPath");
const lastAsr = document.querySelector("#lastAsr");
const lastLlm = document.querySelector("#lastLlm");
const lastAction = document.querySelector("#lastAction");
const clearButton = document.querySelector("#clearButton");
const turnsList = document.querySelector("#turnsList");
const pipelineStatus = document.querySelector("#pipelineStatus");
const sessionStatus = document.querySelector("#sessionStatus");
const startPipelineButton = document.querySelector("#startPipelineButton");
const stopPipelineButton = document.querySelector("#stopPipelineButton");
const interruptPipelineButton = document.querySelector("#interruptPipelineButton");
const endSessionButton = document.querySelector("#endSessionButton");
const readinessList = document.querySelector("#readinessList");
const shadowStatus = document.querySelector("#shadowStatus");
const shadowComparisons = document.querySelector("#shadowComparisons");

const maxEvents = 240;
const turnItems = new Map();
let eventItems = [];
const seenEventKeys = new Set();
let pipelineBusy = false;
let currentPipelineState = "unknown";
let currentLogPath = "";

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

function resetMonitorData(nextLogPath = "") {
  eventItems = [];
  seenEventKeys.clear();
  turnItems.clear();
  eventsList.replaceChildren();
  turnsList.replaceChildren();
  lastAsr.textContent = "-";
  lastLlm.textContent = "-";
  lastAction.textContent = "-";
  renderShadowComparisons([], false);
  currentLogPath = nextLogPath;
  if (nextLogPath) logPath.textContent = nextLogPath;
}

function shadowDecisionLabel(value) {
  const labels = {
    CONTINUE_SPEAKING: "继续说话",
    END_OF_TURN: "轮次结束",
    TRUE_INTERRUPT: "真实打断",
    BACKCHANNEL: "附和",
    UNCERTAIN: "不确定",
  };
  return labels[value] || value || "-";
}

function renderShadowDetector(name, detector) {
  const item = document.createElement("div");
  item.className = "shadow-detector";
  const header = document.createElement("div");
  header.className = "shadow-detector-head";
  const label = document.createElement("strong");
  label.textContent = name === "baseline" ? "当前规则" : name;
  const latency = document.createElement("span");
  latency.textContent = `${Number(detector?.latency_ms || 0).toFixed(2)} ms`;
  header.append(label, latency);

  const decision = document.createElement("div");
  decision.className = "shadow-decision";
  decision.textContent = shadowDecisionLabel(detector?.decision);
  const detail = document.createElement("p");
  const confidence = Number(detector?.confidence || 0);
  detail.textContent = `置信度 ${confidence.toFixed(2)} · ${detector?.reason || "无说明"}`;
  item.append(header, decision, detail);
  return item;
}

function renderShadowComparisons(comparisons, enabled) {
  if (!shadowComparisons || !shadowStatus) return;
  shadowStatus.textContent = enabled ? "观察中" : "未启用";
  shadowStatus.className = `shadow-status ${enabled ? "enabled" : ""}`.trim();

  const rows = comparisons || [];
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "shadow-empty";
    empty.textContent = enabled ? "等待本轮观察数据" : "当前会话没有 Shadow 数据";
    shadowComparisons.replaceChildren(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const comparison of rows) {
    const row = document.createElement("article");
    row.className = `shadow-row ${comparison.agreement ? "agrees" : "differs"}`;
    const context = document.createElement("div");
    context.className = "shadow-context";
    const text = document.createElement("strong");
    text.textContent = comparison.text || "（无转写）";
    const state = document.createElement("span");
    state.textContent = comparison.agreement ? "一致" : "存在差异";
    context.append(text, state);

    const detectorGrid = document.createElement("div");
    detectorGrid.className = "shadow-detector-grid";
    for (const [name, detector] of Object.entries(comparison.detectors || {})) {
      detectorGrid.appendChild(renderShadowDetector(name, detector));
    }
    row.append(context, detectorGrid);
    fragment.appendChild(row);
  }
  shadowComparisons.replaceChildren(fragment);
}

async function refreshShadowComparisons() {
  try {
    const response = await fetch("/api/shadow?limit=8");
    const payload = await response.json();
    renderShadowComparisons(payload.comparisons || [], Boolean(payload.enabled));
  } catch (error) {
    renderShadowComparisons([], false);
  }
}

function switchLogIfNeeded(nextLogPath) {
  if (!nextLogPath) return false;
  if (currentLogPath && currentLogPath !== nextLogPath) {
    resetMonitorData(nextLogPath);
    return true;
  }
  currentLogPath = nextLogPath;
  logPath.textContent = nextLogPath;
  return false;
}

function setPipelineBusy(isBusy) {
  pipelineBusy = isBusy;
  startPipelineButton.disabled = isBusy;
  stopPipelineButton.disabled = isBusy;
  interruptPipelineButton.disabled = isBusy || currentPipelineState !== "running";
  endSessionButton.disabled = isBusy || currentPipelineState !== "running";
}

function updatePipelineStatus(payload) {
  const state = payload?.state || "unknown";
  currentPipelineState = state;
  pipelineStatus.textContent = `Pipeline: ${state}`;
  pipelineStatus.className = `status ${state === "running" ? "ok" : state === "partial" ? "partial" : state === "stopped" ? "" : "error"}`;
  interruptPipelineButton.disabled = state !== "running";
  endSessionButton.disabled = state !== "running";
  if (pipelineBusy) interruptPipelineButton.disabled = true;
  if (pipelineBusy) endSessionButton.disabled = true;
  renderReadiness(payload || {});
}

function setSessionStatus(label, className = "") {
  if (!sessionStatus) return;
  sessionStatus.textContent = `Session: ${label}`;
  sessionStatus.className = `status session-status ${className}`.trim();
}

function renderReadiness(payload) {
  if (!readinessList) return;
  const components = payload.components || fallbackReadinessFromServices(payload.services || {});
  const preferredOrder = [
    "surf-voice-runtime",
    "surf-llm-node",
    "surf-llm-audio-player",
    "robot_relay",
    "robot_mic",
  ];
  const entries = preferredOrder
    .filter((key) => components[key])
    .map((key) => [key, components[key]]);

  const fragment = document.createDocumentFragment();
  for (const [key, component] of entries) {
    const item = document.createElement("div");
    item.className = `readiness-item ${component.ready ? "ready" : "not-ready"}`;

    const main = document.createElement("div");
    main.className = "readiness-main";
    const label = document.createElement("strong");
    label.textContent = component.label || key;
    const state = document.createElement("span");
    state.textContent = component.ready ? "ready" : "not ready";
    main.append(label, state);

    const detail = document.createElement("p");
    const parts = [];
    if (component.endpoint) parts.push(component.endpoint);
    if (component.elapsed_ms !== "" && component.elapsed_ms !== undefined) parts.push(`${component.elapsed_ms} ms`);
    if (component.detail) parts.push(component.detail);
    if (!component.ready && component.hint) parts.push(component.hint);
    detail.textContent = parts.join("  ·  ");

    item.append(main, detail);
    fragment.appendChild(item);
  }
  readinessList.replaceChildren(fragment);
}

function fallbackReadinessFromServices(services) {
  const labels = {
    "surf-voice-runtime": "语音识别",
    "surf-llm-node": "LLM 对话节点",
    "surf-llm-audio-player": "TTS/灯光/动作播放器",
  };
  const components = {};
  for (const [key, service] of Object.entries(services)) {
    components[key] = {
      label: labels[key] || key,
      ready: Boolean(service.active),
      state: service.state || "unknown",
      hint: service.active ? "" : `本机服务未运行：${key}`,
    };
  }
  components.robot_relay = {
    label: "机器人中转服务",
    ready: false,
    state: "unknown",
    hint: "当前 monitor 后端未返回 relay 检查结果，请重启 UI monitor。",
  };
  components.robot_mic = {
    label: "机器人外置麦克风推流",
    ready: false,
    state: "unknown",
    hint: "当前 monitor 后端未返回外置麦克风检查结果，请重启 UI monitor。",
  };
  return components;
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

async function runPipelineInterrupt() {
  setPipelineBusy(true);
  setSessionStatus("正在打断", "partial");
  try {
    const response = await fetch("/api/pipeline/interrupt", { method: "POST" });
    const payload = await response.json();
    const listeningOpened = Boolean(payload.listening_opened);
    const succeeded = Boolean(payload.ok || (payload.partial && listeningOpened));
    if (payload.partial) {
      setSessionStatus(listeningOpened ? "部分完成，正在听取" : "打断未完成", "partial");
    } else if (succeeded) {
      setSessionStatus("已打断，正在听取", "ok");
    } else {
      setSessionStatus("打断失败", "partial");
    }
    await loadSnapshot();
  } catch (error) {
    addEvent({ kind: "system", title: "ERROR", message: `打断失败：${String(error)}` });
    setSessionStatus("打断失败", "partial");
  } finally {
    await refreshPipelineStatus();
    setPipelineBusy(false);
  }
}

async function runPipelineEndSession() {
  setPipelineBusy(true);
  setSessionStatus("正在关闭", "partial");
  try {
    const response = await fetch("/api/pipeline/end-session", { method: "POST" });
    const payload = await response.json();
    if (payload.ok) {
      setSessionStatus("正在播放结束语", "partial");
    } else if (payload.partial) {
      setSessionStatus("关闭中，机器人复位未完成", "partial");
    } else {
      setSessionStatus("关闭失败", "partial");
    }
    await loadSnapshot();
  } catch (error) {
    addEvent({ kind: "system", title: "ERROR", message: `关闭会话失败：${String(error)}` });
    setSessionStatus("关闭失败", "partial");
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
  updateSessionStatus(event);
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

function updateSessionStatus(event) {
  const stage = event.stage || event.raw?.stage || "";
  if (event.kind === "wake" || stage === "wake_listen_open") {
    setSessionStatus("等待问题", "partial");
  } else if (stage === "asr_started" || stage === "followup_asr_started") {
    setSessionStatus("录音识别中", "partial");
  } else if (event.kind === "asr") {
    setSessionStatus("LLM 处理中", "partial");
  } else if (event.kind === "llm" || stage === "tts_ready") {
    setSessionStatus("TTS 生成/待播放", "partial");
  } else if (stage === "tts_play_started") {
    setSessionStatus("机器人播放中", "partial");
  } else if (stage === "tts_play_finished") {
    setSessionStatus("等待追问", "ok");
  } else if (stage === "followup_open") {
    setSessionStatus("等待追问", "ok");
  } else if (stage === "manual_interrupt") {
    if (event.raw?.listening_opened) {
      setSessionStatus(event.raw?.partial ? "部分完成，正在听取" : "已打断，正在听取", event.raw?.partial ? "partial" : "ok");
    } else {
      setSessionStatus("打断未完成", "partial");
    }
  } else if (stage === "manual_interrupt_failed") {
    setSessionStatus("打断失败", "partial");
  } else if (stage === "followup_closed" || stage === "terminate_command" || stage === "session_end") {
    setSessionStatus("已关闭", "");
  } else if (stage === "wake_listen_closed") {
    setSessionStatus("待唤醒", "");
  }
}

function addEvent(event) {
  switchLogIfNeeded(event.log_path);
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
  switchLogIfNeeded(payload.log_path);
  renderTurnSummaries(payload.turn_summaries);
  for (const event of payload.events || []) addEvent(event);
}

async function refreshTurns() {
  try {
    const response = await fetch("/api/turns?limit=30");
    const payload = await response.json();
    switchLogIfNeeded(payload.log_path);
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
  resetMonitorData(currentLogPath);
});

startPipelineButton.addEventListener("click", () => runPipelineAction("start"));
stopPipelineButton.addEventListener("click", () => runPipelineAction("stop"));
interruptPipelineButton.addEventListener("click", runPipelineInterrupt);
endSessionButton.addEventListener("click", runPipelineEndSession);

loadSnapshot()
  .catch((error) => addEvent({ kind: "system", title: "ERROR", message: String(error) }))
  .finally(() => {
    refreshPipelineStatus();
    refreshShadowComparisons();
    connectEvents();
    setInterval(refreshTurns, 2500);
    setInterval(refreshShadowComparisons, 2500);
    setInterval(refreshPipelineStatus, 5000);
  });
