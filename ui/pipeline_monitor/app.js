const eventsList = document.querySelector("#eventsList");
const connection = document.querySelector("#connection");
const logPath = document.querySelector("#logPath");
const lastAsr = document.querySelector("#lastAsr");
const lastLlm = document.querySelector("#lastLlm");
const lastAction = document.querySelector("#lastAction");
const clearButton = document.querySelector("#clearButton");

const maxEvents = 240;

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

function updateSummary(event) {
  if (event.kind === "asr") lastAsr.textContent = event.message || "-";
  if (event.kind === "llm") lastLlm.textContent = event.message || "-";
  if (event.kind === "action") lastAction.textContent = event.message || "-";
  if (event.log_path) logPath.textContent = event.log_path;
}

function addEvent(event) {
  updateSummary(event);

  const item = document.createElement("li");
  item.className = `event ${event.kind || "system"}`;

  const time = document.createElement("time");
  time.textContent = formatTime(event.time);

  const badge = document.createElement("div");
  badge.className = "badge";
  badge.textContent = event.title || event.stage || "EVENT";

  const body = document.createElement("div");
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
  eventsList.appendChild(item);

  while (eventsList.children.length > maxEvents) {
    eventsList.firstElementChild.remove();
  }
  eventsList.scrollTop = eventsList.scrollHeight;
}

async function loadSnapshot() {
  const response = await fetch("/api/events?limit=80");
  const payload = await response.json();
  if (payload.log_path) logPath.textContent = payload.log_path;
  for (const event of payload.events || []) addEvent(event);
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
  eventsList.innerHTML = "";
});

loadSnapshot()
  .catch((error) => addEvent({ kind: "system", title: "ERROR", message: String(error) }))
  .finally(connectEvents);
