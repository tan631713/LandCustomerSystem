"use strict";

const state = {
  token: sessionStorage.getItem("lcs_access_token") || "",
  user: null,
  currentRecordId: null,
  loadedPages: new Set()
};

const pages = {
  home: "首頁",
  owners: "地主搜尋",
  lands: "土地搜尋",
  followups: "追蹤提醒"
};

const recordLabels = {
  district: "地區",
  section: "地段",
  registration_order: "登記次序",
  land_number: "地號",
  area: "面積（㎡）",
  declared_value: "公告現值",
  numerator: "分子",
  denominator: "分母",
  ping: "持分坪數",
  total_declared_value: "持分總現值",
  owner_name: "姓名",
  external_id: "身分證",
  address: "地址",
  registration_reason: "登記原因",
  note: "備註",
  visit_log: "出訪記錄",
  case_names: "案件",
  tag_names: "標籤"
};

const $ = selector => document.querySelector(selector);
const $$ = selector => Array.from(document.querySelectorAll(selector));

function text(value, fallback = "—") {
  const result = String(value ?? "").trim();
  return result || fallback;
}

function element(tag, className = "", content = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = String(content);
  return node;
}

function setChildren(parent, children) {
  parent.replaceChildren(...children.filter(Boolean));
}

function apiErrorMessage(payload, fallback) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(item => item.msg || "輸入內容不正確").join("；");
  }
  return fallback || "伺服器暫時無法處理要求。";
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response;
  try {
    response = await fetch(path, { ...options, headers, cache: "no-store" });
  } catch (error) {
    updateConnection(false, "無法連線至自架伺服器");
    throw new Error("無法連線至自架伺服器，請確認電腦、API 與 Wi-Fi／VPN 都已連線。");
  }

  updateConnection(true);
  if (response.status === 204) return null;

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/v1/auth/login") showLogin("登入已失效，請重新登入。");
    throw new Error(apiErrorMessage(payload, `伺服器錯誤（${response.status}）`));
  }
  return payload;
}

function updateConnection(online, message = "") {
  const banner = $("#connection-banner");
  banner.classList.toggle("online", online);
  banner.classList.toggle("offline", !online);
  banner.textContent = message || (online ? "已連線 PostgreSQL" : "目前離線");
}

let toastTimer = null;
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 2800);
}

function roleLabel(role) {
  return { admin: "管理員", editor: "編輯者", viewer: "唯讀" }[role] || text(role, "使用者");
}

function applyRole() {
  const canEdit = state.user && ["admin", "editor"].includes(state.user.role);
  $$(".editor-only").forEach(node => node.classList.toggle("hidden", !canEdit));
}

function showLogin(message = "") {
  state.token = "";
  state.user = null;
  state.currentRecordId = null;
  state.loadedPages.clear();
  sessionStorage.removeItem("lcs_access_token");
  $("#app-shell").classList.add("hidden");
  $("#record-sheet").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
  $("#login-error").textContent = message;
  $("#login-password").value = "";
}

function showApp(user) {
  state.user = user;
  $("#login-view").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  $("#user-name").textContent = user.display_name || user.username;
  $("#user-role").textContent = `${roleLabel(user.role)}・點此登出`;
  applyRole();
  navigate("home", true);
}

async function login(event) {
  event.preventDefault();
  const button = $("#login-button");
  button.disabled = true;
  button.textContent = "登入中…";
  $("#login-error").textContent = "";
  try {
    const payload = await request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("#login-username").value,
        password: $("#login-password").value
      })
    });
    state.token = payload.access_token;
    sessionStorage.setItem("lcs_access_token", state.token);
    showApp(payload.user);
  } catch (error) {
    $("#login-error").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "登入";
  }
}

async function logout() {
  if (!confirm("確定要登出地主開發助手嗎？")) return;
  try { await request("/api/v1/auth/logout", { method: "POST" }); } catch (_error) { /* local logout still continues */ }
  showLogin();
}

function navigate(page, force = false) {
  if (!pages[page]) return;
  $$(".page").forEach(node => node.classList.toggle("active", node.id === `page-${page}`));
  $$(".bottom-nav button").forEach(button => button.classList.toggle("active", button.dataset.page === page));
  $("#page-title").textContent = pages[page];
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (force || !state.loadedPages.has(page)) {
    state.loadedPages.add(page);
    if (page === "home") loadDashboard();
    if (page === "owners") searchOwners();
    if (page === "lands") searchLands();
    if (page === "followups") loadFollowups();
  }
}

async function loadDashboard() {
  try {
    const [records, owners, lands, followups] = await Promise.all([
      request("/api/v1/records?limit=1"),
      request("/api/v1/owners?limit=1"),
      request("/api/v1/lands?limit=1"),
      request("/api/v1/follow-ups?limit=500")
    ]);
    $("#stat-records").textContent = records.total;
    $("#stat-owners").textContent = owners.total;
    $("#stat-lands").textContent = lands.total;
    $("#stat-followups").textContent = (followups.items || []).filter(item => {
      const status = item.status || item.follow_up_status || "";
      return status !== "完成";
    }).length;
  } catch (error) {
    toast(error.message);
  }
}

function metric(label, value) {
  return element("span", "metric", `${label} ${text(value, "0")}`);
}

function emptyState(message) {
  return element("div", "empty-state", message);
}

async function searchOwners(event) {
  if (event) event.preventDefault();
  const container = $("#owner-results");
  setChildren(container, [emptyState("正在查詢地主…")]);
  try {
    const query = encodeURIComponent($("#owner-query").value.trim());
    const result = await request(`/api/v1/owners?q=${query}&limit=100`);
    $("#owner-count").textContent = `共 ${result.total} 位地主`;
    const cards = (result.items || []).map(owner => {
      const card = element("article", "result-card");
      const heading = element("h3", "", text(owner.name, "未填姓名"));
      const meta = element("div", "card-meta");
      meta.append(
        element("span", "", `身分證：${text(owner.external_id)}`),
        element("span", "", `地址：${text(owner.address)}`)
      );
      const metrics = element("div", "metric-row");
      metrics.append(
        metric("土地", owner.land_count),
        metric("持分", owner.record_count),
        metric("坪數", owner.total_ping),
        metric("現值", owner.total_declared_value)
      );
      const buttons = element("div", "owner-buttons");
      (owner.record_ids || []).slice(0, 6).forEach((recordId, index) => {
        const button = element("button", "record-link", `持分 ${index + 1}`);
        button.type = "button";
        button.dataset.recordId = recordId;
        buttons.append(button);
      });
      if ((owner.record_ids || []).length > 6) buttons.append(element("span", "muted", `另有 ${owner.record_ids.length - 6} 筆`));
      card.append(heading, meta, metrics, buttons);
      return card;
    });
    setChildren(container, cards.length ? cards : [emptyState("找不到符合的地主。")]);
  } catch (error) {
    setChildren(container, [emptyState(error.message)]);
  }
}

async function searchLands(event) {
  if (event) event.preventDefault();
  const container = $("#land-results");
  setChildren(container, [emptyState("正在查詢土地…")]);
  const params = new URLSearchParams({
    q: $("#land-query").value.trim(),
    district: $("#land-district").value.trim(),
    section: $("#land-section").value.trim(),
    limit: "100"
  });
  try {
    const result = await request(`/api/v1/lands?${params}`);
    $("#land-count").textContent = `共 ${result.total} 筆土地`;
    const cards = (result.items || []).map(land => {
      const card = element("article", "result-card");
      card.append(element("h3", "", `${text(land.district, "未填地區")}・${text(land.section, "未填地段")}・${text(land.land_number, "未填地號")}`));
      const metrics = element("div", "metric-row");
      metrics.append(metric("面積㎡", land.area), metric("公告現值", land.declared_value), metric("地主", (land.owners || []).length));
      card.append(metrics);
      (land.owners || []).forEach(owner => {
        const row = element("div", "owner-buttons");
        const button = element("button", "record-link", `${text(owner.name, "未填姓名")}・${text(owner.numerator, "?")}/${text(owner.denominator, "?")}`);
        button.type = "button";
        button.dataset.recordId = owner.record_id;
        row.append(button, element("span", "muted", `${text(owner.ping, "0")} 坪`));
        card.append(row);
      });
      return card;
    });
    setChildren(container, cards.length ? cards : [emptyState("找不到符合的土地。")]);
  } catch (error) {
    setChildren(container, [emptyState(error.message)]);
  }
}

function isOverdue(item) {
  const due = String(item.due_date || item.next_follow_up || "");
  const status = item.status || item.follow_up_status || "";
  return due && due < new Date().toISOString().slice(0, 10) && status !== "完成";
}

async function loadFollowups() {
  const container = $("#followup-results");
  setChildren(container, [emptyState("正在載入追蹤提醒…")]);
  try {
    const result = await request("/api/v1/follow-ups?limit=500");
    const cards = (result.items || []).map(item => {
      const card = element("article", `result-card${isOverdue(item) ? " overdue" : ""}`);
      card.append(
        element("h3", "", text(item.owner_name || item.name, "未填姓名")),
        element("div", "card-meta", `${text(item.district, "未填地區")}・${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}`)
      );
      const metrics = element("div", "metric-row");
      metrics.append(metric("日期", item.due_date || item.next_follow_up), metric("狀態", item.status || item.follow_up_status));
      card.append(metrics);
      const button = element("button", "record-link", "查看與更新");
      button.type = "button";
      button.dataset.recordId = item.id;
      card.append(button);
      return card;
    });
    setChildren(container, cards.length ? cards : [emptyState("目前沒有追蹤提醒。")]);
  } catch (error) {
    setChildren(container, [emptyState(error.message)]);
  }
}

function renderRecord(record) {
  $("#record-title").textContent = `${text(record.owner_name, "未填姓名")}・${text(record.land_number, "未填地號")}`;
  const detail = $("#record-detail");
  const nodes = [];
  Object.entries(recordLabels).forEach(([key, label]) => {
    if (record[key] === undefined || record[key] === null || String(record[key]).trim() === "") return;
    nodes.push(element("dt", "", label), element("dd", "", record[key]));
  });
  setChildren(detail, nodes.length ? nodes : [element("dt", "", "資料"), element("dd", "", "沒有可顯示內容")]);
}

function renderContacts(items) {
  const container = $("#contact-results");
  const nodes = (items || []).map(item => {
    const row = element("article", "timeline-item");
    row.append(
      element("strong", "", `${text(item.contact_date || item.created_at, "未填日期")}・${text(item.method, "未填方式")}`),
      element("p", "", text(item.result, "未填結果"))
    );
    if (item.note) row.append(element("p", "", item.note));
    return row;
  });
  setChildren(container, nodes.length ? nodes : [element("p", "muted", "目前沒有聯絡紀錄。")]);
}

function fillFollowup(item) {
  const followup = item || {};
  $("#followup-date").value = followup.due_date || followup.next_follow_up || "";
  $("#followup-status").value = followup.status || followup.follow_up_status || "未處理";
  $("#followup-note").value = followup.note || "";
}

async function openRecord(recordId) {
  state.currentRecordId = Number(recordId);
  $("#record-sheet").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  setChildren($("#record-detail"), [element("dd", "", "正在載入資料…")]);
  try {
    const [record, contacts, followup] = await Promise.all([
      request(`/api/v1/records/${state.currentRecordId}`),
      request(`/api/v1/records/${state.currentRecordId}/contact-logs`),
      request(`/api/v1/records/${state.currentRecordId}/follow-up`)
    ]);
    renderRecord(record);
    renderContacts(contacts.items);
    fillFollowup(followup.item);
  } catch (error) {
    toast(error.message);
  }
}

function closeRecord() {
  $("#record-sheet").classList.add("hidden");
  document.body.style.overflow = "";
  state.currentRecordId = null;
}

async function submitContact(event) {
  event.preventDefault();
  if (!state.currentRecordId) return;
  const payload = {
    contact_date: $("#contact-date").value || null,
    method: $("#contact-method").value || null,
    result: $("#contact-result").value || null,
    next_follow_up: $("#contact-next").value || null,
    note: $("#contact-note").value || null
  };
  try {
    await request(`/api/v1/records/${state.currentRecordId}/contact-logs`, { method: "POST", body: JSON.stringify(payload) });
    $("#contact-result").value = "";
    $("#contact-note").value = "";
    const contacts = await request(`/api/v1/records/${state.currentRecordId}/contact-logs`);
    renderContacts(contacts.items);
    if (payload.next_follow_up) {
      $("#followup-date").value = payload.next_follow_up;
      state.loadedPages.delete("followups");
    }
    toast("已新增聯絡紀錄");
  } catch (error) {
    toast(error.message);
  }
}

async function submitFollowup(event) {
  event.preventDefault();
  if (!state.currentRecordId) return;
  const payload = {
    due_date: $("#followup-date").value || null,
    status: $("#followup-status").value,
    note: $("#followup-note").value || null
  };
  try {
    await request(`/api/v1/records/${state.currentRecordId}/follow-up`, { method: "PUT", body: JSON.stringify(payload) });
    state.loadedPages.delete("followups");
    state.loadedPages.delete("home");
    toast("已儲存追蹤提醒");
  } catch (error) {
    toast(error.message);
  }
}

async function restoreSession() {
  try {
    const health = await request("/health");
    updateConnection(true, health.backend === "postgresql" ? `已連線 PostgreSQL・v${health.version}` : "伺服器不是 PostgreSQL 模式");
  } catch (_error) {
    showLogin();
    return;
  }
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    const user = await request("/api/v1/auth/me");
    showApp(user);
  } catch (_error) {
    showLogin("請重新登入。");
  }
}

function bindEvents() {
  $("#login-form").addEventListener("submit", login);
  $("#user-button").addEventListener("click", logout);
  $("#owner-search-form").addEventListener("submit", searchOwners);
  $("#land-search-form").addEventListener("submit", searchLands);
  $("#refresh-dashboard").addEventListener("click", loadDashboard);
  $("#refresh-followups").addEventListener("click", loadFollowups);
  $("#contact-form").addEventListener("submit", submitContact);
  $("#followup-form").addEventListener("submit", submitFollowup);
  $$(".bottom-nav button").forEach(button => button.addEventListener("click", () => navigate(button.dataset.page)));
  $$('[data-go]').forEach(button => button.addEventListener("click", () => navigate(button.dataset.go)));
  $$('[data-close-sheet]').forEach(node => node.addEventListener("click", closeRecord));
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-record-id]");
    if (button) openRecord(button.dataset.recordId);
  });
  window.addEventListener("online", () => updateConnection(true));
  window.addEventListener("offline", () => updateConnection(false, "手機目前離線，資料不會寫入"));
  document.addEventListener("keydown", event => { if (event.key === "Escape") closeRecord(); });
  $("#contact-date").value = new Date().toISOString().slice(0, 10);
}

bindEvents();
restoreSession();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js", { scope: "/mobile/" }).catch(() => {}));
}
