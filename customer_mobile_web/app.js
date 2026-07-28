"use strict";

const state = {
  token: sessionStorage.getItem("lcs_access_token") || "",
  user: null,
  currentRecordId: null,
  currentFieldVisitItemId: null,
  loadedPages: new Set(),
  pendingAttachmentFiles: [],
  attachmentOriginalSizes: new Map(),
  attachmentUploadKeys: new Map(),
  attachmentUploadError: "",
  attachmentSelectionVersion: 0,
  attachmentProcessing: false,
  currentAttachments: [],
  thumbnailUrls: new Map(),
  photoPreviewItems: [],
  photoPreviewIndex: -1,
  photoPreviewUrl: "",
  photoPreviewRequestId: 0,
  currentPosition: null,
  fieldVisitRoute: null,
  fieldVisitIndex: 0,
  fieldActionIdempotencyKey: "",
  fieldActionSubmittedSignature: "",
  fieldActionSubmittedPayload: null,
  contactIdempotencyKey: "",
  contactSubmittedSignature: "",
  contactSubmittedPayload: null,
  fieldPlanSelection: new Set(),
  fieldPlanOrder: []
};

const MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024;
const PHOTO_COMPRESSION_THRESHOLD = 1.5 * 1024 * 1024;
const PHOTO_MAX_DIMENSION = 2048;

const pages = {
  home: "總覽",
  field: "今日外勤",
  owners: "地主搜尋",
  lands: "土地搜尋",
  followups: "追蹤提醒"
};

let lastFocusedElement = null;
let fieldActionLastFocusedElement = null;
let fieldPlanLastFocusedElement = null;

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

function maskIdentity(value) {
  const characters = Array.from(String(value ?? "").trim());
  if (!characters.length) return "—";
  if (characters.length <= 5) return characters.join("");
  return `${characters.slice(0, 4).join("")}${"*".repeat(characters.length - 5)}${characters.at(-1)}`;
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("zh-TW").format(number) : text(value);
}

function formatDate(value) {
  if (!value) return "未設定日期";
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? text(value)
    : new Intl.DateTimeFormat("zh-TW", { month: "short", day: "numeric", weekday: "short" }).format(date);
}

function formatFileSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "大小未知";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatAttachmentDate(value) {
  if (!value) return "日期未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? text(value, "日期未知")
    : new Intl.DateTimeFormat("zh-TW", {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(date);
}

function userInitial(value) {
  const name = String(value || "使用者").trim();
  return Array.from(name)[0] || "用";
}

function setButtonBusy(button, busy, busyText = "處理中…") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    return;
  }
  button.textContent = button.dataset.originalText || button.textContent;
  button.disabled = false;
  button.removeAttribute("aria-busy");
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
    const networkError = new Error("無法連線至自架伺服器，請確認電腦、API 與 Wi-Fi／VPN 都已連線。");
    networkError.isNetworkError = true;
    throw networkError;
  }

  updateConnection(true);
  if (response.status === 204) return null;

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/v1/auth/login") showLogin("登入已失效，請重新登入。");
    const error = new Error(apiErrorMessage(payload, `伺服器錯誤（${response.status}）`));
    error.status = response.status;
    error.path = path;
    throw error;
  }
  return payload;
}

async function requestBlob(path) {
  const headers = new Headers();
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);

  let response;
  try {
    response = await fetch(path, { headers, cache: "no-store" });
  } catch (_error) {
    updateConnection(false, "無法連線至自架伺服器");
    const networkError = new Error("無法連線至自架伺服器，請確認電腦、API 與 Wi-Fi／VPN 都已連線。");
    networkError.isNetworkError = true;
    throw networkError;
  }

  updateConnection(true);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) showLogin("登入已失效，請重新登入。");
    throw new Error(apiErrorMessage(payload, `附件讀取失敗（${response.status}）`));
  }
  return response.blob();
}

function updateConnection(online, message = "") {
  const banner = $("#connection-banner");
  banner.classList.toggle("online", online);
  banner.classList.toggle("offline", !online);
  banner.textContent = message || (online ? "已連線 PostgreSQL" : "目前離線");
  const status = $("#sidebar-status");
  if (status) status.textContent = online ? "PostgreSQL 已連線" : "目前無法連線";
  document.body.classList.toggle("is-offline", !online);
}

let toastTimer = null;
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 2800);
}

function formatLocationAccuracy(value) {
  const accuracy = Number(value);
  if (!Number.isFinite(accuracy) || accuracy < 0) return "精確度未知";
  return `約 ${Math.max(1, Math.round(accuracy))} 公尺`;
}

function localDateISO(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function idempotencyKey(action, itemId = "") {
  const randomPart = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `mobile-${action}-${itemId}-${randomPart}`.slice(0, 200);
}

function readSessionDraft(key) {
  try {
    return JSON.parse(sessionStorage.getItem(key) || "null");
  } catch (_error) {
    sessionStorage.removeItem(key);
    return null;
  }
}

function writeSessionDraft(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch (_error) {
    // The form remains intact even if Safari temporarily rejects session storage.
  }
}

function fieldActionDraftKey(itemId, action) {
  return `lcs_field_action_draft:${itemId}:${action}`;
}

function contactDraftKey() {
  return `lcs_contact_draft:${state.currentRecordId || 0}:${state.currentFieldVisitItemId || 0}`;
}

async function requestFieldLocation() {
  const button = $("#field-location-button");
  const status = $("#field-location-status");
  const detail = $("#field-location-detail");
  setButtonBusy(button, true, "正在定位…");
  status.textContent = "正在向手機取得 GPS 位置…";
  detail.textContent = "若是第一次使用，請在 Safari 的提示中選擇允許。";
  try {
    if (!window.LCSFieldVisit) throw new Error("外勤定位工具尚未載入，請重新整理頁面。");
    const position = await window.LCSFieldVisit.requestCurrentPosition();
    state.currentPosition = position;
    status.textContent = "定位成功，可以開始安排外勤路線。";
    detail.textContent = `${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}・${formatLocationAccuracy(position.accuracy_m)}`;
    $("#field-location-panel").classList.add("location-ready");
    toast("已取得目前位置");
  } catch (error) {
    state.currentPosition = null;
    status.textContent = error.message;
    detail.textContent = "你仍可使用原始行程順序，或調整權限後再按一次。";
    $("#field-location-panel").classList.remove("location-ready");
  } finally {
    setButtonBusy(button, false);
  }
}

function roleLabel(role) {
  return { admin: "管理員", editor: "編輯者", viewer: "唯讀" }[role] || text(role, "使用者");
}

function applyRole() {
  const canEdit = state.user && ["admin", "editor"].includes(state.user.role);
  $$(".editor-only").forEach(node => node.classList.toggle("hidden", !canEdit));
}

function canEdit() {
  return Boolean(state.user && ["admin", "editor"].includes(state.user.role));
}

function showLogin(message = "") {
  closeFieldPlan();
  closeFieldAction();
  closePhotoViewer();
  closeAttachmentEdit();
  releaseThumbnailUrls();
  state.token = "";
  state.user = null;
  state.currentRecordId = null;
  state.fieldVisitRoute = null;
  state.fieldVisitIndex = 0;
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
  $("#user-avatar").textContent = userInitial(user.display_name || user.username);
  const hour = new Date().getHours();
  const greeting = hour < 11 ? "早安" : hour < 18 ? "午安" : "晚安";
  $("#home-heading").textContent = `${greeting}，${user.display_name || user.username}`;
  $("#today-label").textContent = new Intl.DateTimeFormat("zh-TW", {
    year: "numeric", month: "long", day: "numeric", weekday: "long"
  }).format(new Date());
  applyRole();
  navigate("home", true);
}

async function login(event) {
  event.preventDefault();
  const button = $("#login-button");
  setButtonBusy(button, true, "登入中…");
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
    setButtonBusy(button, false);
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
  $$(".app-nav button, .mobile-nav button").forEach(button => {
    const active = button.dataset.page === page;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#page-title").textContent = pages[page];
  $("#breadcrumb-page").textContent = pages[page];
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (force || !state.loadedPages.has(page)) {
    state.loadedPages.add(page);
    if (page === "home") loadDashboard();
    if (page === "field") loadFieldVisit();
    if (page === "owners") searchOwners();
    if (page === "lands") searchLands();
    if (page === "followups") loadFollowups();
  }
}

const fieldVisitStatusLabels = Object.freeze({
  draft: "草稿",
  planned: "待拜訪",
  in_progress: "拜訪中",
  completed: "已完成",
  skipped: "已略過",
  postponed: "已延後",
  cancelled: "已取消"
});

function fieldVisitStatusLabel(value) {
  return fieldVisitStatusLabels[String(value || "").toLowerCase()] || text(value, "狀態未知");
}

function fieldVisitRemaining(item) {
  return ["planned", "in_progress", "postponed"].includes(String(item && item.status));
}

function routeItemIndex(route) {
  const items = route && route.items || [];
  const activeIndex = items.findIndex(item => item.status === "in_progress");
  if (activeIndex >= 0) return activeIndex;
  const plannedIndex = items.findIndex(item => item.status === "planned");
  if (plannedIndex >= 0) return plannedIndex;
  const postponedIndex = items.findIndex(item => item.status === "postponed");
  return postponedIndex >= 0 ? postponedIndex : Math.max(0, items.length - 1);
}

function fieldDistance(value) {
  if (value === null || value === undefined || String(value).trim() === "") return "尚未估算";
  const distance = Number(value);
  return Number.isFinite(distance) ? `${distance.toFixed(distance < 10 ? 1 : 0)} km` : "尚未估算";
}

function formatFieldVisitTime(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-TW", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(parsed);
}

function formatFieldVisitDuration(startedAt, completedAt) {
  if (!startedAt || !completedAt) return "—";
  const started = new Date(startedAt);
  const completed = new Date(completedAt);
  const elapsedMinutes = Math.floor((completed.getTime() - started.getTime()) / 60000);
  if (!Number.isFinite(elapsedMinutes) || elapsedMinutes < 0) return "—";
  if (elapsedMinutes < 1) return "少於 1 分";
  const hours = Math.floor(elapsedMinutes / 60);
  const minutes = elapsedMinutes % 60;
  if (!hours) return `${minutes} 分`;
  return minutes ? `${hours} 小時 ${minutes} 分` : `${hours} 小時`;
}

function renderFieldVisitCompletion(route, counts) {
  const summary = $("#field-completion-summary");
  const isCompleted = Boolean(route && route.status === "completed");
  summary.classList.toggle("hidden", !isCompleted);
  if (!isCompleted) return;

  $("#field-completion-total").textContent = formatNumber(counts.total);
  $("#field-completion-completed").textContent = formatNumber(counts.completed);
  $("#field-completion-skipped").textContent = formatNumber(counts.skipped);
  $("#field-completion-cancelled").textContent = formatNumber(counts.cancelled);
  $("#field-completion-distance").textContent = route.total_distance_km !== null
    && route.total_distance_km !== undefined
    && String(route.total_distance_km).trim() !== ""
    && Number.isFinite(Number(route.total_distance_km))
    ? Number(route.total_distance_km).toFixed(1)
    : "—";
  $("#field-completion-duration").textContent = formatFieldVisitDuration(
    route.started_at,
    route.completed_at
  );
  $("#field-completion-started").textContent = formatFieldVisitTime(route.started_at);
  $("#field-completion-ended").textContent = formatFieldVisitTime(route.completed_at);
  $("#field-completion-message").textContent = counts.completed
    ? `今天已完成 ${formatNumber(counts.completed)} 位地主的拜訪，可以回顧完整行程與紀錄。`
    : "今日行程已全部處理完成，可以回顧完整清單。";
}

function reviewFieldVisitItinerary() {
  const itinerary = $(".field-itinerary");
  if (!itinerary) return;
  itinerary.open = true;
  itinerary.scrollIntoView({ behavior: "smooth", block: "start" });
}

function safePhoneUrl(value) {
  const phone = String(value || "").replace(/[^\d+*#,;]/g, "");
  return phone ? `tel:${phone}` : "";
}

function fieldInfoRow(label, value) {
  const row = element("div", "field-info-row");
  row.append(element("span", "", label), element("strong", "", text(value)));
  return row;
}

function renderFieldVisitCurrent() {
  const route = state.fieldVisitRoute;
  const items = route && route.items || [];
  const container = $("#field-visit-current");
  if (!items.length) {
    setChildren(container, [emptyState("今日行程內沒有地主。")]);
    $("#field-visit-position").textContent = "0 / 0";
    $("#field-visit-previous").disabled = true;
    $("#field-visit-next").disabled = true;
    return;
  }
  state.fieldVisitIndex = Math.min(Math.max(0, state.fieldVisitIndex), items.length - 1);
  const item = items[state.fieldVisitIndex];
  const heading = element("div", "field-current-heading");
  const order = element("span", "field-order-badge", `第 ${item.route_order || state.fieldVisitIndex + 1} 站`);
  const status = element("span", `visit-status status-${item.status || "unknown"}`, fieldVisitStatusLabel(item.status));
  const priority = Number(item.priority) > 0
    ? element("span", "field-priority-badge", "優先拜訪")
    : null;
  heading.append(order, priority, status);

  const owner = element("h3", "field-owner-name", text(item.owner_name, "未填姓名"));
  const land = element(
    "p",
    "field-land-label",
    `${text(item.district, "未填地區")}・${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}`
  );
  const info = element("div", "field-info-grid");
  info.append(
    fieldInfoRow("登記次序", item.registration_order),
    fieldInfoRow("地主地址", item.address),
    fieldInfoRow("電話", item.phone),
    fieldInfoRow("路線距離", fieldDistance(item.estimated_distance_km))
  );

  const notes = element("div", "field-visit-notes");
  if (String(item.note || "").trim()) notes.append(fieldInfoRow("重要備註", item.note));
  if (String(item.last_contact || "").trim()) notes.append(fieldInfoRow("最近紀錄", item.last_contact));

  const actions = element("div", "field-primary-actions");
  const navigation = element("button", "primary-button", "開啟導航");
  navigation.type = "button";
  navigation.dataset.fieldNavigate = String(item.id);
  navigation.disabled = !String(item.address || "").trim()
    && !window.LCSFieldVisit.validCoordinates(item.latitude, item.longitude);
  actions.append(navigation);
  const phoneUrl = safePhoneUrl(item.phone);
  if (phoneUrl) {
    const call = element("a", "field-call-button", "撥打電話");
    call.href = phoneUrl;
    actions.append(call);
  }

  const recordActions = element("div", "field-record-actions");
  const addRecordAction = (sectionId, label, count) => {
    const button = element("button", "field-record-button");
    const copy = element("span", "", label);
    const badge = element("strong", "", formatNumber(Number(count) || 0));
    button.type = "button";
    button.dataset.fieldRecordId = String(item.ownership_id);
    button.dataset.fieldRecordSection = sectionId;
    button.dataset.fieldRouteItemId = String(item.id);
    button.append(copy, badge);
    recordActions.append(button);
  };
  addRecordAction(
    "contact-section",
    "拜訪紀錄",
    item.contact_log_count
  );
  addRecordAction(
    "attachment-section",
    "照片與附件",
    item.attachment_count
  );

  const statusActions = element("div", "field-status-actions editor-only");
  statusActions.classList.toggle("hidden", !canEdit());
  const activeItem = items.find(value => value.status === "in_progress");
  const activeElsewhere = activeItem && Number(activeItem.id) !== Number(item.id);
  const addStatusAction = (action, label, className = "") => {
    const button = element("button", className, label);
    button.type = "button";
    button.dataset.fieldAction = action;
    button.dataset.fieldActionItem = String(item.id);
    statusActions.append(button);
  };
  if (["planned", "postponed"].includes(item.status) && !activeElsewhere) {
    addStatusAction("start", "開始拜訪", "field-start-button");
  }
  if (item.status === "in_progress") {
    addStatusAction("complete", "完成拜訪", "field-complete-button");
  }
  if (["planned", "in_progress", "postponed"].includes(item.status)) {
    addStatusAction("skip", "略過", "field-skip-button");
  }
  if (["planned", "in_progress"].includes(item.status)) {
    addStatusAction("postpone", "延後", "field-postpone-button");
  }

  setChildren(container, [
    heading,
    owner,
    land,
    info,
    notes,
    actions,
    recordActions,
    statusActions.children.length ? statusActions : null
  ]);
  $("#field-visit-position").textContent = `${state.fieldVisitIndex + 1} / ${items.length}`;
  $("#field-visit-previous").disabled = state.fieldVisitIndex <= 0;
  $("#field-visit-next").disabled = state.fieldVisitIndex >= items.length - 1;
}

function selectFieldVisitItem(index) {
  state.fieldVisitIndex = Number(index);
  renderFieldVisitCurrent();
  $("#field-visit-current").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderFieldVisitList(items) {
  const nodes = items.map((item, index) => {
    const button = element("button", `field-list-item status-${item.status || "unknown"}`);
    button.type = "button";
    button.dataset.fieldItemIndex = String(index);
    const order = element("span", "field-list-order", String(item.route_order || index + 1));
    const copy = element("span", "field-list-copy");
    copy.append(
      element("strong", "", text(item.owner_name, "未填姓名")),
      element("small", "", `${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}`)
    );
    if (Number(item.priority) > 0) {
      copy.append(element("span", "field-priority-badge", "優先拜訪"));
    }
    button.append(order, copy, element("span", "field-list-status", fieldVisitStatusLabel(item.status)));
    return button;
  });
  setChildren($("#field-visit-list"), nodes.length ? nodes : [emptyState("今日行程內沒有地主。")]);
}

function renderFieldVisit() {
  const route = state.fieldVisitRoute;
  $("#field-visit-loading").classList.add("hidden");
  $("#field-visit-empty").classList.toggle("hidden", Boolean(route));
  $("#field-visit-workspace").classList.toggle("hidden", !route);
  const manageButton = $("#field-visit-manage");
  const hasRestorableItems = Boolean(
    route && (route.items || []).some(item => item.status === "cancelled")
  );
  manageButton.textContent = route ? "編輯行程" : "安排今日行程";
  manageButton.disabled = Boolean(
    route && (route.status === "cancelled"
      || (route.status === "completed" && !hasRestorableItems))
  );
  if (!route) {
    $("#field-completion-summary").classList.add("hidden");
    return;
  }

  const items = route.items || [];
  const completed = items.filter(item => item.status === "completed").length;
  const skipped = items.filter(item => item.status === "skipped").length;
  const cancelled = items.filter(item => item.status === "cancelled").length;
  const remaining = items.filter(fieldVisitRemaining).length;
  const progress = items.length ? Math.round((completed / items.length) * 100) : 0;
  $("#field-visit-date").textContent = formatDate(route.visit_date);
  $("#field-visit-title").textContent = text(route.title, "今日拜訪行程");
  $("#field-visit-route-status").textContent = fieldVisitStatusLabel(route.status);
  $("#field-visit-route-status").className = `visit-status status-${route.status || "unknown"}`;
  $("#field-progress-bar").style.width = `${progress}%`;
  $("#field-stat-total").textContent = formatNumber(items.length);
  $("#field-stat-completed").textContent = formatNumber(completed);
  $("#field-stat-remaining").textContent = formatNumber(remaining);
  $("#field-stat-skipped").textContent = formatNumber(skipped);
  $("#field-stat-distance").textContent = route.total_distance_km !== null
    && route.total_distance_km !== undefined
    && String(route.total_distance_km).trim() !== ""
    && Number.isFinite(Number(route.total_distance_km))
    ? Number(route.total_distance_km).toFixed(1)
    : "—";

  const startButton = $("#field-visit-start");
  const reoptimizeButton = $("#field-visit-reoptimize");
  const activeItem = items.find(item => item.status === "in_progress");
  startButton.disabled = remaining === 0 || route.status === "completed";
  startButton.textContent = activeItem ? "繼續外勤" : "開始外勤";
  reoptimizeButton.disabled = remaining < 2 || route.status !== "in_progress";
  reoptimizeButton.title = remaining < 2
    ? "至少需要兩位尚待拜訪的地主才能重新規劃"
    : route.status !== "in_progress" ? "開始外勤後即可重新規劃剩餘路線" : "";
  $("#field-start-title").textContent = activeItem
    ? `目前正在拜訪：${text(activeItem.owner_name, "未填姓名")}`
    : remaining ? "準備開始今天的外勤" : "今天的行程已處理完成";
  $("#field-start-detail").textContent = activeItem
    ? "按下後會直接回到目前拜訪中的地主。"
    : remaining ? "會先取得 GPS，再讓你確認路線。" : "可以查看完整清單與已完成紀錄。";

  renderFieldVisitCompletion(route, {
    total: items.length,
    completed,
    skipped,
    cancelled
  });
  renderFieldVisitCurrent();
  renderFieldVisitList(items);
  applyRole();
}

async function loadFieldVisit(options = {}) {
  const refreshButton = $("#field-visit-refresh");
  setButtonBusy(refreshButton, true, "更新中…");
  if (!options.quiet) {
    $("#field-visit-loading").classList.remove("hidden");
    $("#field-visit-empty").classList.add("hidden");
    $("#field-visit-workspace").classList.add("hidden");
  }
  try {
    const result = await request(`/api/v1/field-visits/today?visit_date=${localDateISO()}`);
    state.fieldVisitRoute = result.item || null;
    state.fieldVisitIndex = routeItemIndex(state.fieldVisitRoute);
    if (!state.fieldVisitRoute) {
      $("#field-visit-empty-message").textContent = canEdit()
        ? "今天尚未建立拜訪行程，可以直接從手機安排。"
        : "今天尚未建立拜訪行程。";
    }
    renderFieldVisit();
  } catch (error) {
    state.fieldVisitRoute = null;
    $("#field-visit-loading").classList.add("hidden");
    $("#field-visit-empty").textContent = error.message;
    $("#field-visit-empty").classList.remove("hidden");
    $("#field-visit-workspace").classList.add("hidden");
  } finally {
    setButtonBusy(refreshButton, false);
  }
}

function existingFieldVisitOwnershipIds() {
  return new Set(
    ((state.fieldVisitRoute && state.fieldVisitRoute.items) || [])
      .map(item => Number(item.ownership_id))
      .filter(Number.isFinite)
  );
}

function activeFieldPlanItems() {
  return ((state.fieldVisitRoute && state.fieldVisitRoute.items) || [])
    .filter(item => ["planned", "in_progress", "postponed"].includes(String(item.status)));
}

function resetFieldPlanOrder() {
  state.fieldPlanOrder = activeFieldPlanItems()
    .slice()
    .sort((left, right) => Number(left.route_order) - Number(right.route_order))
    .map(item => Number(item.id));
}

function renderFieldPlanCurrent() {
  const route = state.fieldVisitRoute;
  const section = $("#field-plan-current-section");
  section.classList.toggle("hidden", !route);
  if (!route) {
    setChildren($("#field-plan-current"), []);
    $("#field-plan-order-save").disabled = true;
    $("#field-plan-unlock-order").disabled = true;
    $("#field-plan-unlock-order").textContent = "目前為自動排序";
    return;
  }
  const itemsById = new Map(
    activeFieldPlanItems().map(item => [Number(item.id), item])
  );
  const rows = state.fieldPlanOrder.map((itemId, index) => {
    const item = itemsById.get(Number(itemId));
    if (!item) return null;
    const row = element(
      "div",
      item.is_order_locked
        ? "field-plan-current-item is-order-locked"
        : "field-plan-current-item"
    );
    const order = element("span", "field-plan-current-order", String(index + 1));
    const copy = element("span", "field-plan-result-copy");
    copy.append(
      element("strong", "", text(item.owner_name, "未填姓名")),
      element("small", "", `${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}`)
    );
    if (Number(item.priority) > 0) {
      copy.append(element("span", "field-priority-badge", "優先拜訪"));
    }
    if (item.is_order_locked) {
      copy.append(element("span", "field-order-lock-badge", "固定順序"));
    }
    const controls = element("span", "field-plan-current-controls");
    const moveUp = element("button", "", "↑");
    moveUp.type = "button";
    moveUp.title = "往前移";
    moveUp.dataset.fieldPlanMove = "-1";
    moveUp.dataset.fieldPlanItem = String(item.id);
    moveUp.disabled = index === 0;
    const moveDown = element("button", "", "↓");
    moveDown.type = "button";
    moveDown.title = "往後移";
    moveDown.dataset.fieldPlanMove = "1";
    moveDown.dataset.fieldPlanItem = String(item.id);
    moveDown.disabled = index === state.fieldPlanOrder.length - 1;
    controls.append(moveUp, moveDown);
    if (["planned", "postponed"].includes(item.status)) {
      const priority = element(
        "button",
        Number(item.priority) > 0 ? "field-plan-priority is-active" : "field-plan-priority",
        Number(item.priority) > 0 ? "取消優先" : "設為優先"
      );
      priority.type = "button";
      priority.dataset.fieldPlanPriority = String(item.id);
      priority.dataset.fieldPlanPriorityValue = Number(item.priority) > 0 ? "0" : "10";
      controls.append(priority);
    }
    if (item.status === "planned") {
      const remove = element("button", "field-plan-remove", "移除");
      remove.type = "button";
      remove.dataset.fieldPlanRemove = String(item.id);
      controls.append(remove);
    } else {
      controls.append(element("small", "", fieldVisitStatusLabel(item.status)));
    }
    row.append(order, copy, controls);
    return row;
  }).filter(Boolean);
  const cancelledRows = ((route && route.items) || [])
    .filter(item => item.status === "cancelled")
    .map(item => {
      const row = element("div", "field-plan-current-item is-cancelled");
      const order = element("span", "field-plan-current-order", "—");
      const copy = element("span", "field-plan-result-copy");
      copy.append(
        element("strong", "", text(item.owner_name, "未填姓名")),
        element("small", "", `${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}・已移除`)
      );
      const controls = element("span", "field-plan-current-controls");
      const restore = element("button", "field-plan-restore", "恢復");
      restore.type = "button";
      restore.dataset.fieldPlanRestore = String(item.id);
      controls.append(restore);
      row.append(order, copy, controls);
      return row;
    });
  setChildren(
    $("#field-plan-current"),
    rows.length || cancelledRows.length
      ? [...rows, ...cancelledRows]
      : [emptyState("目前沒有可調整的待拜訪資料。")]
  );
  $("#field-plan-order-save").disabled = rows.length < 2;
  const lockedCount = activeFieldPlanItems()
    .filter(item => Boolean(item.is_order_locked))
    .length;
  const unlockButton = $("#field-plan-unlock-order");
  unlockButton.disabled = lockedCount === 0;
  unlockButton.textContent = lockedCount > 0
    ? `恢復自動排序（${formatNumber(lockedCount)}）`
    : "目前為自動排序";
}

function moveFieldPlanItem(itemId, direction) {
  const index = state.fieldPlanOrder.indexOf(Number(itemId));
  const target = index + Number(direction);
  if (index < 0 || target < 0 || target >= state.fieldPlanOrder.length) return;
  [state.fieldPlanOrder[index], state.fieldPlanOrder[target]] = [
    state.fieldPlanOrder[target],
    state.fieldPlanOrder[index]
  ];
  renderFieldPlanCurrent();
}

async function updateFieldPlanPriority(itemId, priority, button) {
  const item = ((state.fieldVisitRoute && state.fieldVisitRoute.items) || [])
    .find(value => Number(value.id) === Number(itemId));
  if (!item || !["planned", "postponed"].includes(item.status)) {
    toast("只有尚待拜訪的地主可以調整優先順序。");
    return;
  }
  const nextPriority = Number(priority) > 0 ? 10 : 0;
  setButtonBusy(button, true, "儲存中…");
  try {
    await request(`/api/v1/field-visit-items/${item.id}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey("item-priority", item.id) },
      body: JSON.stringify({
        priority: nextPriority,
        is_order_locked: nextPriority > 0 ? false : null
      })
    });
    await loadFieldVisit({ quiet: true });
    resetFieldPlanOrder();
    renderFieldPlanCurrent();
    toast(nextPriority > 0
      ? "已設為優先拜訪；重新規劃時會優先安排"
      : "已取消優先拜訪");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

async function saveFieldPlanOrder() {
  const route = state.fieldVisitRoute;
  if (!route || state.fieldPlanOrder.length < 2) return;
  const button = $("#field-plan-order-save");
  setButtonBusy(button, true, "儲存中…");
  try {
    await request(`/api/v1/field-visits/${route.id}/reorder`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("manual-reorder", route.id) },
      body: JSON.stringify({
        items: state.fieldPlanOrder.map(itemId => ({
          item_id: itemId,
          is_order_locked: true
        }))
      })
    });
    await loadFieldVisit({ quiet: true });
    resetFieldPlanOrder();
    renderFieldPlanCurrent();
    toast("已儲存今日拜訪順序");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

async function unlockFieldPlanOrder() {
  const route = state.fieldVisitRoute;
  const lockedCount = activeFieldPlanItems()
    .filter(item => Boolean(item.is_order_locked))
    .length;
  if (!route || lockedCount === 0 || state.fieldPlanOrder.length === 0) {
    toast("目前沒有固定順序");
    return;
  }
  if (!confirm(
    `要解除 ${formatNumber(lockedCount)} 筆固定順序嗎？\n\n` +
    "目前顯示的順序不會立即改變；解除後可按「重新規劃路線」預覽新的自動順序。"
  )) return;
  const button = $("#field-plan-unlock-order");
  setButtonBusy(button, true, "解除中…");
  try {
    await request(`/api/v1/field-visits/${route.id}/reorder`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("unlock-order", route.id) },
      body: JSON.stringify({
        items: state.fieldPlanOrder.map(itemId => ({
          item_id: itemId,
          is_order_locked: false
        }))
      })
    });
    await loadFieldVisit({ quiet: true });
    resetFieldPlanOrder();
    renderFieldPlanCurrent();
    toast("已解除固定順序，可重新規劃路線");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
    renderFieldPlanCurrent();
  }
}

async function removeFieldPlanItem(itemId, button) {
  const item = ((state.fieldVisitRoute && state.fieldVisitRoute.items) || [])
    .find(value => Number(value.id) === Number(itemId));
  if (!item || item.status !== "planned") {
    toast("只有尚未開始的資料可以移除。");
    return;
  }
  if (!confirm(`要將「${text(item.owner_name, "未填姓名")}」移出今日行程嗎？`)) return;
  setButtonBusy(button, true, "移除中…");
  try {
    await request(`/api/v1/field-visit-items/${item.id}/cancel`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("cancel-item", item.id) },
      body: JSON.stringify({ note: "從今日行程移除" })
    });
    await loadFieldVisit({ quiet: true });
    resetFieldPlanOrder();
    renderFieldPlanCurrent();
    $("#field-plan-existing").textContent =
      `目前行程已有 ${formatNumber((state.fieldVisitRoute.items || []).filter(value => value.status !== "cancelled").length)} 筆資料。`;
    toast("已從今日行程移除");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

async function restoreFieldPlanItem(itemId, button) {
  const item = ((state.fieldVisitRoute && state.fieldVisitRoute.items) || [])
    .find(value => Number(value.id) === Number(itemId));
  if (!item || item.status !== "cancelled") {
    toast("這筆資料目前無法恢復。");
    return;
  }
  setButtonBusy(button, true, "恢復中…");
  try {
    await request(`/api/v1/field-visit-items/${item.id}/restore`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("restore-item", item.id) },
      body: JSON.stringify({ note: "恢復至今日行程" })
    });
    await loadFieldVisit({ quiet: true });
    resetFieldPlanOrder();
    renderFieldPlanCurrent();
    $("#field-plan-existing").textContent =
      `目前行程已有 ${formatNumber((state.fieldVisitRoute.items || []).filter(value => value.status !== "cancelled").length)} 筆資料。`;
    toast("已恢復至今日行程");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

function updateFieldPlanSelection() {
  const count = state.fieldPlanSelection.size;
  $("#field-plan-selected").textContent = `已選取 ${formatNumber(count)} 筆`;
  $("#field-plan-submit").disabled = count === 0;
}

function fieldPlanResult(record, existingIds) {
  const recordId = Number(record.id);
  const alreadyAdded = existingIds.has(recordId);
  const label = element("label", `field-plan-result${alreadyAdded ? " is-existing" : ""}`);
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = String(recordId);
  checkbox.dataset.fieldPlanRecord = String(recordId);
  checkbox.disabled = alreadyAdded;
  checkbox.checked = state.fieldPlanSelection.has(recordId);
  const copy = element("span", "field-plan-result-copy");
  copy.append(
    element("strong", "", text(record.owner_name, "未填姓名")),
    element(
      "small",
      "",
      `${text(record.district, "未填地區")}・${text(record.section, "未填地段")}・${text(record.land_number, "未填地號")}`
    ),
    element("small", "", `地址：${text(record.address)}`)
  );
  const status = element("span", "field-plan-result-status", alreadyAdded ? "已在行程" : "選取");
  label.append(checkbox, copy, status);
  return label;
}

async function searchFieldPlanRecords(event) {
  if (event) event.preventDefault();
  const query = $("#field-plan-query").value.trim();
  if (!query) {
    setChildren($("#field-plan-results"), [emptyState("請輸入姓名、地段、地號或地址。")]);
    $("#field-plan-query").focus();
    return;
  }
  const button = $("#field-plan-search-button");
  setButtonBusy(button, true, "搜尋中…");
  setChildren($("#field-plan-results"), [emptyState("正在搜尋可加入的資料…")]);
  try {
    const result = await request(`/api/v1/records?q=${encodeURIComponent(query)}&limit=100`);
    const existingIds = existingFieldVisitOwnershipIds();
    const rows = (result.items || []).map(record => fieldPlanResult(record, existingIds));
    setChildren(
      $("#field-plan-results"),
      rows.length ? rows : [emptyState("找不到符合的資料。")]
    );
  } catch (error) {
    setChildren($("#field-plan-results"), [emptyState(error.message)]);
  } finally {
    setButtonBusy(button, false);
  }
}

function openFieldPlan() {
  if (!canEdit()) return;
  const route = state.fieldVisitRoute;
  const hasRestorableItems = Boolean(
    route && (route.items || []).some(item => item.status === "cancelled")
  );
  if (
    route
    && (route.status === "cancelled"
      || (route.status === "completed" && !hasRestorableItems))
  ) {
    toast("已完成的行程不能再加入地主。");
    return;
  }
  const canAddItems = !route || !["completed", "cancelled"].includes(route.status);
  fieldPlanLastFocusedElement = document.activeElement;
  state.fieldPlanSelection.clear();
  $("#field-plan-heading").textContent = route ? "加入地主到今日行程" : "安排今日行程";
  $("#field-plan-title-row").classList.toggle("hidden", Boolean(route));
  $("#field-plan-add-section").classList.toggle("hidden", !canAddItems);
  $("#field-plan-title").value = route ? text(route.title, "今日拜訪行程") : "今日拜訪行程";
  $("#field-plan-query").value = "";
  $("#field-plan-existing").textContent = route
    ? `目前行程已有 ${formatNumber((route.items || []).filter(item => item.status !== "cancelled").length)} 筆資料。`
    : "選取資料後，系統會自動建立今天的行程。";
  resetFieldPlanOrder();
  renderFieldPlanCurrent();
  setChildren($("#field-plan-results"), [emptyState("請先輸入條件搜尋要加入的資料。")]);
  updateFieldPlanSelection();
  $("#field-plan-dialog").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  if (canAddItems) $("#field-plan-query").focus();
  else $("#field-plan-current").focus();
}

function closeFieldPlan() {
  const dialog = $("#field-plan-dialog");
  if (!dialog || dialog.classList.contains("hidden")) return;
  dialog.classList.add("hidden");
  document.body.style.overflow = "";
  state.fieldPlanSelection.clear();
  state.fieldPlanOrder = [];
  updateFieldPlanSelection();
  if (fieldPlanLastFocusedElement && document.contains(fieldPlanLastFocusedElement)) {
    fieldPlanLastFocusedElement.focus();
  }
}

async function submitFieldPlan() {
  if (!canEdit() || state.fieldPlanSelection.size === 0) return;
  const button = $("#field-plan-submit");
  setButtonBusy(button, true, "加入中…");
  try {
    let routeId = Number(state.fieldVisitRoute && state.fieldVisitRoute.id);
    if (!routeId) {
      const payload = {
        visit_date: localDateISO(),
        title: $("#field-plan-title").value.trim() || "今日拜訪行程"
      };
      if (state.currentPosition) {
        payload.start_latitude = state.currentPosition.latitude;
        payload.start_longitude = state.currentPosition.longitude;
      }
      const created = await request("/api/v1/field-visits", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("create-route", localDateISO()) },
        body: JSON.stringify(payload)
      });
      routeId = Number(created.id);
      if (!routeId) throw new Error("伺服器沒有回傳今日行程編號。");
    }
    const result = await request(`/api/v1/field-visits/${routeId}/items`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("add-route-items", routeId) },
      body: JSON.stringify({
        items: Array.from(state.fieldPlanSelection).map(ownershipId => ({
          ownership_id: ownershipId
        }))
      })
    });
    closeFieldPlan();
    await loadFieldVisit({ quiet: true });
    const added = Number(result.added_count) || 0;
    const existing = Number(result.existing_count) || 0;
    toast(existing
      ? `已加入 ${added} 筆，另有 ${existing} 筆原本就在行程內`
      : `已加入 ${added} 筆今日行程`);
  } catch (error) {
    if (
      error.status === 404
      && String(error.path || "").startsWith("/api/v1/field-visits")
    ) {
      toast("手機頁面已更新，但伺服器程式仍是舊版。請更新並重新啟動家中伺服器。");
    } else {
      toast(error.message);
    }
  } finally {
    setButtonBusy(button, false);
    updateFieldPlanSelection();
  }
}

async function startFieldVisitItem(item, position) {
  const body = {
    latitude: position ? position.latitude : null,
    longitude: position ? position.longitude : null,
    note: ""
  };
  await request(`/api/v1/field-visit-items/${item.id}/start`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey("start", item.id) },
    body: JSON.stringify(body)
  });
}

async function startFieldWork() {
  const button = $("#field-visit-start");
  const route = state.fieldVisitRoute;
  if (!route) return;
  const current = (route.items || []).find(item => item.status === "in_progress");
  if (current) {
    state.fieldVisitIndex = route.items.indexOf(current);
    renderFieldVisitCurrent();
    return;
  }
  const remaining = (route.items || []).filter(fieldVisitRemaining);
  if (!remaining.length) {
    toast("今天沒有尚待拜訪的地主");
    return;
  }

  setButtonBusy(button, true, "正在準備…");
  let position = null;
  try {
    try {
      position = await window.LCSFieldVisit.requestCurrentPosition();
      state.currentPosition = position;
    } catch (locationError) {
      const useOriginalOrder = confirm(`${locationError.message}\n\n是否沿用原始行程順序開始外勤？`);
      if (!useOriginalOrder) return;
    }

    if (position) {
      const payload = {
        current_latitude: position.latitude,
        current_longitude: position.longitude,
        keep_current_item_first: true,
        current_item_id: null
      };
      const preview = await request(`/api/v1/field-visits/${route.id}/optimize/preview`, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      const hasDistance = preview.total_distance_km !== null
        && preview.total_distance_km !== undefined
        && String(preview.total_distance_km).trim() !== "";
      const distance = Number(preview.total_distance_km);
      const distanceLabel = hasDistance && Number.isFinite(distance)
        ? `，預估 ${distance.toFixed(1)} 公里`
        : "";
      if (!confirm(`已依目前位置排好 ${preview.items.length} 位地主${distanceLabel}。確定套用並開始外勤嗎？`)) return;
      await request(`/api/v1/field-visits/${route.id}/optimize`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("optimize", route.id) },
        body: JSON.stringify({ ...payload, plan_token: preview.plan_token })
      });
      await loadFieldVisit({ quiet: true });
    }

    const refreshedRoute = state.fieldVisitRoute || route;
    const first = (refreshedRoute.items || []).find(fieldVisitRemaining);
    if (!first) return;
    setButtonBusy(button, true, "正在開始…");
    await startFieldVisitItem(first, position);
    await loadFieldVisit({ quiet: true });
    toast(`已開始拜訪 ${text(first.owner_name, "地主")}`);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

async function reoptimizeRemainingFieldVisit() {
  const button = $("#field-visit-reoptimize");
  const route = state.fieldVisitRoute;
  if (!route || !canEdit()) return;
  const remaining = (route.items || []).filter(fieldVisitRemaining);
  if (remaining.length < 2) {
    toast("至少需要兩位尚待拜訪的地主才能重新規劃");
    return;
  }
  const activeItem = remaining.find(item => item.status === "in_progress") || null;
  setButtonBusy(button, true, "正在取得位置…");
  try {
    const position = await window.LCSFieldVisit.requestCurrentPosition();
    state.currentPosition = position;
    const payload = {
      current_latitude: position.latitude,
      current_longitude: position.longitude,
      keep_current_item_first: true,
      current_item_id: activeItem ? Number(activeItem.id) : null
    };
    button.textContent = "正在規劃…";
    const preview = await request(`/api/v1/field-visits/${route.id}/optimize/preview`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const distance = Number(preview.total_distance_km);
    const distanceLabel = Number.isFinite(distance)
      ? `，預估剩餘 ${distance.toFixed(1)} 公里`
      : "";
    const excludedCount = Array.isArray(preview.excluded_item_ids)
      ? preview.excluded_item_ids.length
      : 0;
    const protectedLabel = activeItem
      ? `\n目前拜訪中的「${text(activeItem.owner_name, "地主")}」會保留在第一位。`
      : "";
    const excludedLabel = excludedCount
      ? `\n已完成、略過或取消的 ${excludedCount} 筆資料不會變動。`
      : "";
    if (!confirm(
      `將依目前位置重新安排 ${preview.items.length} 位尚待拜訪的地主${distanceLabel}。`
      + `${protectedLabel}${excludedLabel}\n\n確定套用新順序嗎？`
    )) return;
    await request(`/api/v1/field-visits/${route.id}/optimize`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("reoptimize", route.id) },
      body: JSON.stringify({ ...payload, plan_token: preview.plan_token })
    });
    await loadFieldVisit({ quiet: true });
    toast(`已重新規劃 ${preview.items.length} 位地主的剩餘路線`);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
    if (state.fieldVisitRoute) renderFieldVisit();
  }
}

async function openFieldNavigation(itemId) {
  const item = (state.fieldVisitRoute && state.fieldVisitRoute.items || [])
    .find(value => Number(value.id) === Number(itemId));
  if (!item) return;
  let origin = state.currentPosition;
  try {
    if (!origin || !window.LCSFieldVisit.validCoordinates(
      origin.latitude,
      origin.longitude
    )) {
      try {
        origin = await window.LCSFieldVisit.requestCurrentPosition({
          timeout: 8000,
          maximumAge: 60000
        });
        state.currentPosition = origin;
      } catch (_locationError) {
        origin = null;
      }
    }
    window.LCSFieldVisit.openGoogleMapsNavigation(item, origin);
  } catch (error) {
    toast(error.message);
  }
}

const fieldActionLabels = Object.freeze({
  start: { title: "開始拜訪", submit: "確認開始" },
  complete: { title: "完成拜訪", submit: "儲存並前往下一位" },
  skip: { title: "略過這位地主", submit: "確認略過" },
  postpone: { title: "延後拜訪", submit: "確認延後" }
});

function defaultPostponedLocalValue() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function saveFieldActionDraft() {
  const itemId = Number($("#field-action-item-id").value);
  const action = $("#field-action-name").value;
  if (!itemId || !fieldActionLabels[action]) return;
  writeSessionDraft(fieldActionDraftKey(itemId, action), {
    note: $("#field-action-note").value,
    postponed_until: $("#field-action-postponed-until").value,
    idempotency_key: state.fieldActionIdempotencyKey,
    submitted_signature: state.fieldActionSubmittedSignature,
    submitted_payload: state.fieldActionSubmittedPayload
  });
}

function clearFieldActionDraft(itemId, action) {
  sessionStorage.removeItem(fieldActionDraftKey(itemId, action));
  state.fieldActionIdempotencyKey = "";
  state.fieldActionSubmittedSignature = "";
  state.fieldActionSubmittedPayload = null;
}

function openFieldAction(action, itemId, trigger = null) {
  const config = fieldActionLabels[action];
  const item = (state.fieldVisitRoute && state.fieldVisitRoute.items || [])
    .find(value => Number(value.id) === Number(itemId));
  if (!config || !item || !canEdit()) return;
  fieldActionLastFocusedElement = trigger || document.activeElement;
  $("#field-action-title").textContent = config.title;
  $("#field-action-owner").textContent = `${text(item.owner_name, "未填姓名")}・${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}`;
  $("#field-action-item-id").value = String(item.id);
  $("#field-action-name").value = action;
  const draft = readSessionDraft(fieldActionDraftKey(item.id, action));
  $("#field-action-note").value = draft && typeof draft.note === "string" ? draft.note : "";
  state.fieldActionIdempotencyKey = draft && draft.idempotency_key
    ? String(draft.idempotency_key)
    : idempotencyKey(action, item.id);
  state.fieldActionSubmittedSignature = draft && draft.submitted_signature
    ? String(draft.submitted_signature)
    : "";
  state.fieldActionSubmittedPayload = draft && draft.submitted_payload
    ? draft.submitted_payload
    : null;
  $("#field-action-submit").textContent = config.submit;
  const postponeRow = $("#field-action-postpone-row");
  const postponeInput = $("#field-action-postponed-until");
  postponeRow.classList.toggle("hidden", action !== "postpone");
  postponeInput.required = action === "postpone";
  postponeInput.value = action === "postpone"
    ? (draft && typeof draft.postponed_until === "string" && draft.postponed_until
      ? draft.postponed_until
      : defaultPostponedLocalValue())
    : "";
  $("#field-action-location-note").textContent = "送出時會嘗試附上目前 GPS；定位失敗仍可正常儲存。";
  $("#field-action-dialog").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  if (action === "postpone") postponeInput.focus();
  else $("#field-action-note").focus();
}

function closeFieldAction() {
  const dialog = $("#field-action-dialog");
  if (!dialog || dialog.classList.contains("hidden")) return;
  dialog.classList.add("hidden");
  if ($("#record-sheet").classList.contains("hidden")) document.body.style.overflow = "";
  if (fieldActionLastFocusedElement && document.contains(fieldActionLastFocusedElement)) {
    fieldActionLastFocusedElement.focus();
  }
  fieldActionLastFocusedElement = null;
}

async function submitFieldAction(event) {
  event.preventDefault();
  const action = $("#field-action-name").value;
  const itemId = Number($("#field-action-item-id").value);
  if (!fieldActionLabels[action] || !itemId) return;
  const button = $("#field-action-submit");
  setButtonBusy(button, true, "正在儲存…");
  let position = null;
  try {
    try {
      position = await window.LCSFieldVisit.requestCurrentPosition({
        timeout: 5000,
        maximumAge: 60000
      });
      state.currentPosition = position;
      $("#field-action-location-note").textContent = `已附上目前位置・${formatLocationAccuracy(position.accuracy_m)}`;
    } catch (_locationError) {
      $("#field-action-location-note").textContent = "未取得 GPS，將只儲存狀態、時間與備註。";
    }

    let postponedUntil = null;
    if (action === "postpone") {
      const localValue = $("#field-action-postponed-until").value;
      if (!localValue) {
        $("#field-action-postponed-until").focus();
        throw new Error("請選擇延後日期與時間。");
      }
      const parsed = new Date(localValue);
      if (Number.isNaN(parsed.getTime())) throw new Error("延後日期格式不正確。");
      postponedUntil = parsed.toISOString();
    }
    const semanticSignature = JSON.stringify({
      note: $("#field-action-note").value.trim(),
      postponed_until: postponedUntil
    });
    let payload = {
      latitude: position ? position.latitude : null,
      longitude: position ? position.longitude : null,
      note: $("#field-action-note").value.trim(),
      postponed_until: postponedUntil
    };
    if (
      state.fieldActionIdempotencyKey
      && state.fieldActionSubmittedSignature === semanticSignature
      && state.fieldActionSubmittedPayload
    ) {
      payload = state.fieldActionSubmittedPayload;
    } else {
      state.fieldActionIdempotencyKey = idempotencyKey(action, itemId);
      state.fieldActionSubmittedPayload = payload;
    }
    state.fieldActionSubmittedSignature = semanticSignature;
    saveFieldActionDraft();
    await request(`/api/v1/field-visit-items/${itemId}/${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": state.fieldActionIdempotencyKey },
      body: JSON.stringify(payload)
    });
    clearFieldActionDraft(itemId, action);
    closeFieldAction();
    await loadFieldVisit({ quiet: true });
    const routeCompleted = state.fieldVisitRoute
      && state.fieldVisitRoute.status === "completed";
    const success = routeCompleted && ["complete", "skip"].includes(action)
      ? "今日行程已全部處理完成"
      : {
          start: "已開始拜訪",
          complete: "已完成拜訪，已前往下一位",
          skip: "已略過，已前往下一位",
          postpone: "已延後，已前往下一位"
        }[action];
    toast(success);
  } catch (error) {
    saveFieldActionDraft();
    toast(error.isNetworkError ? "儲存失敗，內容已保留，可直接重新送出。" : error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

async function loadDashboard() {
  const button = $("#refresh-dashboard");
  setButtonBusy(button, true, "更新中…");
  try {
    const [records, owners, lands, followups] = await Promise.all([
      request("/api/v1/records?limit=1"),
      request("/api/v1/owners?limit=1"),
      request("/api/v1/lands?limit=1"),
      request("/api/v1/follow-ups?limit=500")
    ]);
    $("#stat-records").textContent = formatNumber(records.total);
    $("#stat-owners").textContent = formatNumber(owners.total);
    $("#stat-lands").textContent = formatNumber(lands.total);
    const pendingCount = (followups.items || []).filter(item => {
      const status = item.status || item.follow_up_status || "";
      return status !== "完成";
    }).length;
    $("#stat-followups").textContent = formatNumber(pendingCount);
    const navCount = $("#nav-followup-count");
    navCount.textContent = formatNumber(pendingCount);
    navCount.classList.toggle("hidden", pendingCount === 0);
    $("#last-sync-time").textContent = `最後同步：${new Intl.DateTimeFormat("zh-TW", { hour: "2-digit", minute: "2-digit" }).format(new Date())}`;
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
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
  const button = $("#owner-search-form button[type='submit']");
  setButtonBusy(button, true, "搜尋中…");
  const container = $("#owner-results");
  setChildren(container, [emptyState("正在查詢地主…")]);
  try {
    const query = encodeURIComponent($("#owner-query").value.trim());
    const result = await request(`/api/v1/owners?q=${query}&limit=100`);
    $("#owner-count").textContent = `找到 ${formatNumber(result.total)} 位地主`;
    const cards = (result.items || []).map(owner => {
      const card = element("article", "result-card");
      const heading = element("h3", "", text(owner.name, "未填姓名"));
      const meta = element("div", "card-meta");
      meta.append(
        element("span", "", `身分證：${maskIdentity(owner.external_id)}`),
        element("span", "", `地址：${text(owner.address)}`)
      );
      const metrics = element("div", "metric-row");
      metrics.append(
        metric("土地", formatNumber(owner.land_count)),
        metric("持分", formatNumber(owner.record_count)),
        metric("坪數", formatNumber(owner.total_ping)),
        metric("現值", formatNumber(owner.total_declared_value))
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
  } finally {
    setButtonBusy(button, false);
  }
}

async function searchLands(event) {
  if (event) event.preventDefault();
  const button = $("#land-search-form button[type='submit']");
  setButtonBusy(button, true, "搜尋中…");
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
    $("#land-count").textContent = `找到 ${formatNumber(result.total)} 筆土地`;
    const cards = (result.items || []).map(land => {
      const card = element("article", "result-card");
      card.append(element("h3", "", `${text(land.district, "未填地區")}・${text(land.section, "未填地段")}・${text(land.land_number, "未填地號")}`));
      const metrics = element("div", "metric-row");
      metrics.append(metric("面積㎡", formatNumber(land.area)), metric("公告現值", formatNumber(land.declared_value)), metric("地主", formatNumber((land.owners || []).length)));
      card.append(metrics);
      (land.owners || []).forEach(owner => {
        const row = element("div", "owner-buttons");
        const button = element("button", "record-link", `${text(owner.name, "未填姓名")}・${text(owner.numerator, "?")}/${text(owner.denominator, "?")}`);
        button.type = "button";
        button.dataset.recordId = owner.record_id;
        row.append(button, element("span", "muted", `${formatNumber(owner.ping || 0)} 坪`));
        card.append(row);
      });
      return card;
    });
    setChildren(container, cards.length ? cards : [emptyState("找不到符合的土地。")]);
  } catch (error) {
    setChildren(container, [emptyState(error.message)]);
  } finally {
    setButtonBusy(button, false);
  }
}

function isOverdue(item) {
  const due = String(item.due_date || item.next_follow_up || "");
  const status = item.status || item.follow_up_status || "";
  return due && due < new Date().toISOString().slice(0, 10) && status !== "完成";
}

async function loadFollowups() {
  const refreshButton = $("#refresh-followups");
  setButtonBusy(refreshButton, true, "更新中…");
  const container = $("#followup-results");
  setChildren(container, [emptyState("正在載入追蹤提醒…")]);
  try {
    const result = await request("/api/v1/follow-ups?limit=500");
    const items = [...(result.items || [])].sort((a, b) => {
      if (isOverdue(a) !== isOverdue(b)) return isOverdue(a) ? -1 : 1;
      return String(a.due_date || a.next_follow_up || "9999").localeCompare(String(b.due_date || b.next_follow_up || "9999"));
    });
    const cards = items.map(item => {
      const card = element("article", `result-card${isOverdue(item) ? " overdue" : ""}`);
      card.append(
        element("h3", "", text(item.owner_name || item.name, "未填姓名")),
        element("div", "card-meta", `${text(item.district, "未填地區")}・${text(item.section, "未填地段")}・${text(item.land_number, "未填地號")}`)
      );
      const metrics = element("div", "metric-row");
      metrics.append(metric("日期", formatDate(item.due_date || item.next_follow_up)), metric("狀態", item.status || item.follow_up_status));
      card.append(metrics);
      const button = element("button", "record-link", "查看與更新");
      button.type = "button";
      button.dataset.recordId = item.id;
      card.append(button);
      return card;
    });
    setChildren(container, cards.length ? cards : [emptyState("目前沒有追蹤提醒。")]);
    const pendingCount = items.filter(item => (item.status || item.follow_up_status || "") !== "完成").length;
    const navCount = $("#nav-followup-count");
    navCount.textContent = formatNumber(pendingCount);
    navCount.classList.toggle("hidden", pendingCount === 0);
  } catch (error) {
    setChildren(container, [emptyState(error.message)]);
  } finally {
    setButtonBusy(refreshButton, false);
  }
}

function renderRecord(record) {
  $("#record-title").textContent = `${text(record.owner_name, "未填姓名")}・${text(record.land_number, "未填地號")}`;
  const detail = $("#record-detail");
  const nodes = [];
  Object.entries(recordLabels).forEach(([key, label]) => {
    if (record[key] === undefined || record[key] === null || String(record[key]).trim() === "") return;
    const value = key === "external_id" ? maskIdentity(record[key]) : record[key];
    nodes.push(element("dt", "", label), element("dd", "", value));
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
    if (
      state.currentFieldVisitItemId
      && Number(item.field_visit_route_item_id) === Number(state.currentFieldVisitItemId)
    ) {
      row.append(element("span", "field-context-badge", "本次行程"));
    }
    if (item.note) row.append(element("p", "", item.note));
    return row;
  });
  setChildren(container, nodes.length ? nodes : [element("p", "muted", "目前沒有聯絡紀錄。")]);
}

function attachmentIcon(item) {
  const mediaType = String(item.media_type || "").toLowerCase();
  const name = String(item.original_name || item.file_path || "").toLowerCase();
  if (mediaType.startsWith("image/") || /\.(jpg|jpeg|png|gif|webp|heic|heif)$/.test(name)) return "照片";
  if (mediaType === "application/pdf" || name.endsWith(".pdf")) return "PDF";
  return "檔案";
}

function isImageAttachment(item) {
  return attachmentIcon(item) === "照片";
}

function isDocumentAttachment(item) {
  const mediaType = String(item.media_type || "").toLowerCase();
  const name = String(item.original_name || item.file_path || "").toLowerCase();
  return mediaType === "application/pdf"
    || /\.(pdf|doc|docx|xls|xlsx|ppt|pptx|txt|csv)$/.test(name);
}

function releaseThumbnailUrls() {
  state.thumbnailUrls.forEach(url => URL.revokeObjectURL(url));
  state.thumbnailUrls.clear();
}

function filteredAndSortedAttachments() {
  const filter = $("#attachment-filter").value;
  const sort = $("#attachment-sort").value;
  const filtered = state.currentAttachments.filter(item => {
    if (filter === "photos") return isImageAttachment(item);
    if (filter === "documents") return isDocumentAttachment(item);
    if (filter === "other") return !isImageAttachment(item) && !isDocumentAttachment(item);
    return true;
  });
  return filtered.sort((left, right) => {
    if (sort === "name") {
      return String(left.original_name || left.file_path || "").localeCompare(
        String(right.original_name || right.file_path || ""), "zh-TW"
      );
    }
    const leftTime = new Date(left.created_at || 0).getTime() || 0;
    const rightTime = new Date(right.created_at || 0).getTime() || 0;
    return sort === "oldest" ? leftTime - rightTime : rightTime - leftTime;
  });
}

async function loadAttachmentThumbnail(recordId, item, image, fallback) {
  try {
    const blob = await requestBlob(`/api/v1/records/${recordId}/attachments/${item.id}/thumbnail`);
    if (state.currentRecordId !== recordId || !document.contains(image)) return;
    const url = URL.createObjectURL(blob);
    const previousUrl = state.thumbnailUrls.get(Number(item.id));
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    state.thumbnailUrls.set(Number(item.id), url);
    image.src = url;
    image.classList.remove("hidden");
    fallback.classList.add("hidden");
  } catch (_error) {
    image.classList.add("hidden");
    fallback.classList.remove("hidden");
  }
}

function renderAttachments(items = null) {
  if (items) state.currentAttachments = [...items];
  const container = $("#attachment-results");
  releaseThumbnailUrls();
  const attachments = filteredAndSortedAttachments();
  const total = state.currentAttachments.length;
  $("#attachment-count").textContent = attachments.length === total
    ? `${formatNumber(total)} 個附件`
    : `顯示 ${formatNumber(attachments.length)}／${formatNumber(total)}`;
  const nodes = attachments.map(item => {
    const managed = String(item.status || "managed") !== "external";
    const isPhoto = managed && isImageAttachment(item);
    const card = element("article", `attachment-item${isPhoto ? " photo-card" : ""}`);
    const media = element(isPhoto ? "button" : "div", "attachment-media");
    if (isPhoto) {
      media.type = "button";
      media.dataset.photoPreview = item.id;
      media.setAttribute("aria-label", `預覽 ${text(item.original_name, "照片")}`);
      const thumbnail = element("img", "hidden");
      thumbnail.alt = "";
      const fallback = element("span", "attachment-icon", "照片");
      fallback.setAttribute("aria-hidden", "true");
      media.append(thumbnail, fallback);
      loadAttachmentThumbnail(state.currentRecordId, item, thumbnail, fallback);
    } else {
      const icon = element("span", "attachment-icon", attachmentIcon(item));
      icon.setAttribute("aria-hidden", "true");
      media.append(icon);
    }

    const copy = element("div", "attachment-copy");
    copy.append(element("strong", "", text(item.original_name || item.file_path, "未命名附件")));
    if (item.category) copy.append(element("span", "attachment-category", item.category));
    if (
      state.currentFieldVisitItemId
      && Number(item.field_visit_route_item_id) === Number(state.currentFieldVisitItemId)
    ) {
      copy.append(element("span", "field-context-badge", "本次行程"));
    }
    if (item.description) copy.append(element("p", "", item.description));
    const metadata = managed
      ? `${formatFileSize(item.size_bytes)}・${formatAttachmentDate(item.created_at)}`
      : `外部連結・${formatAttachmentDate(item.created_at)}`;
    copy.append(element("small", "muted", metadata));
    if (!managed) copy.append(element("small", "muted", "外部連結只能在原本的桌面電腦開啟。"));

    const actions = element("div", "attachment-actions");
    if (managed) {
      const openButton = element("button", "secondary-button", "開啟／下載");
      openButton.type = "button";
      openButton.dataset.attachmentOpen = item.id;
      actions.append(openButton);
    }
    if (canEdit()) {
      const editButton = element("button", "secondary-button", "編輯");
      editButton.type = "button";
      editButton.dataset.attachmentEdit = item.id;
      actions.append(editButton);
      if (item.can_delete === true) {
        const deleteButton = element("button", "danger-button", "刪除");
        deleteButton.type = "button";
        deleteButton.dataset.attachmentDelete = item.id;
        deleteButton.dataset.attachmentName = item.original_name || item.file_path || "此附件";
        actions.append(deleteButton);
      }
    }
    card.append(media, copy, actions);
    return card;
  });
  const emptyMessage = total ? "目前的篩選條件沒有符合附件。" : "目前沒有照片或附件。";
  setChildren(container, nodes.length ? nodes : [element("p", "muted", emptyMessage)]);
}

function attachmentFileKey(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function attachmentUploadSignature(file, recordId, description, category) {
  return JSON.stringify([
    attachmentFileKey(file),
    Number(recordId),
    description,
    category,
    state.currentFieldVisitItemId || null
  ]);
}

function loadImageFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("照片格式無法在此手機壓縮"));
    };
    image.src = url;
  });
}

function canvasBlob(canvas, quality) {
  return new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", quality));
}

async function compressPhotoFile(file) {
  const mediaType = String(file.type || "").toLowerCase();
  const name = String(file.name || "").toLowerCase();
  const compressible = (mediaType === "image/jpeg" || /\.(jpg|jpeg|heic|heif)$/.test(name))
    && file.size >= PHOTO_COMPRESSION_THRESHOLD;
  if (!compressible) return file;
  try {
    const image = await loadImageFile(file);
    const scale = Math.min(1, PHOTO_MAX_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await canvasBlob(canvas, 0.82);
    if (!blob || blob.size >= file.size * 0.95) return file;
    const stem = file.name.replace(/\.[^.]+$/, "") || "photo";
    return new File([blob], `${stem}.jpg`, {
      type: "image/jpeg",
      lastModified: file.lastModified
    });
  } catch (_error) {
    return file;
  }
}

function updateAttachmentSelectionDisplay() {
  const totalSize = state.pendingAttachmentFiles.reduce((sum, file) => sum + file.size, 0);
  const originalSize = state.pendingAttachmentFiles.reduce(
    (sum, file) => sum + (state.attachmentOriginalSizes.get(attachmentFileKey(file)) || file.size), 0
  );
  const savedSize = Math.max(0, originalSize - totalSize);
  const selection = $("#attachment-selection");
  let selectionText = state.attachmentProcessing
    ? "正在處理照片，請稍候…"
    : state.pendingAttachmentFiles.length
      ? `已選擇 ${state.pendingAttachmentFiles.length} 個：${state.pendingAttachmentFiles.map(file => file.name).join("、")}（共 ${formatFileSize(totalSize)}${savedSize ? `，已節省 ${formatFileSize(savedSize)}` : ""}）`
      : "尚未選擇檔案";
  if (state.attachmentUploadError && state.pendingAttachmentFiles.length) {
    selectionText += `；${state.attachmentUploadError}`;
  }
  selection.textContent = selectionText;
  selection.classList.toggle("ready", state.pendingAttachmentFiles.length > 0);
  $("#attachment-upload-button").disabled = state.attachmentProcessing || state.pendingAttachmentFiles.length === 0;
}

function resetAttachmentSelection() {
  state.attachmentSelectionVersion += 1;
  state.attachmentProcessing = false;
  state.pendingAttachmentFiles = [];
  state.attachmentOriginalSizes.clear();
  state.attachmentUploadKeys.clear();
  state.attachmentUploadError = "";
  $("#attachment-photo-input").value = "";
  $("#attachment-file-input").value = "";
  updateAttachmentSelectionDisplay();
}

async function selectAttachmentFiles(event) {
  const selected = Array.from(event.target.files || []);
  event.target.value = "";
  state.attachmentUploadError = "";
  const selectionVersion = ++state.attachmentSelectionVersion;
  state.attachmentProcessing = true;
  updateAttachmentSelectionDisplay();
  const processed = [];
  for (const file of selected) {
    const compressed = await compressPhotoFile(file);
    processed.push({ file: compressed, originalSize: file.size });
  }
  if (selectionVersion !== state.attachmentSelectionVersion) return;
  state.attachmentProcessing = false;
  const oversized = processed.filter(item => item.file.size > MAX_ATTACHMENT_SIZE);
  const accepted = processed.filter(item => item.file.size <= MAX_ATTACHMENT_SIZE);
  const existing = new Map(state.pendingAttachmentFiles.map(file => [attachmentFileKey(file), file]));
  accepted.forEach(item => {
    const key = attachmentFileKey(item.file);
    existing.set(key, item.file);
    state.attachmentOriginalSizes.set(key, item.originalSize);
  });
  state.pendingAttachmentFiles = Array.from(existing.values());

  if (oversized.length) toast(`已略過超過 50 MB 的檔案：${oversized.map(item => item.file.name).join("、")}`);
  updateAttachmentSelectionDisplay();
}

async function loadAttachments(recordId = state.currentRecordId) {
  if (!recordId) return;
  setChildren($("#attachment-results"), [element("p", "muted", "正在載入附件…")]);
  try {
    const result = await request(`/api/v1/records/${recordId}/attachments`);
    if (Number(recordId) === state.currentRecordId) renderAttachments(result.items);
  } catch (error) {
    if (Number(recordId) === state.currentRecordId) {
      setChildren($("#attachment-results"), [element("p", "muted", error.message)]);
    }
  }
}

async function submitAttachments(event) {
  event.preventDefault();
  const recordId = state.currentRecordId;
  const files = [...state.pendingAttachmentFiles];
  if (!recordId || !files.length || !canEdit()) return;
  const button = $("#attachment-upload-button");
  const description = $("#attachment-description").value.trim();
  const category = $("#attachment-category").value;
  setButtonBusy(button, true, `正在上傳 1/${files.length}…`);
  try {
    for (let index = 0; index < files.length; index += 1) {
      button.textContent = `正在上傳 ${index + 1}/${files.length}…`;
      const form = new FormData();
      form.append("file", files[index], files[index].name);
      form.append("description", description);
      form.append("category", category);
      if (state.currentFieldVisitItemId) {
        form.append("field_visit_route_item_id", String(state.currentFieldVisitItemId));
      }
      const uploadSignature = attachmentUploadSignature(files[index], recordId, description, category);
      let uploadKey = state.attachmentUploadKeys.get(uploadSignature);
      if (!uploadKey) {
        uploadKey = idempotencyKey("attachment", recordId);
        state.attachmentUploadKeys.set(uploadSignature, uploadKey);
      }
      await request(`/api/v1/records/${recordId}/attachments/upload`, {
        method: "POST",
        headers: { "Idempotency-Key": uploadKey },
        body: form
      });
      state.attachmentUploadKeys.delete(uploadSignature);
      const completedKey = attachmentFileKey(files[index]);
      state.pendingAttachmentFiles = state.pendingAttachmentFiles.filter(file => attachmentFileKey(file) !== completedKey);
      state.attachmentOriginalSizes.delete(completedKey);
    }
    resetAttachmentSelection();
    $("#attachment-description").value = "";
    $("#attachment-category").value = "";
    await loadAttachments(recordId);
    toast(`已上傳 ${files.length} 個附件至家中伺服器`);
  } catch (error) {
    state.attachmentUploadError = error.isNetworkError
      ? "上傳中斷，未完成的檔案已保留，可再次上傳"
      : `上傳失敗：${error.message}`;
    toast(state.attachmentUploadError);
    await loadAttachments(recordId);
  } finally {
    setButtonBusy(button, false);
    updateAttachmentSelectionDisplay();
  }
}

async function openAttachment(attachmentId) {
  const recordId = state.currentRecordId;
  if (!recordId) return;
  const previewWindow = window.open("about:blank", "_blank");
  try {
    const blob = await requestBlob(`/api/v1/records/${recordId}/attachments/${attachmentId}/content`);
    const url = URL.createObjectURL(blob);
    if (previewWindow) {
      previewWindow.location.href = url;
    } else {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      document.body.append(link);
      link.click();
      link.remove();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    if (previewWindow) previewWindow.close();
    toast(error.message);
  }
}

function closePhotoViewer() {
  state.photoPreviewRequestId += 1;
  if (state.photoPreviewUrl) URL.revokeObjectURL(state.photoPreviewUrl);
  state.photoPreviewUrl = "";
  state.photoPreviewIndex = -1;
  $("#photo-viewer-image").src = "";
  $("#photo-viewer").classList.add("hidden");
}

async function updatePhotoViewer() {
  const item = state.photoPreviewItems[state.photoPreviewIndex];
  if (!item || !state.currentRecordId) return;
  const requestId = ++state.photoPreviewRequestId;
  if (state.photoPreviewUrl) URL.revokeObjectURL(state.photoPreviewUrl);
  state.photoPreviewUrl = "";
  const image = $("#photo-viewer-image");
  image.classList.add("hidden");
  image.src = "";
  $("#photo-viewer-loading").textContent = "正在載入照片…";
  $("#photo-viewer-loading").classList.remove("hidden");
  $("#photo-viewer-title").textContent = text(item.original_name, "照片");
  $("#photo-viewer-caption").textContent = [item.category, item.description].filter(Boolean).join("・") || "未填分類與說明";
  $("#photo-viewer-position").textContent = `${state.photoPreviewIndex + 1}／${state.photoPreviewItems.length}`;
  $("#photo-viewer-previous").disabled = state.photoPreviewItems.length < 2;
  $("#photo-viewer-next").disabled = state.photoPreviewItems.length < 2;
  try {
    const blob = await requestBlob(`/api/v1/records/${state.currentRecordId}/attachments/${item.id}/content`);
    if (requestId !== state.photoPreviewRequestId) return;
    state.photoPreviewUrl = URL.createObjectURL(blob);
    image.src = state.photoPreviewUrl;
    image.alt = text(item.description || item.original_name, "附件照片");
    image.classList.remove("hidden");
    $("#photo-viewer-loading").classList.add("hidden");
  } catch (error) {
    if (requestId === state.photoPreviewRequestId) $("#photo-viewer-loading").textContent = error.message;
  }
}

function openPhotoViewer(attachmentId) {
  state.photoPreviewItems = state.currentAttachments.filter(item => (
    String(item.status || "managed") !== "external" && isImageAttachment(item)
  ));
  state.photoPreviewIndex = state.photoPreviewItems.findIndex(item => Number(item.id) === Number(attachmentId));
  if (state.photoPreviewIndex < 0) return;
  $("#photo-viewer").classList.remove("hidden");
  updatePhotoViewer();
  $("#photo-viewer-close").focus();
}

function movePhotoViewer(offset) {
  if (state.photoPreviewItems.length < 2) return;
  state.photoPreviewIndex = (state.photoPreviewIndex + offset + state.photoPreviewItems.length) % state.photoPreviewItems.length;
  updatePhotoViewer();
}

function closeAttachmentEdit() {
  $("#attachment-edit-dialog").classList.add("hidden");
  $("#attachment-edit-id").value = "";
}

function openAttachmentEdit(attachmentId) {
  const item = state.currentAttachments.find(row => Number(row.id) === Number(attachmentId));
  if (!item || !canEdit()) return;
  $("#attachment-edit-id").value = item.id;
  $("#attachment-edit-category").value = item.category || "";
  $("#attachment-edit-description").value = item.description || "";
  $("#attachment-edit-title").textContent = text(item.original_name, "修改分類與說明");
  $("#attachment-edit-dialog").classList.remove("hidden");
  $("#attachment-edit-category").focus();
}

async function submitAttachmentEdit(event) {
  event.preventDefault();
  const attachmentId = Number($("#attachment-edit-id").value);
  if (!state.currentRecordId || !attachmentId || !canEdit()) return;
  const button = $("#attachment-edit-save");
  setButtonBusy(button, true, "儲存中…");
  try {
    await request(`/api/v1/records/${state.currentRecordId}/attachments/${attachmentId}`, {
      method: "PATCH",
      body: JSON.stringify({
        category: $("#attachment-edit-category").value,
        description: $("#attachment-edit-description").value.trim()
      })
    });
    closeAttachmentEdit();
    await loadAttachments(state.currentRecordId);
    toast("附件分類與說明已更新");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
}

async function deleteAttachment(attachmentId, attachmentName) {
  const recordId = state.currentRecordId;
  if (!recordId || !canEdit()) return;
  if (!confirm(`確定要刪除「${attachmentName}」嗎？此動作無法復原。`)) return;
  try {
    await request(`/api/v1/records/${recordId}/attachments/${attachmentId}`, { method: "DELETE" });
    closePhotoViewer();
    closeAttachmentEdit();
    await loadAttachments(recordId);
    toast("附件已刪除");
  } catch (error) {
    toast(error.message);
  }
}

function fillFollowup(item) {
  const followup = item || {};
  $("#followup-date").value = followup.due_date || followup.next_follow_up || "";
  $("#followup-status").value = followup.status || followup.follow_up_status || "未處理";
  $("#followup-note").value = followup.note || "";
}

function focusRecordSection(sectionId) {
  const section = sectionId ? document.getElementById(sectionId) : null;
  if (!section) return;
  $$(".sheet-section.record-section-highlight").forEach(node => node.classList.remove("record-section-highlight"));
  section.classList.add("record-section-highlight");
  section.scrollIntoView({ behavior: "smooth", block: "start" });
  if (canEdit() && sectionId === "contact-section") {
    $("#contact-result").focus({ preventScroll: true });
  } else if (canEdit() && sectionId === "attachment-section") {
    $("#attachment-category").focus({ preventScroll: true });
  } else {
    section.tabIndex = -1;
    section.focus({ preventScroll: true });
  }
}

function saveContactDraft() {
  if (!state.currentRecordId) return;
  writeSessionDraft(contactDraftKey(), {
    contact_date: $("#contact-date").value,
    method: $("#contact-method").value,
    result: $("#contact-result").value,
    next_follow_up: $("#contact-next").value,
    note: $("#contact-note").value,
    idempotency_key: state.contactIdempotencyKey,
    submitted_signature: state.contactSubmittedSignature,
    submitted_payload: state.contactSubmittedPayload
  });
}

function restoreContactDraft() {
  const draft = readSessionDraft(contactDraftKey());
  $("#contact-date").value = draft && typeof draft.contact_date === "string"
    ? draft.contact_date
    : localDateISO();
  $("#contact-method").value = draft && typeof draft.method === "string"
    ? draft.method
    : "面談";
  $("#contact-result").value = draft && typeof draft.result === "string" ? draft.result : "";
  $("#contact-next").value = draft && typeof draft.next_follow_up === "string" ? draft.next_follow_up : "";
  $("#contact-note").value = draft && typeof draft.note === "string" ? draft.note : "";
  state.contactIdempotencyKey = draft && draft.idempotency_key
    ? String(draft.idempotency_key)
    : idempotencyKey("contact", state.currentRecordId);
  state.contactSubmittedSignature = draft && draft.submitted_signature
    ? String(draft.submitted_signature)
    : "";
  state.contactSubmittedPayload = draft && draft.submitted_payload
    ? draft.submitted_payload
    : null;
}

function clearContactDraft() {
  sessionStorage.removeItem(contactDraftKey());
  state.contactIdempotencyKey = "";
  state.contactSubmittedSignature = "";
  state.contactSubmittedPayload = null;
}

async function openRecord(recordId, sectionId = "", fieldVisitItemId = null) {
  lastFocusedElement = document.activeElement;
  const requestedRecordId = Number(recordId);
  state.currentRecordId = requestedRecordId;
  state.currentFieldVisitItemId = fieldVisitItemId ? Number(fieldVisitItemId) : null;
  $("#record-sheet").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  $("#record-sheet").querySelector("[data-close-sheet]").focus();
  setChildren($("#record-detail"), [element("dd", "", "正在載入資料…")]);
  resetAttachmentSelection();
  $("#attachment-description").value = "";
  restoreContactDraft();
  $("#attachment-count").textContent = "載入中…";
  setChildren($("#attachment-results"), [element("p", "muted", "正在載入附件…")]);
  try {
    const [record, contacts, followup, attachments] = await Promise.all([
      request(`/api/v1/records/${requestedRecordId}`),
      request(`/api/v1/records/${requestedRecordId}/contact-logs`),
      request(`/api/v1/records/${requestedRecordId}/follow-up`),
      request(`/api/v1/records/${requestedRecordId}/attachments`)
    ]);
    if (state.currentRecordId !== requestedRecordId) return;
    renderRecord(record);
    renderContacts(contacts.items);
    fillFollowup(followup.item);
    renderAttachments(attachments.items);
    if (sectionId) requestAnimationFrame(() => focusRecordSection(sectionId));
  } catch (error) {
    toast(error.message);
  }
}

function closeRecord() {
  closePhotoViewer();
  closeAttachmentEdit();
  releaseThumbnailUrls();
  state.currentAttachments = [];
  $$(".sheet-section.record-section-highlight").forEach(node => node.classList.remove("record-section-highlight"));
  $("#record-sheet").classList.add("hidden");
  document.body.style.overflow = "";
  resetAttachmentSelection();
  state.currentRecordId = null;
  state.currentFieldVisitItemId = null;
  if (lastFocusedElement && document.contains(lastFocusedElement)) lastFocusedElement.focus();
}

async function submitContact(event) {
  event.preventDefault();
  if (!state.currentRecordId) return;
  let payload = {
    contact_date: $("#contact-date").value || null,
    method: $("#contact-method").value || null,
    result: $("#contact-result").value || null,
    next_follow_up: $("#contact-next").value || null,
    note: $("#contact-note").value || null
  };
  if (state.currentFieldVisitItemId) {
    payload.field_visit_route_item_id = state.currentFieldVisitItemId;
    if (state.currentPosition) {
      payload.latitude = state.currentPosition.latitude;
      payload.longitude = state.currentPosition.longitude;
    }
  }
  const semanticSignature = JSON.stringify({
    contact_date: payload.contact_date,
    method: payload.method,
    result: payload.result,
    next_follow_up: payload.next_follow_up,
    note: payload.note,
    field_visit_route_item_id: payload.field_visit_route_item_id || null
  });
  if (
    state.contactIdempotencyKey
    && state.contactSubmittedSignature === semanticSignature
    && state.contactSubmittedPayload
  ) {
    payload = state.contactSubmittedPayload;
  } else {
    state.contactIdempotencyKey = idempotencyKey("contact", state.currentRecordId);
    state.contactSubmittedPayload = payload;
  }
  state.contactSubmittedSignature = semanticSignature;
  saveContactDraft();
  let contactSaved = false;
  try {
    await request(`/api/v1/records/${state.currentRecordId}/contact-logs`, {
      method: "POST",
      headers: { "Idempotency-Key": state.contactIdempotencyKey },
      body: JSON.stringify(payload)
    });
    contactSaved = true;
    clearContactDraft();
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
    if (contactSaved) {
      toast("聯絡紀錄已儲存，但清單更新失敗；重新開啟即可查看。");
      return;
    }
    saveContactDraft();
    toast(error.isNetworkError ? "儲存失敗，聯絡內容已保留，可直接重新送出。" : error.message);
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
  $("#field-location-button").addEventListener("click", requestFieldLocation);
  $("#field-visit-manage").addEventListener("click", openFieldPlan);
  $("#field-visit-create").addEventListener("click", openFieldPlan);
  $("#field-visit-refresh").addEventListener("click", () => loadFieldVisit());
  $("#field-visit-start").addEventListener("click", startFieldWork);
  $("#field-visit-reoptimize").addEventListener("click", reoptimizeRemainingFieldVisit);
  $("#field-completion-review").addEventListener("click", reviewFieldVisitItinerary);
  $("#field-visit-previous").addEventListener("click", () => selectFieldVisitItem(state.fieldVisitIndex - 1));
  $("#field-visit-next").addEventListener("click", () => selectFieldVisitItem(state.fieldVisitIndex + 1));
  $("#refresh-followups").addEventListener("click", loadFollowups);
  $("#contact-form").addEventListener("submit", submitContact);
  $("#contact-form").addEventListener("input", saveContactDraft);
  $("#contact-form").addEventListener("change", saveContactDraft);
  $("#followup-form").addEventListener("submit", submitFollowup);
  $("#attachment-form").addEventListener("submit", submitAttachments);
  $("#attachment-photo-input").addEventListener("change", selectAttachmentFiles);
  $("#attachment-file-input").addEventListener("change", selectAttachmentFiles);
  $("#attachment-filter").addEventListener("change", () => renderAttachments());
  $("#attachment-sort").addEventListener("change", () => renderAttachments());
  $("#attachment-edit-form").addEventListener("submit", submitAttachmentEdit);
  $$('[data-close-attachment-edit]').forEach(node => node.addEventListener("click", closeAttachmentEdit));
  $("#field-action-form").addEventListener("submit", submitFieldAction);
  $("#field-action-form").addEventListener("input", saveFieldActionDraft);
  $("#field-action-form").addEventListener("change", saveFieldActionDraft);
  $$('[data-close-field-action]').forEach(node => node.addEventListener("click", closeFieldAction));
  $("#field-plan-search-form").addEventListener("submit", searchFieldPlanRecords);
  $("#field-plan-submit").addEventListener("click", submitFieldPlan);
  $("#field-plan-order-save").addEventListener("click", saveFieldPlanOrder);
  $("#field-plan-unlock-order").addEventListener("click", unlockFieldPlanOrder);
  $$('[data-close-field-plan]').forEach(node => node.addEventListener("click", closeFieldPlan));
  $("#field-plan-results").addEventListener("change", event => {
    const checkbox = event.target.closest("[data-field-plan-record]");
    if (!checkbox) return;
    const recordId = Number(checkbox.dataset.fieldPlanRecord);
    if (checkbox.checked) state.fieldPlanSelection.add(recordId);
    else state.fieldPlanSelection.delete(recordId);
    updateFieldPlanSelection();
  });
  $("#photo-viewer-close").addEventListener("click", closePhotoViewer);
  $("#photo-viewer-previous").addEventListener("click", () => movePhotoViewer(-1));
  $("#photo-viewer-next").addEventListener("click", () => movePhotoViewer(1));
  $("#photo-viewer-download").addEventListener("click", () => {
    const item = state.photoPreviewItems[state.photoPreviewIndex];
    if (item) openAttachment(item.id);
  });
  $$(".app-nav button, .mobile-nav button").forEach(button => button.addEventListener("click", () => navigate(button.dataset.page)));
  $$('[data-go]').forEach(button => button.addEventListener("click", () => navigate(button.dataset.go)));
  $$('[data-close-sheet]').forEach(node => node.addEventListener("click", closeRecord));
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-record-id]");
    if (button) openRecord(button.dataset.recordId);
    const fieldRecordButton = event.target.closest("[data-field-record-id]");
    if (fieldRecordButton) {
      openRecord(
        fieldRecordButton.dataset.fieldRecordId,
        fieldRecordButton.dataset.fieldRecordSection,
        fieldRecordButton.dataset.fieldRouteItemId
      );
    }
    const openButton = event.target.closest("[data-attachment-open]");
    if (openButton) openAttachment(openButton.dataset.attachmentOpen);
    const previewButton = event.target.closest("[data-photo-preview]");
    if (previewButton) openPhotoViewer(previewButton.dataset.photoPreview);
    const editButton = event.target.closest("[data-attachment-edit]");
    if (editButton) openAttachmentEdit(editButton.dataset.attachmentEdit);
    const deleteButton = event.target.closest("[data-attachment-delete]");
    if (deleteButton) deleteAttachment(deleteButton.dataset.attachmentDelete, deleteButton.dataset.attachmentName);
    const fieldItem = event.target.closest("[data-field-item-index]");
    if (fieldItem) selectFieldVisitItem(fieldItem.dataset.fieldItemIndex);
    const navigationButton = event.target.closest("[data-field-navigate]");
    if (navigationButton) openFieldNavigation(navigationButton.dataset.fieldNavigate);
    const fieldActionButton = event.target.closest("[data-field-action]");
    if (fieldActionButton) {
      openFieldAction(
        fieldActionButton.dataset.fieldAction,
        fieldActionButton.dataset.fieldActionItem,
        fieldActionButton
      );
    }
    const moveFieldPlanButton = event.target.closest("[data-field-plan-move]");
    if (moveFieldPlanButton) {
      moveFieldPlanItem(
        moveFieldPlanButton.dataset.fieldPlanItem,
        moveFieldPlanButton.dataset.fieldPlanMove
      );
    }
    const removeFieldPlanButton = event.target.closest("[data-field-plan-remove]");
    if (removeFieldPlanButton) {
      removeFieldPlanItem(
        removeFieldPlanButton.dataset.fieldPlanRemove,
        removeFieldPlanButton
      );
    }
    const priorityFieldPlanButton = event.target.closest("[data-field-plan-priority]");
    if (priorityFieldPlanButton) {
      updateFieldPlanPriority(
        priorityFieldPlanButton.dataset.fieldPlanPriority,
        priorityFieldPlanButton.dataset.fieldPlanPriorityValue,
        priorityFieldPlanButton
      );
    }
    const restoreFieldPlanButton = event.target.closest("[data-field-plan-restore]");
    if (restoreFieldPlanButton) {
      restoreFieldPlanItem(
        restoreFieldPlanButton.dataset.fieldPlanRestore,
        restoreFieldPlanButton
      );
    }
  });
  window.addEventListener("online", () => updateConnection(true));
  window.addEventListener("offline", () => updateConnection(false, "手機目前離線，資料不會寫入"));
  let photoTouchStart = null;
  $("#photo-viewer").addEventListener("touchstart", event => {
    photoTouchStart = event.changedTouches[0]?.clientX ?? null;
  }, { passive: true });
  $("#photo-viewer").addEventListener("touchend", event => {
    if (photoTouchStart === null) return;
    const distance = (event.changedTouches[0]?.clientX ?? photoTouchStart) - photoTouchStart;
    photoTouchStart = null;
    if (Math.abs(distance) > 55) movePhotoViewer(distance > 0 ? -1 : 1);
  }, { passive: true });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !$("#photo-viewer").classList.contains("hidden")) closePhotoViewer();
    else if (event.key === "Escape" && !$("#attachment-edit-dialog").classList.contains("hidden")) closeAttachmentEdit();
    else if (event.key === "Escape" && !$("#field-action-dialog").classList.contains("hidden")) closeFieldAction();
    else if (event.key === "Escape" && !$("#field-plan-dialog").classList.contains("hidden")) closeFieldPlan();
    else if (event.key === "Escape") closeRecord();
    if (event.key === "ArrowLeft" && !$("#photo-viewer").classList.contains("hidden")) movePhotoViewer(-1);
    if (event.key === "ArrowRight" && !$("#photo-viewer").classList.contains("hidden")) movePhotoViewer(1);
  });
  $("#contact-date").value = new Date().toISOString().slice(0, 10);
}

bindEvents();
restoreSession();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js", { scope: "/mobile/" }).catch(() => {}));
}
