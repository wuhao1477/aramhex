"""网页端的页面（单文件，不加载外部资源）。__TOKEN__ 由 web.py 在返回页面时替换。"""

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AramHex 网页</title>
<style>
 body{font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f5f5f7;color:#222}
 main{max-width:640px;margin:0 auto;padding:16px}
 .card{background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:12px;box-shadow:0 1px 2px #0001}
 h1{font-size:18px;margin:4px 0 12px}
 h2{font-size:14px;color:#666;margin:0 0 8px;font-weight:600}
 .aug{display:flex;gap:8px;flex-wrap:wrap}
 .aug span{background:#eef;border-radius:8px;padding:6px 10px}
 .aug span.pick{background:#cfe9d4;font-weight:600}
 button{font:inherit;padding:8px 14px;border:0;border-radius:8px;background:#2b6cb0;color:#fff;margin:4px 6px 4px 0}
 button:disabled{background:#aaa}
 select{font:inherit;padding:6px}
 #log{white-space:pre-wrap;max-height:260px;overflow:auto;font-size:14px}
 .muted{color:#888;font-size:13px}
 input[type=text]{font:inherit;width:70%;padding:8px}
</style></head>
<body><main>
<h1>AramHex 网页</h1>
<div class="card">
 <h2>当前状态</h2>
 <div id="status">读取中…</div>
 <div class="aug" id="augs"></div>
</div>
<div class="card">
 <h2>第三方 AI 分析</h2>
 <div id="ai" class="muted">—</div>
 <div style="margin-top:8px">
  <button id="refresh">刷新 AI 分析</button>
  <label class="muted">模式
   <select id="mode">
    <option value="auto">自动</option>
    <option value="manual">手动</option>
    <option value="off">关闭</option>
   </select>
  </label>
 </div>
</div>
<div class="card">
 <h2>问 AI</h2>
 <div id="log" class="muted">还没有对话</div>
 <div style="margin-top:8px">
  <input type="text" id="msg" placeholder="问点什么，例如：这三个里哪个更适合我的阵容">
  <button id="send">发送</button>
 </div>
</div>
</main>
<script>
const TOKEN = "__TOKEN__";
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function post(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json", "X-Token": TOKEN},
                               body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}
const PHASE = {ingame: "对局中", client: "客户端", null: "未检测到游戏"};
let modeSet = false;
async function tick() {
  try {
    const s = await (await fetch("/api/state", {cache: "no-store"})).json();
    $("status").textContent = (PHASE[s.phase] || s.phase || "—") + (s.hero ? "｜英雄：" + s.hero : "");
    const pick = s.ai && s.ai.result ? s.ai.result.pick : -1;
    $("augs").innerHTML = s.augments.map((a, i) => `<span class="${i === pick ? "pick" : ""}">${esc(a.name)}</span>`).join("")
      || '<span class="muted">没有在选海克斯</span>';
    const ai = s.ai || {};
    const st = {idle: "等待三选一", waiting: "等待三选一", running: "分析中…", done: "", error: "出错：", unconfigured: "未配置"}[ai.status] ?? "";
    let text = st;
    if (ai.status === "done" && ai.result) text = `推荐第 ${ai.result.pick + 1} 张：${ai.result.reason || ""}`;
    if (ai.status === "error") text = "出错：" + (ai.error || "");
    if (ai.status === "unconfigured") text = "第三方 AI 未配置：请在电脑的 .env 里填写 AI_BASE_URL、AI_API_KEY、AI_MODEL";
    $("ai").textContent = text || "—";
    $("refresh").disabled = ai.mode === "off" || !ai.configured || !s.augments.length || s.augments.some(a => !a.id);
    if (!modeSet && ai.mode) { $("mode").value = ai.mode; modeSet = true; }
  } catch (e) { $("status").textContent = "连不上电脑上的助手：" + e.message; }
}
$("refresh").onclick = () => post("/api/ai/refresh").then(tick).catch(e => alert(e.message));
$("mode").onchange = () => post("/api/ai/mode", {mode: $("mode").value}).then(tick).catch(e => alert(e.message));
async function send() {
  const m = $("msg").value.trim();
  if (!m) return;
  $("send").disabled = true;
  try {
    const r = await post("/api/chat", {message: m});
    $("msg").value = "";
    $("log").dataset.text = ($("log").dataset.text || "") + `你：${m}\\nAI：${r.reply}\\n\\n`;
    $("log").textContent = $("log").dataset.text;
    $("log").className = "";
  } catch (e) { alert(e.message); }
  $("send").disabled = false;
}
$("send").onclick = send;
$("msg").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
tick();
setInterval(tick, 1000);
</script></body></html>
"""
