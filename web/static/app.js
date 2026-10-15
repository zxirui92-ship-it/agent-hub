/* Agent Hub 控制台前端逻辑。
 * 只调用 /api/* 薄层；不重写后端契约，状态与错误体原样渲染。 */
(function () {
  "use strict";

  const state = { sessionId: null, mode: null, capabilities: [], examples: {} };

  const $ = (sel) => document.querySelector(sel);
  const transcript = $("#transcript");
  const emptyState = $("#emptyState");
  const moduleViews = new Map();
  let activeRequests = 0;
  function requestStarted() { activeRequests++; updateSessionButtons(); }
  function requestFinished() { activeRequests = Math.max(0, activeRequests-1); updateSessionButtons(); }
  function updateSessionButtons() { $('#btnNew').disabled = $('#btnReset').disabled = activeRequests > 0; }
  const MODULE_UI = {
    'm1.faq_chat': ['智能客服', '解答政策与售后问题，支持多轮追问。'],
    'm2.order_tracking': ['订单追踪', '查询订单状态、金额和物流动态。'],
    'm3.weekly_report': ['经营周报', '整理经营数据，发现变化与关键问题。'],
    'm4.capability_gateway': ['创作与搜索', '联网搜索、知识问答、代码与图片生成。'],
    'm5.promotion_plan': ['营销策划', '结合数据和预算，协作制定活动方案。'],
    'm6.data_fusion': ['数据融合', '汇总订单、行为和营销的同口径数据。'],
    'm7.refund_approval': ['退款审核', '核对订单与退款金额，处理审批流程。'],
  };
  const FIELD_LABELS = {question:'你的问题',query:'任务描述',order_id:'订单编号',week:'统计周次',
    refund_amount:'退款金额',budget_amount:'活动预算',reason:'退款原因',goal:'活动目标',
    fused_data:'本周经营数据',previous_fused_data:'上周经营数据',revenue_amount:'成交金额',
    order_count:'订单数量',conversion_rate:'转化率',anomaly:'数据说明',report_markdown:'参考周报',
    session_id:'会话编号',sources:'资料来源',customer_id:'客户编号'};
  const moduleName = id => MODULE_UI[id]?.[0] || state.capabilities.find(c=>c.capability_id === id)?.name || id;

  const SCENARIOS = [
    { tag: "客服", text: "小家电保修几年？请说明不同条目差异。", cap: "m1.faq_chat" },
    { tag: "订单", text: "查询订单 2025101234 的物流。", cap: "m2.order_tracking" },
    { tag: "经营", text: "分别融合 2025-W41 和 2025-W40 数据，生成 W41 环比周报，再制定下周预算 10000 元的大促方案。", cap: "m3.weekly_report" },
    { tag: "退款", text: "查询订单 2025100004 并申请整单退款。", cap: "m7.refund_approval" },
    { tag: "网关", text: "查找今天的电商新闻并给出来源。", cap: "m4.capability_gateway" },
  ];

  /* ---------- 工具 ---------- */
  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // 极简 Markdown -> HTML（先转义，再处理少量语法，避免 XSS）
  function miniMarkdown(md) {
    if (!md) return "";
    const esc = escapeHtml(md);
    const lines = esc.split(/\r?\n/);
    let html = "", inCode = false, codeBuf = [];
    for (const line of lines) {
      if (/^```/.test(line.trim())) {
        if (inCode) { html += `<pre class="code">${codeBuf.join("\n")}</pre>`; codeBuf = []; inCode = false; }
        else { inCode = true; }
        continue;
      }
      if (inCode) { codeBuf.push(line); continue; }
      let t = line
        .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
        .replace(/^###\s+(.*)$/g, "<h4>$1</h4>")
        .replace(/^##\s+(.*)$/g, "<h3>$1</h3>")
        .replace(/^#\s+(.*)$/g, "<h2>$1</h2>")
        .replace(/^[-*]\s+(.*)$/g, "<li>$1</li>");
      if (/^<(h[2-4]|li)>/.test(t)) { html += t; }
      else if (t.trim() === "") { html += ""; }
      else { html += `<p>${t}</p>`; }
    }
    if (inCode) html += `<pre class="code">${codeBuf.join("\n")}</pre>`;
    return html;
  }

  function moneyYuan(amount) {
    if (typeof amount !== "number") return escapeHtml(amount);
    const yuan = amount.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `<span class="money">${yuan} 元</span>`;
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(t._timer);
    t._timer = setTimeout(() => (t.hidden = true), 2600);
  }

  async function api(path, method, body) {
    const res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.error?.message || `请求失败 (${res.status})`);
    return data;
  }

  /* ---------- 初始化 ---------- */
  async function init() {
    try {
      const s = await api("/api/session", "POST", {});
      state.sessionId = s.session_id;
      state.mode = s.mode;
      $("#sessionId").textContent = s.session_id;
      const badge = $("#modeBadge");
      badge.textContent = s.mode === "real" ? "真实模式" : "离线演示";
      badge.className = "badge " + (s.mode === "real" ? "badge-real" : "badge-offline");
    } catch (e) {
      toast("无法创建会话：" + e.message);
      $('#connectionError').hidden = false;
      $('#modeBadge').textContent = '连接失败';
    }
    await loadCapabilities();
    renderScenarios();
  }

  function renderScenarios() {
    const box1 = $("#scenarioList");   // 对话编排：填入输入框
    const box2 = $("#scenarioList2");  // 模块视图：跳到对应模块并带入示例
    if (box1) {
      box1.innerHTML = "";
      SCENARIOS.forEach((sc) => box1.appendChild(scenarioBtn(sc, "orchestrate")));
    }
    if (box2) {
      box2.innerHTML = "";
      SCENARIOS.forEach((sc) => box2.appendChild(scenarioBtn(sc, "module")));
    }
  }

  function scenarioBtn(sc, view) {
    const b = document.createElement("button");
    b.className = "scenario";
    b.innerHTML = `<span class="tag">${escapeHtml(sc.tag)}</span>${escapeHtml(sc.text)}`;
    b.onclick = () => {
      if (view === "orchestrate") {
        $("#goalInput").value = sc.text; $("#goalInput").focus();
      } else if (sc.cap) {
        const sel = $("#navSelect");
        sel.value = sc.cap;
        if (sel.onchange) sel.onchange();  // 触发与手动选择相同的跳转渲染
      }
    };
    return b;
  }

  async function loadCapabilities() {
    try {
      const data = await api("/api/capabilities", "GET");
      state.capabilities = data.capabilities || [];
      state.examples = data.examples || {};
      const refund = state.examples['m7.refund_approval'];
      if (refund) SCENARIOS.find(s => s.tag === '退款').text = `查询订单 ${refund.order_id} 并申请整单退款，原因是买错了。`;
      renderCapabilityList($("#capabilityList"));
      renderCapabilityList($("#capabilityList2"));
      populateNav();
    } catch (e) { toast('能力清单加载失败：' + e.message); $('#connectionError').hidden = false; }
  }

  function renderCapabilityList(box) {
    if (!box) return;
    box.innerHTML = "";
    (state.capabilities || []).forEach((c) => {
      const div = document.createElement("div");
      div.className = "cap";
      div.innerHTML =
        `<div class="cap-head"><span class="cap-name">${escapeHtml(c.name)}</span>` +
        `<span class="cap-id">${escapeHtml(c.capability_id)} · v${escapeHtml(c.version)}</span></div>` +
        `<div class="cap-desc">${escapeHtml(c.description)}</div>`;
      box.appendChild(div);
    });
  }

  /* ---------- 模块直调 ---------- */
  // 各能力的演示默认值（嵌套对象用点号路径在表单中还原）

  function populateNav() {
    const group = $("#moduleOptGroup");
    if (!group) return;
    group.innerHTML = "";
    (state.capabilities || []).forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.capability_id;
      opt.textContent = moduleName(c.capability_id);
      group.appendChild(opt);
    });
    $('#moduleCount').textContent = state.capabilities.length;
    const nav = $('#moduleNav'), grid = $('#assistantGrid');
    nav.innerHTML = ''; grid.innerHTML = '';
    state.capabilities.forEach(c => {
      const number = c.capability_id.split('.')[0].toUpperCase();
      const name = moduleName(c.capability_id);
      const desc = MODULE_UI[c.capability_id]?.[1] || c.description;
      const button = document.createElement('button');
      button.className = 'nav-item'; button.dataset.view = c.capability_id;
      button.innerHTML = `<span class="nav-icon">${escapeHtml(number)}</span><span>${escapeHtml(name)}</span>`;
      button.onclick = () => selectView(c.capability_id);
      nav.appendChild(button);
      const tile = document.createElement('button'); tile.className = 'assistant-card';
      tile.innerHTML = `<span class="assistant-icon">${escapeHtml(number)}</span><span><strong>${escapeHtml(name)}</strong><p>${escapeHtml(desc)}</p></span><span class="nav-arrow">↗</span>`;
      tile.onclick = () => selectView(c.capability_id); grid.appendChild(tile);
    });
  }

  // M1（FAQ 客服）的聊天记录：按会话 ID 保存，切走再切回仍保留
  const faqChats = {};

  // 根据下拉选择，渲染单个模块的专属调用界面（表单 + 调用 + 结果）
  function renderModuleDetail(capId) {
    const cap = (state.capabilities || []).find((c) => c.capability_id === capId);
    const detail = $("#moduleDetail");
    if (!cap || !detail) return;
    if (cap.capability_id === "m1.faq_chat") { renderFaqChat(cap); return; }
    if (moduleViews.has(capId)) { detail.replaceChildren(moduleViews.get(capId)); return; }
    detail.innerHTML =
      `<div class="module-card">` +
      `<div class="module-head"><span class="assistant-icon">${escapeHtml(capId.split('.')[0].toUpperCase())}</span><div><span class="cap-name">${escapeHtml(moduleName(capId))}</span>` +
      `<span class="cap-id">${escapeHtml(cap.capability_id)} · v${escapeHtml(cap.version)}</span></div></div>` +
      `<div class="cap-desc">${escapeHtml(MODULE_UI[capId]?.[1] || cap.description)}</div>` +
      `<form class="module-form" data-cap="${escapeHtml(cap.capability_id)}">` +
      formFields(cap.input_schema.properties || {}, cap.input_schema.required || [], "") +
      `</form>` +
      `<div class="module-actions"><button class="btn btn-primary" data-invoke="${escapeHtml(cap.capability_id)}">调用此模块</button>` +
      `<button class="btn btn-ghost" data-reset="${escapeHtml(cap.capability_id)}">清空</button></div>` +
      `<div class="module-result" id="result-${escapeHtml(cap.capability_id)}"></div>` +
      `</div>`;

    const card = detail.querySelector(".module-card");
    moduleViews.set(capId, card);
    if (capId === 'm4.capability_gateway') {
      const shortcuts = document.createElement('div'); shortcuts.className = 'skill-shortcuts';
      [['联网搜索','联网搜索近期电商新闻，提供来源。'],['知识问答','查询企业知识库：退换货有哪些条件？'],
       ['代码生成','用 Python 编写一个两数相加的函数。'],['图片生成','生成一张蓝色小鸟的简洁插画。']].forEach(([label,query])=>{
        const b = document.createElement('button'); b.textContent = label;
        b.onclick = () => { card.querySelector('[data-field="query"]').value=query; card.querySelector('[data-field="query"]').focus(); };
        shortcuts.appendChild(b);
      });
      card.querySelector('.module-form').before(shortcuts);
    }
    const defaults = state.examples[cap.capability_id] || {};
    const prefill = Object.assign({}, defaults);
    if (cap.capability_id === "m1.faq_chat" && state.sessionId) prefill.session_id = state.sessionId;
    fillDefaults(card, prefill);

    card.querySelector(`[data-invoke="${CSS.escape(cap.capability_id)}"]`).onclick = () => invokeModule(card, cap.capability_id);
    card.querySelector(`[data-reset="${CSS.escape(cap.capability_id)}"]`).onclick = () => {
      card.querySelectorAll("[data-field]").forEach((el) => { if (el.type === "checkbox") el.checked = false; else el.value = ""; });
    };
  }

  /* ---------- M1 FAQ 聊天窗口 ---------- */
  function renderFaqChat(cap) {
    const detail = $("#moduleDetail");
    if (!detail) return;
    const sid = state.sessionId;
    faqChats[sid] = faqChats[sid] || [];
    detail.innerHTML =
      `<div class="module-card">` +
      `<div class="module-head"><span class="assistant-icon">M1</span><div><span class="cap-name">智能客服</span>` +
      `<span class="cap-id">${escapeHtml(cap.capability_id)} · v${escapeHtml(cap.version)}</span></div></div>` +
      `<div class="cap-desc">${escapeHtml(MODULE_UI[cap.capability_id]?.[1] || cap.description)}</div>` +
      `<div class="chat-window">` +
      `<div class="chat-messages" id="faqMessages"></div>` +
      `<div class="chat-input-row">` +
      `<textarea id="faqInput" rows="2" placeholder="输入客服问题，回车发送（Shift+回车换行）"></textarea>` +
      `<button class="btn btn-primary" id="faqSend">发送</button>` +
      `</div>` +
      `<div class="chat-foot">` +
      `<button class="btn btn-ghost" id="faqClear">重置会话并清空</button>` +
      `<span class="muted">多轮记忆基于会话 ID：<code>${escapeHtml(sid)}</code></span>` +
      `</div>` +
      `</div></div>`;

    $("#faqSend").onclick = sendFaqMessage;
    const input = $("#faqInput");
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendFaqMessage(); }
    });
    $("#faqClear").onclick = resetSession;

    renderFaqBubbles(sid, false);
  }

  function renderFaqBubbles(sid, typing) {
    const box = $("#faqMessages");
    if (!box) return;
    const msgs = faqChats[sid];
    if (!msgs || msgs.length === 0) {
      box.innerHTML = `<div class="chat-empty">你好，我是 FAQ 客服。可以问我退换货、发票、售后政策等问题。支持基于本会话的多轮追问。</div>`;
    } else {
      let html = "";
      msgs.forEach((m) => {
        if (m.role === "user") {
          html += `<div class="chat-msg user"><div class="bubble">${escapeHtml(m.text)}</div></div>`;
        } else {
          html += `<div class="chat-msg bot"><div class="bubble bot-bubble">${miniMarkdown(m.text)}</div></div>`;
        }
      });
      box.innerHTML = html;
    }
    if (typing) {
      box.insertAdjacentHTML("beforeend",
        `<div class="chat-msg bot"><div class="bubble bot-bubble typing"><span class="spinner"></span>正在思考…</div></div>`);
    }
    box.scrollTop = box.scrollHeight;
  }

  async function sendFaqMessage() {
    if ($("#faqSend")?.disabled) return;
    const input = $("#faqInput");
    const text = input.value.trim();
    if (!text) return;
    if (!state.sessionId) { toast("会话未就绪"); return; }
    const sid = state.sessionId;
    faqChats[sid] = faqChats[sid] || [];
    faqChats[sid].push({ role: "user", text });
    input.value = "";
    renderFaqBubbles(sid, true);

    const sendBtn = $("#faqSend");
    requestStarted();
    sendBtn.disabled = true;
    try {
      const report = await api("/api/invoke", "POST", {
        session_id: sid, capability_id: "m1.faq_chat",
        payload: { question: text },
      });
      const step = report && report.steps ? Object.values(report.steps)[0] : null;
      if (report.status !== 'completed' || step?.status !== 'completed') {
        throw new Error(step?.error?.message || step?.result?.error?.message || '客服调用未完成');
      }
      const answer = (step && step.result && step.result.data && step.result.data.answer) || "（未返回答案）";
      faqChats[sid].push({ role: "bot", text: answer });
    } catch (e) {
      faqChats[sid].push({ role: "bot", text: "调用失败：" + e.message });
    } finally {
      requestFinished();
      sendBtn.disabled = false;
      if (state.sessionId === sid) renderFaqBubbles(sid, false);
    }
  }

  function setupCollapsibles() {
    document.querySelectorAll("[data-collapsible] > .card-title").forEach((h) => {
      h.onclick = () => h.parentElement.classList.toggle("collapsed");
    });
  }

  // 由 JSON Schema 生成表单（支持一层嵌套 object）；返回 HTML 字符串
  function formFields(properties, required, pathPrefix) {
    let html = "";
    Object.entries(properties).forEach(([key, prop]) => {
      const path = pathPrefix ? `${pathPrefix}.${key}` : key;
      const isRequired = required.includes(key);
      if (prop.type === "object" && prop.properties) {
        html += `<fieldset class="nested"><legend>${escapeHtml(FIELD_LABELS[key] || key)}${isRequired ? ' <span class="req">*</span>' : ''}</legend>` +
          formFields(prop.properties, prop.required || [], path) + `</fieldset>`;
      } else {
        html += fieldHtml(key, prop, path, isRequired);
      }
    });
    return html;
  }

  function fieldHtml(key, prop, path, isRequired) {
    const label = escapeHtml(FIELD_LABELS[key] || key) + (key.endsWith('_amount') ? '（元）' : '') + (isRequired ? ' <span class="req">*</span>' : '');
    const type = prop.type;
    let control;
    if (type === "string" && Array.isArray(prop.enum)) {
      control = `<select data-field="${escapeHtml(path)}" data-type="enum">` +
        prop.enum.map((o) => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("") + `</select>`;
    } else if (type === "integer" || type === "number") {
      const step = key.endsWith("_amount") ? "0.01" : type === "number" ? "0.001" : "1";
      control = `<input type="number" data-field="${escapeHtml(path)}" data-type="${type}" step="${step}" />`;
    } else if (type === "boolean") {
      control = `<input type="checkbox" data-field="${escapeHtml(path)}" data-type="boolean" />`;
    } else if (type === "array") {
      control = `<textarea data-field="${escapeHtml(path)}" data-type="array" rows="2" placeholder="每行或逗号分隔一项"></textarea>`;
    } else if (['question','query','goal','reason','report_markdown','anomaly'].includes(key)) {
      control = `<textarea data-field="${escapeHtml(path)}" data-type="string" rows="3"></textarea>`;
    } else {
      const ph = prop.pattern ? `placeholder="格式：${escapeHtml(prop.pattern)}"` : "";
      control = `<input type="text" data-field="${escapeHtml(path)}" data-type="string" ${ph} />`;
    }
    const id = `field-${path.replace(/\./g,'-')}`;
    control = control.replace(/<(input|select|textarea) /, `<$1 id="${escapeHtml(id)}" `);
    return `<div class="field ${['question','query','goal','reason','report_markdown','anomaly'].includes(key) ? 'field-wide' : ''}"><label for="${escapeHtml(id)}">${label}</label>${control}` +
      (prop.description ? `<div class="field-desc">${escapeHtml(prop.description)}</div>` : "") + `</div>`;
  }

  function fillDefaults(card, defaults) {
    if (!defaults) return;
    card.querySelectorAll("[data-field]").forEach((el) => {
      const path = el.getAttribute("data-field");
      const val = getPath(defaults, path);
      if (val === undefined || val === null || val === "") return;
      if (el.tagName === "SELECT") el.value = val;
      else if (el.type === "checkbox") el.checked = !!val;
      else el.value = (typeof val === "object") ? "" : path.split(".").pop().endsWith("_amount") && typeof val === "number" ? val.toFixed(2) : String(val);
    });
  }

  // 读取嵌套对象的字段（点号路径）
  function getPath(obj, path) {
    return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
  }

  // 收集表单 -> 嵌套 payload；空值省略，保持与 Manifest 一致
  function collectForm(card) {
    const payload = {};
    card.querySelectorAll("[data-field]").forEach((el) => {
      const path = el.getAttribute("data-field");
      const type = el.getAttribute("data-type") || "string";
      let val;
      if (el.tagName === "SELECT") val = el.value;
      else if (el.type === "checkbox") val = el.checked;
      else if (type === "integer" || type === "number") {
        const raw = el.value.trim();
        if (raw === "") return;
        val = Number(raw);
        if (!Number.isFinite(val)) throw new Error(`字段 ${path} 不是合法数字`);
        if (path.split('.').pop().endsWith('_amount') && (!/^\d+(?:\.\d{1,2})?$/.test(raw) || val > 999999999999.99)) throw new Error('金额单位为元，请填写最多两位小数且不超过 999999999999.99。');
        if (type === 'integer' && !Number.isInteger(val)) throw new Error('数量必须填写整数。');
      } else if (type === "array") {
        const raw = el.value.trim();
        if (raw === "") return;
        val = raw.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      } else {
        const raw = el.value.trim();
        if (raw === "") return;
        val = raw;
      }
      setPath(payload, path, val);
    });
    return payload;
  }

  function setPath(obj, path, value) {
    const keys = path.split(".");
    let cur = obj;
    for (let i = 0; i < keys.length - 1; i++) {
      if (typeof cur[keys[i]] !== "object" || cur[keys[i]] === null) cur[keys[i]] = {};
      cur = cur[keys[i]];
    }
    cur[keys[keys.length - 1]] = value;
  }

  async function invokeModule(card, capId) {
    const resultEl = card.querySelector(".module-result");
    const btn = card.querySelector(`[data-invoke="${CSS.escape(capId)}"]`);
    let payload;
    try {
      payload = collectForm(card);
    } catch (e) {
      toast(e.message); return;
    }
    if (!state.sessionId) { toast("会话未就绪"); return; }
    requestStarted();
    btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>调用中`;
    resultEl.innerHTML = '<div class="module-progress" role="status"><span class="spinner"></span>正在处理，请稍候。复杂任务可能需要一至两分钟。</div>';
    try {
      const report = await api("/api/invoke", "POST", { session_id: state.sessionId, capability_id: capId, payload });
      resultEl.innerHTML = renderReport(report);
      bindReviews(resultEl, "/api/invoke/review");
      resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) {
      resultEl.innerHTML = `<div class="turn"><div class="turn-status-line">` +
        `<span class="status-badge status-failed">失败</span></div>` +
        `<div class="turn-message">${escapeHtml(e.message)}</div></div>`;
      toast("调用失败：" + e.message);
    } finally {
      requestFinished();
      btn.disabled = false; btn.textContent = "调用此模块";
    }
  }

  /* ---------- 下拉导航：选择模块 / 统一调用，跳转对应界面 ---------- */
  function setupNav() {
    const sel = $("#navSelect");
    if (!sel) return;
    sel.onchange = () => {
      const v = sel.value;
      if (v === "orchestrate") {
        $("#viewOrchestrate").hidden = false;
        $("#viewModule").hidden = true;
      } else {
        $("#viewOrchestrate").hidden = true;
        $("#viewModule").hidden = false;
        renderModuleDetail(v);
      }
      $('#pageTitle').textContent = v === 'orchestrate' ? '智能任务' : moduleName(v);
      document.querySelectorAll('[data-view]').forEach(button => {
        const active = button.dataset.view === v;
        button.classList.toggle('active', active);
        if (active) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
      });
    };
    document.querySelectorAll('[data-view="orchestrate"]').forEach(button=>button.onclick=()=>selectView('orchestrate'));
  }

  function selectView(value) {
    const select = $('#navSelect'); select.value = value; select.onchange();
    $('#workspace').scrollIntoView({behavior:'smooth',block:'start'});
  }

  /* ---------- 发送 ---------- */
  async function sendGoal(execute) {
    if ($('#btnRun').disabled) return;
    const input = $("#goalInput");
    const text = input.value.trim();
    if (!text) { toast("请输入任务目标"); return; }
    if (!state.sessionId) { toast("会话未就绪"); return; }

    if (emptyState) emptyState.style.display = "none";

    appendUserTurn(text);
    setLoading(true, execute ? "规划并执行业务模块…" : "生成并校验计划…");

    try {
      const path = execute ? "/api/chat" : "/api/plan";
      const turn = await api(path, "POST", { session_id: state.sessionId, text });
      renderTurn(turn, text);
    } catch (e) {
      appendError(e.message);
    } finally {
      setLoading(false);
      input.value = "";
    }
  }

  function setLoading(on, msg) {
    const run = $("#btnRun"), plan = $("#btnPlan");
    run.disabled = plan.disabled = on;
    if (on) {
      requestStarted();
      const previewOnly = msg.startsWith('生成');
      run.innerHTML = previewOnly ? '开始执行 ↗' : `<span class="spinner"></span>执行中`;
      plan.innerHTML = previewOnly ? `<span class="spinner"></span>预览中` : '仅预览计划';
      $('#taskProgress').hidden = false;
      $('#taskProgress').textContent = msg + ' 复杂任务可能需要一至两分钟。';
    } else {
      requestFinished();
      $('#taskProgress').hidden = true;
      run.textContent = "开始执行 ↗"; plan.textContent = "仅预览计划";
    }
  }

  /* ---------- 渲染回合 ---------- */
  function appendUserTurn(text) {
    const card = document.createElement("div");
    card.className = "turn user";
    card.innerHTML = `<p class="turn-user-text">${escapeHtml(text)}</p>`;
    transcript.appendChild(card);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function appendError(msg) {
    const card = document.createElement("div");
    card.className = "turn";
    card.innerHTML =
      `<div class="turn-status-line"><span class="status-badge status-failed">失败</span></div>` +
      `<div class="turn-message">${escapeHtml(msg)}</div>`;
    transcript.appendChild(card);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function statusLabel(status) {
    return ({
      ready: "计划就绪", needs_clarification: "需要澄清", unsupported: "不支持",
      completed: "已完成", failed: "失败", waiting_approval: "等待审批",
      pending: "等待上游", running: "执行中", skipped: "未执行",
    })[status] || status;
  }

  function renderTurn(turn, originalText) {
    const card = document.createElement("div");
    card.className = "turn";
    let html =
      `<div class="turn-status-line">` +
      `<span class="status-badge status-${escapeHtml(turn.status)}">${statusLabel(turn.status)}</span>` +
      `<span class="evt">task ${escapeHtml(turn.task_id)} · ${escapeHtml(turn.trace_id)}</span></div>` +
      `<div class="turn-message">${escapeHtml(turn.message)}</div>`;

    if (turn.plan && turn.plan.steps && turn.plan.steps.length) {
      html += `<div class="section-title">生成的计划（${escapeHtml(turn.plan.plan_id)}）</div>`;
      html += renderPlan(turn.plan);
      if (turn.status === "ready") {
        html += `<div class="warn-line">这是计划预览，业务尚未执行。开始执行时会按这个目标重新规划。</div>`;
        html += `<div class="approve-actions"><button class="btn btn-primary" data-exec="${escapeHtml(originalText || "")}">执行这个目标</button></div>`;
      }
    }

    if (turn.report) html += `<div class="module-result">${renderReport(turn.report)}</div>`;
    if (turn.error) {
      html += `<div class="section-title">错误</div>` +
        `<div class="kv"><dt>错误码</dt><dd>${escapeHtml(turn.error.code)}</dd>` +
        `<dt>消息</dt><dd>${escapeHtml(turn.error.message)}</dd>` +
        `<dt>可重试</dt><dd>${turn.error.retryable ? "是" : "否"}</dd></div>`;
    }
    if (turn.planning_attempts && turn.planning_attempts.length > 1) {
      html += `<div class="warn-line">规划调用次数：${turn.planning_attempts.length}（含非法计划修正）</div>`;
    }

    card.innerHTML = html;
    transcript.appendChild(card);

    // 绑定“执行此计划”
    const execBtn = card.querySelector("[data-exec]");
    if (execBtn) execBtn.onclick = () => { $("#goalInput").value = execBtn.getAttribute("data-exec"); sendGoal(true); };

    // 绑定审批表单
    bindReviews(card, "/api/review");

    transcript.scrollTop = transcript.scrollHeight;
  }

  function renderPlan(plan) {
    let html = `<div class="plan-steps">`;
    plan.steps.forEach((s) => {
      const dep = s.depends_on && s.depends_on.length ? `依赖 ${escapeHtml(s.depends_on.join(", "))}` : "无依赖";
      html += `<div class="plan-step"><span class="ps-id">${escapeHtml(s.step_id)}</span>` +
        `${escapeHtml(moduleName(s.capability_id))} <span class="ps-dep">· ${dep}</span></div>`;
    });
    html += `</div>`;
    return html;
  }

  function renderReport(report) {
    let html = `<div class="section-title">执行报告（总体：${statusLabel(report.status)}）</div>`;
    html += `<div class="report-steps">`;
    // 保持步骤顺序
    const ordered = Object.values(report.steps).sort((a, b) =>
      parseInt(a.step_id.slice(1)) - parseInt(b.step_id.slice(1)));
    ordered.forEach((step) => { html += renderStep(step, report.task_id); });
    html += `</div>`;

    if (report.events && report.events.length) {
      html += `<details class="diagnostics"><summary>查看执行轨迹</summary><div>`;
      report.events.forEach((e) => {
        html += `<div class="evt">${e.sequence}. ${escapeHtml(e.step_id)}: ${escapeHtml(e.status)} — ${escapeHtml(e.reason || "")}</div>`;
      });
      html += `</div></details>`;
    }

    if (report.final_results && Object.keys(report.final_results).length) {
      html += `<details class="diagnostics"><summary>查看原始结果 JSON</summary><div class="final-results">`;
      Object.entries(report.final_results).forEach(([sid, data]) => {
        html += `<div class="kv"><dt>${escapeHtml(sid)}</dt><dd>${renderDataValue(data)}</dd></div>`;
      });
      html += `</div></details>`;
    }
    return html;
  }

  function renderStep(step, taskId) {
    const st = step.status;
    let html = `<div class="rstep"><div class="rstep-head">` +
      `<span class="rstep-status status-${escapeHtml(st)}">${statusLabel(st)}</span>` +
      `<b>${escapeHtml(moduleName(step.capability_id))}</b> <span class="cap-id">${escapeHtml(step.step_id)}</span></div>` +
      `<div class="rstep-body">`;

    if (step.error) {
      html += `<div class="kv"><dt>错误码</dt><dd>${escapeHtml(step.error.code)}</dd>` +
        `<dt>消息</dt><dd class="error-message">${escapeHtml(step.error.message)}</dd></div>` +
        `<details class="diagnostics"><summary>完整错误详情（可选中复制）</summary><pre class="error-detail">${escapeHtml(JSON.stringify(step.error, null, 2))}</pre></details>`;
    }
    if (step.reason && st !== "failed") html += `<div class="turn-message">${escapeHtml(step.reason)}</div>`;
    if (step.result && step.result.data && Object.keys(step.result.data).length) {
      html += renderData(step.capability_id, step.result.data);
    }
    if (st === "waiting_approval") {
      html += renderApproveBox(step.step_id, taskId);
    }
    html += `</div></div>`;
    return html;
  }

  /* ---------- 业务数据渲染（按能力定制） ---------- */
  function renderData(capId, data) {
    if (capId === "m2.order_tracking") return renderOrder(data);
    if (capId === "m7.refund_approval") return renderRefund(data);
    if (capId === "m4.capability_gateway") return renderGateway(data);
    if (capId === "m5.promotion_plan") return renderPromotion(data);
    if (capId === "m3.weekly_report") return renderWeekly(data);
    if (capId === "m6.data_fusion") return renderFusion(data);
    if (capId === "m1.faq_chat") return `<div class="turn-message">${miniMarkdown(data.answer)}</div>`;
    return renderGeneric(data);
  }

  function kvRow(dt, dd) {
    const labels = {mode:'运行模式',provider:'服务商',model:'模型',query:'任务描述',answer:'回答',language:'代码语言',source_kind:'资料来源',conflicts:'资料差异',warning:'提示'};
    return `<div class="kv"><dt>${escapeHtml(labels[dt] || dt)}</dt><dd>${dd}</dd></div>`;
  }

  function renderGeneric(data) {
    let html = "";
    Object.entries(data).forEach(([k, v]) => {
      html += kvRow(k, renderDataValue(v));
    });
    return html;
  }

  function renderDataValue(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") return `<pre class="code">${escapeHtml(JSON.stringify(v, null, 2))}</pre>`;
    return escapeHtml(v);
  }

  function renderOrder(d) {
    let html = "";
    html += kvRow("订单号", escapeHtml(d.order_id));
    if (typeof d.order_amount === "number") html += kvRow("订单金额", moneyYuan(d.order_amount));
    const statusNames = {delivered:'已送达',completed:'已完成',paid:'已付款',shipped:'已发货',pending:'待处理',cancelled:'已取消',processing:'处理中',refunded:'已退款'};
    html += kvRow("订单状态", escapeHtml(statusNames[d.order_status] || d.order_status));
    const avail = d.logistics_availability;
    if (avail === "available") {
      html += kvRow("物流状态", `<span class="status-badge status-completed">已核实</span>`);
      html += kvRow("运单号", d.tracking_number ? escapeHtml(d.tracking_number) : "—");
    } else if (avail === "unavailable" || avail === "inconsistent") {
      html += kvRow("物流状态", `<span class="status-badge status-needs_clarification">${avail === 'unavailable' ? '缺少物流资料' : '资料存在冲突'}</span>`);
      html += `<div class="warn-line">物流未核实，未展示有效运单（tracking_number 为空或不一致）。</div>`;
    }
    if (Array.isArray(d.warnings) && d.warnings.length) {
      d.warnings.forEach((w) => (html += `<div class="warn-line">⚠ ${escapeHtml(w)}</div>`));
    }
    if (Array.isArray(d.observations)) {
      html += `<details class="diagnostics"><summary>查询过程与依据</summary>`;
      d.observations.forEach((o) => (html += `<div class="evt">${renderDataValue(o)}</div>`));
      html += '</details>';
    }
    return html;
  }

  function renderRefund(d) {
    let html = "";
    const status = d.approval_status;
    const label = { approved: "已批准", rejected: "已拒绝", waiting_approval: "待审批" }[status] || status;
    const cls = { approved: "status-completed", rejected: "status-failed", waiting_approval: "status-waiting_approval" }[status] || "";
    html += kvRow("审批状态", `<span class="status-badge ${cls}">${label}</span>`);
    html += kvRow("申请号", escapeHtml(d.request_id));
    if (d.state_view) {
      const sv = d.state_view;
      if (typeof sv.order_amount === "number") html += kvRow("订单金额", moneyYuan(sv.order_amount));
      if (typeof sv.refund_amount === "number") html += kvRow("退款金额", moneyYuan(sv.refund_amount));
    }
    if (Array.isArray(d.node_trace)) {
      html += kvRow("节点轨迹", d.node_trace.map((n) => escapeHtml(typeof n === 'string' ? n : n.node_name || n.node || JSON.stringify(n))).join(" → "));
    }
    return html;
  }

  function renderGateway(d) {
    let html = kvRow("技能", escapeHtml(d.skill_name));
    let parsed = null;
    try { parsed = JSON.parse(d.result); } catch (_) { parsed = null; }
    if (parsed && typeof parsed === "object") {
      // 结构化结果（真实/部分 Mock）
      Object.entries(parsed).forEach(([k, v]) => {
        if ((k === "sources" || k === "results") && Array.isArray(v)) {
          html += `<div class="section-title" style="margin-top:6px">来源</div>`;
          v.forEach((s) => {
            const url = safeUrl(s.source_url || s.url || s.link);
            const title = s.title || s.name || url || "来源";
            if (url) html += `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>`;
            else html += `<div class="evt">${escapeHtml(title)}</div>`;
          });
        } else if (k === 'images' && Array.isArray(v)) {
          v.forEach(img => {
            const url = safeUrl(img.image_url) || rasterDataUrl(img.b64_json);
            if (url) html += `<img src="${escapeHtml(url)}" alt="生成图片" style="max-width:100%;max-height:480px;border-radius:8px" />`;
          });
        } else if (k === "image" || k === "image_url" || k === "url") {
          const url = safeUrl(v);
          if (url) html += kvRow(k, `<img src="${escapeHtml(url)}" alt="生成图片" style="max-width:240px;border-radius:8px" />`);
        } else if (k === "code" || (typeof v === "string" && /```/.test(v))) {
          html += `<pre class="code">${escapeHtml(typeof v === "string" ? v : JSON.stringify(v))}</pre>`;
        } else {
          html += kvRow(k, renderDataValue(v));
        }
      });
    } else {
      // 纯字符串回退（新增 Skill 或 Mock 文本）
      const r = d.result || "";
      if (/```/.test(r)) html += miniMarkdown(r);
      else html += `<div class="turn-message">${escapeHtml(r)}</div>`;
    }
    html += kvRow("路由说明", escapeHtml(d.route_reason || ""));
    return html;
  }

  function renderPromotion(d) {
    let html = "";
    if (d.plan_markdown) {
      // 顶部“已核对的基础数据”为程序计算，单独标注；其余为模型建议
      const md = d.plan_markdown;
      const first = /^## 已核对的基础数据\s*\n/.test(md);
      const end = first ? md.indexOf('\n## ', 3) : -1;
      if (first && end >= 0) {
        html += `<div class="verified-facts"><h4>已核对的基础数据（程序计算）</h4>` + miniMarkdown(md.slice(0, end)) + `</div>`;
        html += `<div class="section-title">方案（模型建议 · 草稿）</div>` + miniMarkdown(md.slice(end));
      } else {
        html += `<div class="section-title">方案（模型建议 · 草稿）</div>` + miniMarkdown(md);
      }
    }
    if (Array.isArray(d.roles)) {
      html += `<div class="section-title">四角色协同</div>`;
      d.roles.forEach((r) => {
        html += `<div class="role-card"><div class="role-name">${escapeHtml(r.role)}</div>` +
          `<div>${escapeHtml(r.contribution)}</div>` +
          (r.rationale ? `<div class="muted" style="margin-top:4px">${escapeHtml(r.rationale)}</div>` : "") +
          `</div>`;
      });
    }
    return html;
  }

  function renderWeekly(d) {
    let html = "";
    if (d.week) html += kvRow("周次", escapeHtml(d.week));
    if (d.report_markdown) html += `<div class="section-title">周报</div>` + miniMarkdown(d.report_markdown);
    if (Array.isArray(d.steps)) {
      html += `<details class="diagnostics"><summary>周报生成步骤</summary>`;
      d.steps.forEach((s) => html += `<div class="evt">${typeof s === 'string' ? escapeHtml(s) : escapeHtml(s.step_id || '') + ' · ' + escapeHtml(s.description || s.action || '') + ' · ' + escapeHtml(s.status || '')}</div>`);
      html += '</details>';
    }
    return html;
  }

  function renderFusion(d) {
    let html = "";
    if (d.fused_data) {
      const f = d.fused_data;
      html += kvRow("周次", escapeHtml(f.week));
      if (typeof f.revenue_amount === "number") html += kvRow("成交额", moneyYuan(f.revenue_amount));
      html += kvRow("订单数", escapeHtml(f.order_count));
      html += kvRow("转化率", typeof f.conversion_rate === 'number' ? `${(f.conversion_rate*100).toFixed(2)}%` : escapeHtml(f.conversion_rate));
      html += kvRow("异常", escapeHtml(f.anomaly));
    }
    if (Array.isArray(d.field_definitions)) html += kvRow("字段定义", d.field_definitions.map(escapeHtml).join("；"));
    if (Array.isArray(d.update_events)) {
      html += `<details class="diagnostics"><summary>数据更新记录</summary>`;
      d.update_events.forEach((e) => html += `<div class="evt">${escapeHtml(e)}</div>`);
      html += '</details>';
    }
    return html;
  }

  /* ---------- 审批 ---------- */
  function renderApproveBox(stepId, taskId) {
    return `<div class="approve-box" data-approve="${escapeHtml(stepId)}">` +
      `<h4>等待人工审批（${escapeHtml(stepId)}）</h4>` +
      `<label>审核人<input type="text" class="reviewer" placeholder="请输入审核人姓名" /></label>` +
      `<div class="approve-row"><label><input type="checkbox" class="approved" checked /> 批准</label>` +
      `<label><input type="checkbox" class="material" checked /> 材料齐全</label></div>` +
      `<div class="approve-actions">` +
      `<button class="btn btn-primary" data-review-step="${escapeHtml(stepId)}" data-task="${escapeHtml(taskId || "")}">提交决定</button>` +
      `</div></div>`;
  }

  function bindReviews(scope, endpoint) {
    scope.querySelectorAll("[data-review-step]").forEach((btn) => {
      const stepId = btn.getAttribute("data-review-step");
      const taskId = btn.getAttribute("data-task");
      btn.onclick = () => submitReview(scope, stepId, taskId, endpoint);
    });
  }

  async function submitReview(card, stepId, taskId, endpoint) {
    const box = card.querySelector(`[data-approve="${CSS.escape(stepId)}"]`);
    if (!box) return;
    const reviewer = box.querySelector(".reviewer").value.trim();
    if (!reviewer) { toast("请填写审核人"); return; }
    const approved = box.querySelector(".approved").checked;
    const material = box.querySelector(".material").checked;
    const btn = card.querySelector(`[data-review-step="${CSS.escape(stepId)}"]`);
    requestStarted();
    btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>提交中`;
    try {
      const report = await api(endpoint || "/api/review", "POST", {
        session_id: state.sessionId, step_id: stepId,
        approved, reviewer, material_complete: material, task_id: taskId || undefined,
      });
      // 直调返回的是报告本身（含 task_id），对话返回的是回合；统一取 report 字段
      const rep = report.report || report;
      if (report.error) throw new Error(report.error.message || '审核失败');
      const container = card.classList.contains("module-result") ? card : card.querySelector(".module-result");
      if (container) {
        container.innerHTML = renderReport(rep);
        bindReviews(container, endpoint || "/api/review");
        container.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      const status = card.querySelector('.turn-status-line .status-badge');
      if (status) { status.textContent = statusLabel(report.status); status.className = 'status-badge status-' + report.status; }
      toast("审核已提交");
    } catch (e) {
      toast("审核失败：" + e.message);
    } finally {
      requestFinished();
      btn.disabled = false; btn.textContent = "提交决定";
    }
  }

  /* ---------- 会话操作 ---------- */
  async function newTask() {
    if (activeRequests) return;
    try { await api("/api/new", "POST", { session_id: state.sessionId }); toast("已结束当前任务，历史保留"); }
    catch (e) { toast(e.message); }
  }
  async function resetSession() {
    if (activeRequests) return;
    try {
      const oldId = state.sessionId;
      const c = await api("/api/reset", "POST", { session_id: state.sessionId });
      state.sessionId = c.session_id;
      $('#sessionId').textContent = c.session_id;
      delete faqChats[oldId];
      moduleViews.clear();
      transcript.innerHTML = "";
      if (emptyState) emptyState.style.display = '';
      const selected = $('#navSelect').value;
      if (selected !== 'orchestrate') renderModuleDetail(selected);
      toast("会话已重置");
    } catch (e) { toast(e.message); }
  }

  function safeUrl(value) {
    if (typeof value !== 'string') return '';
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; }
    catch (_) { return ''; }
  }

  function rasterDataUrl(value) {
    if (typeof value !== 'string' || !/^[A-Za-z0-9+/=]+$/.test(value)) return '';
    const mime = value.startsWith('iVBORw0KGgo') ? 'png' : value.startsWith('/9j/') ? 'jpeg' : value.startsWith('R0lGOD') ? 'gif' : value.startsWith('UklGR') ? 'webp' : '';
    return mime ? `data:image/${mime};base64,${value}` : '';
  }

  /* ---------- 绑定 ---------- */
  $("#btnRun").onclick = () => sendGoal(true);
  $("#btnPlan").onclick = () => sendGoal(false);
  $("#btnNew").onclick = newTask;
  $("#btnReset").onclick = resetSession;
  $("#goalInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendGoal(true);
  });

  setupNav();
  setupCollapsibles();
  init();
})();
