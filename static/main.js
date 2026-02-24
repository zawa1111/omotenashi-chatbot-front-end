// ================================
// 背景：3種類×3枚（合計9枚）ランダム配置＋パララックス
// ================================

const MARKS = [
  {
    src: "/static/marks/omotenashi_mark_blue.png",
    count: 4,
    baseOpacity: 0.60,
    k: 12,
    sizeMin: 390,
    sizeMax: 410
  },
  {
    src: "/static/marks/omotenashi_mark_gold.png",
    count: 4,
    baseOpacity: 0.55,
    k: 20,
    sizeMin: 350,
    sizeMax: 390
  },
  {
    src: "/static/marks/omotenashi_mark_purple.png",
    count: 4,
    baseOpacity: 0.70,
    k: 28,
    sizeMin: 410,
    sizeMax: 470
  },
];


const bgLayers = [];
let tx = 0, ty = 0, cx = 0, cy = 0;

function rand(min, max) {
  return Math.random() * (max - min) + min;
}

function initParallaxMarks() {
  const parallax = document.querySelector(".parallax");
  if (!parallax) {
    console.warn("parallax not found");
    return;
  }

  // 既存を消して再生成
  parallax.innerHTML = "";
  bgLayers.length = 0;

  for (const mark of MARKS) {
    for (let i = 0; i < mark.count; i++) {
      const el = document.createElement("div");
      el.className = "layer";
      el.style.backgroundImage = `url("${mark.src}")`;

      // ✅ ランダム配置（少しはみ出してOK）
      const x = rand(-10, 90);
      const y = rand(-10, 90);
      el.style.left = x + "vw";
      el.style.top  = y + "vh";

      // ✅ ランダムサイズ
      const size = rand(220, 360);
      el.style.width  = size + "px";
      el.style.height = size + "px";

      // ✅ ランダム回転
      el.style.rotate = rand(-18, 18) + "deg";

      // ✅ 透け具合（少し揺らして自然に）
      el.style.opacity = mark.baseOpacity * rand(0.85, 1.15);

      parallax.appendChild(el);
      bgLayers.push({ el, k: mark.k });
    }
  }
}

window.addEventListener("mousemove", (e) => {
  tx = e.clientX / window.innerWidth - 0.5;
  ty = e.clientY / window.innerHeight - 0.5;
});

function tickParallax() {
  let t = 0;

function tickParallax() {
  t += 0.01;

  cx += (tx - cx) * 0.08;
  cy += (ty - cy) * 0.08;

  bgLayers.forEach(({ el, k }, i) => {
    const breathe = Math.sin(t + i) * 6; // 呼吸量
    el.style.transform =
      `translate(${cx * k}px, ${cy * k}px) scale(${1 + breathe / 300})`;
  });

  requestAnimationFrame(tickParallax);
}

}

window.addEventListener("DOMContentLoaded", () => {
  initParallaxMarks();
  tickParallax();
});


function tickParallax() {
  cx += (tx - cx) * 0.08;
  cy += (ty - cy) * 0.08;

  bgLayers.forEach(({ el, k }) => {
    el.style.transform = `translate(${cx * k}px, ${cy * k}px)`;
  });

  requestAnimationFrame(tickParallax);
}

// ===== チャット =====
const input = document.getElementById("input");
const log = document.getElementById("log");
const sendBtn = document.getElementById("send");

let es = null;

function clearStream() {
  if (es) { es.close(); es = null; }
}

function escapeHtml(s) {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatReply(text) {
  if (!text) return "";
  const lines = text.split("\n");
  let html = "";

  for (const line of lines) {
    const t = line.trim();
    if (!t) { html += `<div class="sp"></div>`; continue; }

    if (t.length < 22 && /とは|特徴|メリット|種類|対象|概要|ポイント/.test(t)) {
      html += `<div class="heading">${escapeHtml(t)}</div>`;
      continue;
    }
    if (t.startsWith("・")) {
      html += `<div class="item">${escapeHtml(t)}</div>`;
      continue;
    }
    if (/^https?:\/\//.test(t)) {
      const safe = escapeHtml(t);
      html += `<div class="url"><a href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a></div>`;
      continue;
    }
    html += `<div class="p">${escapeHtml(t)}</div>`;
  }
  return html;
}

function appendMessage(role, innerHtml) {
  const row = document.createElement("div");
  row.className = `m ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = innerHtml;

  row.appendChild(bubble);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

async function sendMessage() {
  const text = input?.value?.trim();
  if (!text || !log) return;

  clearStream();
  input.value = "";

  appendMessage("user", `<div class="p">${escapeHtml(text)}</div>`);
  const aiBubble = appendMessage("assistant", `<span class="thinking">考え中…</span>`);

  let buffer = "";
  const url = `/chat_stream?text=${encodeURIComponent(text)}`;
  es = new EventSource(url);

  es.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }

    if (data.type === "token") {
      buffer += data.t;
      aiBubble.innerHTML = formatReply(buffer);
      log.scrollTop = log.scrollHeight;
    }
    if (data.type === "error") {
      aiBubble.innerHTML = `<div class="p">${escapeHtml(data.msg)}</div>`;
      log.scrollTop = log.scrollHeight;
    }
  };

  es.addEventListener("end", () => clearStream());

  es.onerror = () => {
    clearStream();
    if (!buffer) aiBubble.innerHTML = `<div class="p">接続に失敗しました（/chat_stream）</div>`;
  };
}

window.addEventListener("DOMContentLoaded", () => {
  initParallaxMarks();
  tickParallax();

  input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendMessage();
  });
  sendBtn?.addEventListener("click", sendMessage);
});
