// ============================================================
// XJTLU RAG 前端交互逻辑
// ============================================================

const form = document.querySelector("#form");
const input = document.querySelector("#message");
const messages = document.querySelector("#messages");
const connectionStatus = document.querySelector("#connectionStatus");
const clearBtn = document.querySelector("#clearBtn");
const sidebar = document.querySelector("#sidebar");
const openSidebarBtn = document.querySelector("#openSidebar");
const closeSidebarBtn = document.querySelector("#closeSidebar");
const reloadConfigBtn = document.querySelector("#reloadConfig");

// ============================================================
// 状态管理
// ============================================================
let isConnected = false;
let conversationHistory = [];

// ============================================================
// 工具函数
// ============================================================
function addBubble(role, text, sources = [], metadata = {}) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;

  // 消息内容
  const content = document.createElement("div");
  content.className = "bubble-content";
  content.textContent = text;
  bubble.appendChild(content);

  // 来源引用
  if (sources && sources.length > 0) {
    const sourceBox = document.createElement("div");
    sourceBox.className = "sources";
    sourceBox.innerHTML = sources
      .map((source, index) => {
        const title = source.title || `来源 ${index + 1}`;
        const url = source.url && source.url !== "None" ? source.url : "#";
        const score = source.score ? ` (${(source.score * 100).toFixed(1)}%)` : "";
        return `[${index + 1}] <a href="${url}" target="_blank" rel="noreferrer">${title}</a>${score}`;
      })
      .join("<br />");
    bubble.appendChild(sourceBox);
  }

  // 时间戳
  const timestamp = document.createElement("div");
  timestamp.className = "bubble-time";
  timestamp.textContent = new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
  bubble.appendChild(timestamp);

  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;

  // 保存对话历史
  conversationHistory.push({ role, text, sources, metadata });
  return bubble;
}

function addErrorBubble(text) {
  const bubble = document.createElement("div");
  bubble.className = "bubble error";
  bubble.innerHTML = `<span class="error-icon">⚠</span> ${text}`;
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function updateConnectionStatus(status, text) {
  const dot = connectionStatus.querySelector(".status-dot");
  const textEl = connectionStatus.querySelector(".status-text");

  isConnected = status === "connected";
  dot.className = `status-dot ${status}`;
  textEl.textContent = text;
}

function updateSidebar(data) {
  if (data.status) {
    document.getElementById("configStatus").textContent = data.status === "ok" ? "✓ 正常" : "✗ 异常";
  }
  if (data.chat_model) {
    document.getElementById("configChatModel").textContent = data.chat_model;
  }
  if (data.embed_model) {
    document.getElementById("configEmbedModel").textContent = data.embed_model;
  }
}

// ============================================================
// 事件处理
// ============================================================
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  // 显示用户消息
  addBubble("user", text);
  input.value = "";
  form.querySelector(".btn-send").disabled = true;

  // 添加加载状态
  const loadingBubble = addBubble("assistant", "思考中...");
  const loadingDots = ["思考中.", "思考中..", "思考中..."];
  let dotIndex = 0;
  const loadingInterval = setInterval(() => {
    dotIndex = (dotIndex + 1) % loadingDots.length;
    loadingBubble.querySelector(".bubble-content").textContent = loadingDots[dotIndex];
  }, 500);

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
      }),
    });

    clearInterval(loadingInterval);

    if (!response.ok) {
      throw new Error(`服务器错误: ${response.status}`);
    }

    const data = await response.json();

    // 移除加载消息
    loadingBubble.remove();

    // 显示助手回复
    addBubble("assistant", data.answer || "没有返回内容。", data.sources || []);
  } catch (error) {
    clearInterval(loadingInterval);
    loadingBubble.remove();
    addErrorBubble(`请求失败: ${error.message}`);
    console.error("Chat error:", error);
  } finally {
    form.querySelector(".btn-send").disabled = false;
    input.focus();
  }
});

// 清空对话
clearBtn.addEventListener("click", () => {
  if (confirm("确定要清空当前对话吗？")) {
    messages.innerHTML = "";
    conversationHistory = [];
    addBubble(
      "assistant",
      "对话已清空。我可以基于XJTLU知识库回答问题，也会记住你明确告诉我的身份偏好。"
    );
  }
});

// 侧边栏
openSidebarBtn.addEventListener("click", () => {
  sidebar.classList.add("open");
  loadConfig();
});

closeSidebarBtn.addEventListener("click", () => {
  sidebar.classList.remove("open");
});

reloadConfigBtn.addEventListener("click", loadConfig);


// ============================================================
// API 调用
// ============================================================
async function loadConfig() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    updateSidebar(data);
    updateConnectionStatus("connected", "已连接");
  } catch (error) {
    updateConnectionStatus("disconnected", "连接失败");
    console.error("Config load error:", error);
  }
}


// ============================================================
// 初始化
// ============================================================
async function init() {
  // 添加欢迎消息
  addBubble(
    "assistant",
    "你好！我是 XJTLU 智能助手。\n\n我可以帮助你：\n• 了解西交利物浦大学的专业、招生、学院等信息\n• 记住你的身份偏好和对话上下文\n• 切换不同身份（招生顾问、学术导师、校园助手）\n\n请输入你的问题，我会给出准确详细的回答。"
  );

  // 加载配置
  await loadConfig();
}

// 页面加载时初始化
document.addEventListener("DOMContentLoaded", init);
