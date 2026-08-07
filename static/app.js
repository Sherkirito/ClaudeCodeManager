"use strict";

const $ = (selector, scope = document) => scope.querySelector(selector);
const pageRoot = $("#page-content");
const pageScroll = $("#page-scroll");
const toastRegion = $("#toast-region");
const launchDialog = $("#launch-dialog");
const confirmDialog = $("#confirm-dialog");

const ICONS = {
  activity: ["M4 13h3l2-7 4 13 2-6h5"],
  alert: ["M12 3 2.8 20h18.4z", "M12 9v5M12 17h.01"],
  arrow: ["M5 12h14", "m14 0-5-5m5 5-5 5"],
  check: ["m5 12 4 4L19 6"],
  chevronLeft: ["m15 18-6-6 6-6"],
  chevronRight: ["m9 18 6-6-6-6"],
  clock: ["M12 7v5l3 2", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"],
  database: ["M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z", "M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6", "M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"],
  folder: ["M3 7.5h7l2-2h9v13H3z", "M3 9h18"],
  key: ["M15 8a5 5 0 1 0-4.6 7", "m14 13 7-7", "m18 9 2 2"],
  message: ["M5 5h14v11H9l-4 3z", "M8 9h8M8 12h5"],
  play: ["m8 5 11 7-11 7z"],
  refresh: ["M20 7v5h-5", "M4 17v-5h5", "M6.1 8a7 7 0 0 1 11.7-2.1L20 9", "M17.9 16a7 7 0 0 1-11.7 2.1L4 15"],
  search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z", "m20 20-4-4"],
  settings: ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 0 0-1.7-1L14.6 3h-4l-.3 3.1a7 7 0 0 0-1.7 1l-2.3-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 1.7 1l.3 3.1h4l.3-3.1a7 7 0 0 0 1.7-1l2.3 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z"],
  spark: ["m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4z", "m18.5 14 .7 2.3 2.3.7-2.3.8-.7 2.2-.8-2.2-2.2-.8 2.2-.7z"],
  terminal: ["m5 7 4 4-4 4", "M11 16h7"],
  token: ["M12 3 4 7v10l8 4 8-4V7z", "m4 7 8 4 8-4", "M12 11v10"],
  trash: ["M4 7h16", "m9 11-.5-7h7l-.5 7", "M9 7V4h6v3"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M4 21a8 8 0 0 1 16 0"],
  x: ["m6 6 12 12M18 6 6 18"]
};

function icon(name, className = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);
  (ICONS[name] || ICONS.activity).forEach((d) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  });
  return svg;
}

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === false) return;
    if (key === "className") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key === "dataset") Object.entries(value).forEach(([k, v]) => { node.dataset[k] = String(v); });
    else if (key === "checked" || key === "disabled" || key === "selected" || key === "open" || key === "readOnly") node[key] = Boolean(value);
    else if (key === "value") node.value = value;
    else if (key in node && !key.startsWith("aria")) node[key] = value;
    else node.setAttribute(key.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase()), String(value));
  });
  const append = (child) => {
    if (Array.isArray(child)) child.forEach(append);
    else if (child instanceof Node) node.append(child);
    else if (child !== undefined && child !== null && child !== false) node.append(document.createTextNode(String(child)));
  };
  children.forEach(append);
  return node;
}

function button(label, action, { kind = "ghost", iconName = "", dataset = {}, disabled = false, small = false } = {}) {
  const btn = h("button", {
    type: "button",
    className: `button button-${kind}${small ? " button-small" : ""}`,
    dataset: { action, ...dataset },
    disabled
  });
  if (iconName) btn.append(icon(iconName));
  btn.append(document.createTextNode(label));
  return btn;
}

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data || {};
  }
}

async function api(url, options = {}) {
  const separator = url.includes("?") ? "&" : "?";
  const response = await fetch(`${url}${separator}_t=${Date.now()}`, options);
  let data = {};
  try { data = await response.json(); } catch { /* local service may be shutting down */ }
  if (!response.ok) throw new ApiError(data.message || data.error || `HTTP ${response.status}`, response.status, data);
  return data;
}

function post(url, body = {}) {
  return api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

const MODEL_CATALOG = {
  deepseek: {
    "deepseek-v4-flash": "DeepSeek-V4-Flash（推荐）",
    "deepseek-v4-pro": "DeepSeek-V4-Pro"
  },
  anthropic: {
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5（最快最便宜）",
    "claude-sonnet-4-6-20250514": "Claude Sonnet 4.6（推荐）",
    "claude-opus-4-7-20250514": "Claude Opus 4.7（最准确）"
  }
};

const PERMISSIONS = {
  read: { label: "仅阅读", description: "只允许读取文件", command: "--allowedTools Read" },
  write: { label: "文件编辑", description: "允许读取与写入文件", command: "--allowedTools Read,Write" },
  std: { label: "标准权限", description: "使用 Claude Code 默认授权规则", command: "不追加权限参数" },
  full: { label: "完全控制", description: "绕过权限确认，请谨慎使用", command: "--permission-mode bypassPermissions" }
};

const state = {
  route: "dashboard",
  params: {},
  renderToken: 0,
  config: null,
  pathMappings: { mappings: {} },
  projectNames: new Map(),
  projectCache: new Map(),
  launchContexts: new Map(),
  launchContext: null,
  launchCounter: 0,
  projects: { q: "", drive: "", sort: "active", offset: 0, limit: 50, dirParts: [], data: null, dirs: null },
  sessions: { q: "", offset: 0, limit: 60 },
  selectedProjects: new Set(),
  selectedSessions: new Map(),
  projectViews: new Map(),
  sessionViews: new Map(),
  projectTabs: new Map(),
  projectData: new Map(),
  summaryProgress: new Map(),
  search: { q: "", offset: 0, limit: 60 }
};

function encode(value) { return encodeURIComponent(value || ""); }
function formatNumber(value) {
  const n = Number(value || 0);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}K`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}
function formatExactNumber(value) { return Number(value || 0).toLocaleString("zh-CN"); }
function shortPath(value) {
  const clean = String(value || "").replace(/\//g, "\\").replace(/\\+$/, "");
  return clean.split("\\").pop() || clean || "未命名";
}
function normalizePath(value) { return String(value || "").replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase(); }
function selectedSessionSet(projectId) {
  if (!state.selectedSessions.has(projectId)) state.selectedSessions.set(projectId, new Set());
  return state.selectedSessions.get(projectId);
}
function findPathMapping(path) {
  const key = normalizePath(path);
  let match = null;
  let length = -1;
  Object.entries(state.pathMappings?.mappings || {}).forEach(([oldPath, entry]) => {
    const oldKey = normalizePath(entry?.old_path || oldPath);
    if (oldKey && (key === oldKey || key.startsWith(`${oldKey}\\`)) && oldKey.length > length) {
      match = entry;
      length = oldKey.length;
    }
  });
  return match;
}
function findProjectPathMapping(path) {
  const oldMatch = findPathMapping(path);
  if (oldMatch) return oldMatch;
  const key = normalizePath(path);
  let match = null;
  let length = -1;
  Object.values(state.pathMappings?.mappings || {}).forEach((entry) => {
    const newKey = normalizePath(entry?.new_path || "");
    if (newKey && (key === newKey || key.startsWith(`${newKey}\\`)) && newKey.length > length) {
      match = entry;
      length = newKey.length;
    }
  });
  return match;
}
function isMappingTarget(path, mapping) {
  const key = normalizePath(path);
  const target = normalizePath(mapping?.new_path || "");
  return Boolean(target && (key === target || key.startsWith(`${target}\\`)));
}
function mappedPath(path, mapping) {
  if (!mapping) return path;
  const oldPath = mapping.old_path || "";
  const suffix = String(path || "").slice(oldPath.length).replace(/^[\\/]+/, "");
  return suffix ? `${mapping.new_path}\\${suffix}` : mapping.new_path;
}

function toast(message, type = "info") {
  const names = { success: "check", error: "alert", info: "activity" };
  const node = h("div", { className: `toast is-${type}` }, icon(names[type] || "activity"), h("span", { text: message }));
  toastRegion.append(node);
  window.setTimeout(() => node.remove(), 3600);
}

function setGlobalLoading(show, title = "处理中", detail = "请稍候…") {
  $("#global-loader").hidden = !show;
  $("#global-loader-title").textContent = title;
  $("#global-loader-detail").textContent = detail;
}

function skeletonPage() {
  pageRoot.replaceChildren(
    h("div", { className: "skeleton heading" }),
    h("div", { className: "stats-grid" }, [1, 2, 3, 4].map(() => h("div", { className: "skeleton card" }))),
    h("div", { className: "skeleton-stack" }, [1, 2, 3, 4].map(() => h("div", { className: "skeleton row" })))
  );
}

function errorPage(error, retryAction = "retry-page") {
  pageRoot.replaceChildren(h("div", { className: "error-state" },
    h("span", { className: "section-icon" }, icon("alert")),
    h("h2", { text: "页面加载失败" }),
    h("p", { text: error?.message || "无法连接本地管理服务。" }),
    button("重新加载", retryAction, { kind: "secondary", iconName: "refresh" })
  ));
}

function pageHeading(eyebrow, title, description, actions = []) {
  return h("header", { className: "page-heading" },
    h("div", { className: "page-heading-main" },
      h("span", { className: "eyebrow", text: eyebrow }),
      h("h1", { text: title }),
      description ? h("p", { className: description.includes("\\") || description.includes(":/") ? "path-subtitle" : "", text: description }) : null
    ),
    h("div", { className: "heading-actions" }, actions)
  );
}

function panel(title, subtitle, content, action = null, extraClass = "") {
  return h("section", { className: `panel ${extraClass}`.trim() },
    h("div", { className: "panel-head" },
      h("div", {}, h("h2", { text: title }), subtitle ? h("p", { text: subtitle }) : null),
      action
    ),
    h("div", { className: "panel-body flush" }, content)
  );
}

function statCard(label, value, hint, iconName) {
  return h("article", { className: "stat-card" },
    h("div", { className: "stat-top" }, h("span", { text: label }), h("span", { className: "stat-icon" }, icon(iconName))),
    h("strong", { text: value }),
    h("small", { text: hint })
  );
}

function emptyState(title, detail, iconName = "folder") {
  return h("div", { className: "empty-state" }, icon(iconName), h("div", {}, h("strong", { text: title }), h("p", { text: detail })));
}

function pager(total, offset, limit, scope, projectId = "") {
  const from = total ? offset + 1 : 0;
  const to = Math.min(total, offset + limit);
  return h("div", { className: "pager" },
    h("span", { text: `${from}–${to} / ${total}` }),
    h("div", { className: "pager-actions" },
      button("上一页", "page-prev", { kind: "ghost", iconName: "chevronLeft", small: true, disabled: offset <= 0, dataset: { scope, projectId } }),
      button("下一页", "page-next", { kind: "ghost", iconName: "chevronRight", small: true, disabled: offset + limit >= total, dataset: { scope, projectId } })
    )
  );
}

function tag(text, kind = "") { return h("span", { className: `tag ${kind}`.trim(), text }); }

function rowMeta(items) {
  return h("div", { className: "row-meta" }, items.filter(Boolean).map((item) => {
    const span = h("span", {});
    if (item.icon) span.append(icon(item.icon));
    span.append(document.createTextNode(item.text));
    return span;
  }));
}

function registerLaunchContext(context) {
  const key = `launch-${++state.launchCounter}`;
  state.launchContexts.set(key, context);
  return key;
}

function sessionKindLabel(kind) {
  return { subagent: "Subagent", job: "后台 Job", sdk: "SDK 自动会话" }[kind] || "主会话";
}

function sessionEntry(session, { selectable = false, compact = false } = {}) {
  const sessionId = session.id || session.session_id || "";
  const projectId = session.project_id || "";
  const recordProjectId = session.record_project_id || projectId;
  const isPrimary = (session.session_kind || "primary") === "primary" && !session.parent_session_id;
  const canSelect = selectable && isPrimary;
  const row = h("div", {
    className: `list-row${canSelect ? " has-check" : " is-clickable"}${compact ? " is-child-session" : ""}`,
    dataset: canSelect ? undefined : { action: "open-session", projectId, sessionId },
    title: canSelect ? undefined : "打开会话详情"
  });
  if (canSelect) {
    row.append(h("label", { className: "check-wrap", ariaLabel: "选择会话" }, h("input", {
      type: "checkbox",
      checked: selectedSessionSet(projectId).has(sessionId),
      dataset: { change: "select-session", projectId, sessionId }
    })));
  }
  const titleLine = h("div", { className: "row-title-line" }, h("span", { className: "row-title", text: session.title || sessionId }));
  if (!isPrimary) titleLine.append(tag(sessionKindLabel(session.session_kind), session.relation_confidence === "exact" ? "success" : "info"));
  if (session.child_count) titleLine.append(tag(`下属 ${session.child_count}`, "info"));
  if (session.cwd_changed) titleLine.append(tag("CWD 变化", "warning"));
  if (session.grouping_reason === "cwd_collision") titleLine.append(tag("已纠正归类", "info"));
  if (session.path_exists === 0) titleLine.append(tag("目录疑似已移动", "warning"));
  const open = h("button", { className: "row-click", type: "button", dataset: { action: "open-session", projectId, sessionId } },
    titleLine,
    h("p", { className: "row-description", text: session.first_user_msg || session.cwd || "暂无首条消息" }),
    rowMeta([
      { icon: "folder", text: session.project_name || shortPath(session.cwd) },
      { icon: "clock", text: session.last_active || session.created_at || "时间未知" }
    ])
  );
  const launchKey = isPrimary ? registerLaunchContext({ kind: "session", projectId: recordProjectId, logicalProjectId: projectId, sessionId, path: session.cwd_initial || session.cwd || session.project_name || "", label: session.title || sessionId }) : "";
  const side = h("div", { className: "row-side" },
    h("div", { className: "metric" }, h("strong", { text: formatNumber(session.total_tokens) }), h("span", { text: "tokens" })),
    h("div", { className: "metric" }, h("strong", { text: formatNumber(session.total_msgs) }), h("span", { text: "消息" })),
    isPrimary ? button("恢复", "open-launch", { kind: "secondary", iconName: "play", small: true, dataset: { launchKey } }) : h("span", { className: "auto-session-note", text: "仅查看" })
  );
  row.append(open, side);
  const nodes = [row];
  if (session.ai_summary) nodes.push(h("details", { className: "summary-accordion" }, h("summary", { text: "查看 AI 摘要" }), h("p", { text: session.ai_summary })));
  if (!compact && (session.children || []).length) {
    const childList = h("div", { className: "list child-session-list" });
    session.children.forEach((child) => childList.append(...sessionEntry(child, { compact: true })));
    nodes.push(h("details", { className: "child-session-group" },
      h("summary", {}, h("span", { text: `下属会话 ${session.children.length} 个` }), h("small", { text: "默认折叠，不参与主会话计数" })),
      childList
    ));
  }
  return nodes;
}

function automaticSessionsPanel(data, { selectable = false } = {}) {
  const items = data.automatic_items || [];
  if (!items.length) return h("div", { hidden: true });
  const list = h("div", { className: "list child-session-list" });
  items.forEach((session) => list.append(...sessionEntry(session, { selectable, compact: true })));
  return h("details", { className: "automatic-session-group" },
    h("summary", {}, h("div", {}, h("strong", { text: `未关联的自动会话 ${data.automatic_total || items.length} 个` }), h("p", { text: "已识别为 Job 或 SDK 会话，但没有足够证据确定母会话。" }))),
    list
  );
}

function projectRow(project, description = null) {
  const projectId = project.id;
  const path = project.cwd || project.name || project.id;
  const mapping = findProjectPathMapping(path);
  state.projectNames.set(projectId, path);
  state.projectCache.set(projectId, project);
  const titleLine = h("div", { className: "row-title-line" }, h("span", { className: "row-title", text: shortPath(path) }));
  if (mapping) titleLine.append(tag("已重定向", "info"));
  if (project.grouping_reason === "cwd_collision") titleLine.append(tag("编码碰撞·已拆分", "info"));
  if (project.path_exists === 0 && !mapping) titleLine.append(tag("目录疑似已移动", "warning"));
  if (project.automatic_session_count) titleLine.append(tag(`自动/下属 ${project.automatic_session_count}`, "info"));
  const virtualProject = projectId !== (project.record_project_id || projectId);
  return h("div", { className: "list-row has-check" },
    h("label", { className: "check-wrap", ariaLabel: virtualProject ? "逻辑项目不能执行物理目录批量操作" : "选择项目" }, h("input", { type: "checkbox", disabled: virtualProject, checked: state.selectedProjects.has(projectId), dataset: { change: "select-project", projectId } })),
    h("button", { className: "row-click", type: "button", dataset: { action: "open-project", projectId, projectPath: path } },
      titleLine,
      h("p", { className: "row-description path", text: path }),
      h("p", { className: `row-description project-description${description?.description ? " is-generated" : ""}`, text: description?.description || "尚未生成项目简介" }),
      rowMeta([{ icon: "clock", text: `最近活跃 ${project.last_active || "未知"}` }])
    ),
    h("div", { className: "row-side" },
      h("div", { className: "metric" }, h("strong", { text: formatNumber(project.session_count) }), h("span", { text: "会话" })),
      h("div", { className: "metric" }, h("strong", { text: formatNumber(project.total_tokens) }), h("span", { text: "tokens" })),
      h("span", { className: "icon-button", ariaHidden: "true" }, icon("chevronRight"))
    )
  );
}

function updateActiveNav() {
  const mainRoute = ["project", "session"].includes(state.route) ? "projects" : state.route;
  document.querySelectorAll("[data-route]").forEach((node) => node.classList.toggle("is-active", node.dataset.route === mainRoute));
}

function setBreadcrumbs(items) {
  const root = $("#breadcrumbs");
  root.replaceChildren();
  items.forEach((item, index) => {
    if (index) root.append(h("span", { className: "breadcrumb-separator", text: "/" }));
    if (item.route) root.append(h("button", { type: "button", className: "breadcrumb-button", text: item.label, dataset: { action: "breadcrumb", route: item.route, projectId: item.projectId || "", projectPath: item.projectPath || "" } }));
    else root.append(h("span", { className: "breadcrumb-current", text: item.label }));
  });
}

function routeHash(route, params) {
  if (route === "project") return `#/project/${encode(params.projectId)}`;
  if (route === "session") return `#/session/${encode(params.projectId)}/${encode(params.sessionId)}`;
  if (route === "search") return `#/search?q=${encode(params.q || "")}`;
  return `#/${route}`;
}

function navigate(route, params = {}, { push = true, scroll = true } = {}) {
  state.route = route;
  state.params = params;
  if (params.projectPath && params.projectId) state.projectNames.set(params.projectId, params.projectPath);
  updateActiveNav();
  if (push) history.pushState({ route, params }, "", routeHash(route, params));
  if (scroll) pageScroll.scrollTop = 0;
  renderCurrentPage();
}

async function renderCurrentPage() {
  const token = ++state.renderToken;
  state.launchContexts.clear();
  skeletonPage();
  try {
    if (state.route === "dashboard") await renderDashboard(token);
    else if (state.route === "projects") await renderProjects(token);
    else if (state.route === "sessions") await renderSessions(token);
    else if (state.route === "project") await renderProject(token, state.params.projectId);
    else if (state.route === "session") await renderSession(token, state.params.projectId, state.params.sessionId);
    else if (state.route === "search") await renderSearch(token, state.params.q || "");
    else if (state.route === "settings") await renderSettings(token);
    else navigate("dashboard", {}, { push: false });
  } catch (error) {
    if (token === state.renderToken) errorPage(error);
  }
}

async function renderDashboard(token) {
  setBreadcrumbs([{ label: "工作台" }]);
  const data = await api("/api/v2/dashboard");
  if (token !== state.renderToken) return;
  const stats = data.stats || {};
  const primaryMessages = stats.total_primary_messages ?? stats.total_messages ?? 0;
  const automaticMessages = stats.total_automatic_messages ?? 0;
  const apiTokens = stats.api_tokens_30d ?? 0;
  const apiResponses = stats.api_unique_responses_30d ?? 0;
  const list = h("div", { className: "list" });
  const recent = data.recent_sessions || [];
  recent.forEach((session) => list.append(...sessionEntry(session)));
  if (!recent.length) list.append(emptyState("暂无最近会话", "重建索引后，最近活动会显示在这里。", "message"));
  pageRoot.replaceChildren(
    pageHeading("Overview", "工作台", "查看本地 Claude Code 记录与近 30 天 API 用量。", [button("刷新索引", "reindex", { kind: "secondary", iconName: "refresh" })]),
    h("div", { className: "stats-grid" },
      statCard("项目", formatExactNumber(stats.total_projects), "已建立本地索引", "folder"),
      statCard("主会话", formatExactNumber(stats.total_sessions), `自动/下属另计 ${formatExactNumber(stats.total_automatic_sessions)} 个`, "message"),
      statCard("主会话记录", formatExactNumber(primaryMessages), `本地 user/assistant 记录；自动任务另计 ${formatExactNumber(automaticMessages)} 条`, "database"),
      statCard("近 30 天 Token", formatNumber(apiTokens), `全部本机模型，含缓存 · ${formatExactNumber(apiResponses)} 个唯一响应`, "token")
    ),
    h("div", { className: "dashboard-grid" }, renderApiUsage(data.api_usage || [], data.api_usage_period || {}), panel("最近会话", "按最后活跃时间排序", list))
  );
}

function renderApiUsage(rows, period) {
  const range = period.start && period.end ? `${period.start} 至 ${period.end}` : "近 30 个自然日";
  const body = h("div", { className: "usage-summary" });
  if (!rows.length) {
    body.append(emptyState("暂无 API 用量", "刷新索引后，将从本机保留的会话日志中统计。", "activity"));
    return panel("本机 API 用量", `${range} · 按唯一响应去重`, body);
  }
  body.append(h("div", { className: "usage-head" },
    h("span", { text: "模型" }),
    h("span", { text: "唯一响应" }),
    h("span", { text: "Token（含缓存）" })
  ));
  rows.forEach((row) => {
    const inputOutput = Number(row.input_tokens || 0) + Number(row.output_tokens || 0);
    const cache = Number(row.cache_creation_tokens || 0) + Number(row.cache_read_tokens || 0);
    body.append(h("div", { className: "usage-row" },
      h("div", { className: "usage-model" },
        h("strong", { text: row.model || "unknown" }),
        h("small", { text: `输入+输出 ${formatExactNumber(inputOutput)} · 缓存 ${formatExactNumber(cache)}` })
      ),
      h("strong", { className: "usage-responses", text: formatExactNumber(row.unique_responses) }),
      h("strong", { className: "usage-tokens", text: formatExactNumber(row.total_tokens) })
    ));
  });
  body.append(h("p", { className: "usage-note", text: "本机日志估算：Token 已按响应 ID 去重，并包含输入、输出、缓存创建与缓存读取。供应商后台还可能包含其他设备、已删除会话或不同请求口径。" }));
  return panel("本机 API 用量", `${range} · 按唯一响应去重`, body);
}

async function renderProjects(token) {
  setBreadcrumbs([{ label: "项目列表" }]);
  const view = state.projects;
  const prefix = view.dirParts.join("\\");
  const [data, dirs, descriptions] = await Promise.all([
    api(`/api/v2/projects?q=${encode(view.q)}&drive=${encode(view.drive)}&sort=${encode(view.sort)}&path_prefix=${encode(prefix)}&limit=${view.limit}&offset=${view.offset}`),
    api(`/api/v2/project-dirs?prefix=${encode(prefix)}`),
    api("/api/descriptions")
  ]);
  if (token !== state.renderToken) return;
  view.data = data;
  view.dirs = dirs;
  (data.items || []).forEach((project) => { state.projectCache.set(project.id, project); state.projectNames.set(project.id, project.cwd || project.name || project.id); });
  const drive = h("select", { id: "project-drive", dataset: { change: "project-filter" } }, h("option", { value: "", text: "全部盘符" }));
  (data.drives || []).forEach((value) => drive.append(h("option", { value, text: value, selected: view.drive === value })));
  const sort = h("select", { id: "project-sort", dataset: { change: "project-filter" } },
    ...[["active", "最近活跃"], ["name", "路径名称"], ["sessions", "会话最多"], ["tokens", "Token 最多"], ["oldest", "最早活跃"]].map(([value, label]) => h("option", { value, text: label, selected: view.sort === value }))
  );
  const toolbar = h("div", { className: "toolbar" },
    h("label", { className: "field field-grow" }, h("span", { text: "路径关键词" }), h("input", { id: "project-query", value: view.q, placeholder: "输入项目路径…", dataset: { enter: "project-filter" } })),
    h("label", { className: "field" }, h("span", { text: "磁盘" }), drive),
    h("label", { className: "field" }, h("span", { text: "排序" }), sort),
    button("筛选", "project-filter", { kind: "primary", iconName: "search" })
  );
  const browser = directoryBrowser(dirs);
  const list = h("div", { className: "list" });
  (data.items || []).forEach((project) => list.append(projectRow(project, descriptions?.[project.id])));
  if (!(data.items || []).length) list.append(emptyState("没有匹配项目", "调整路径、盘符或目录范围后再试。", "folder"));
  const projectPanel = panel("项目列表", `${formatNumber(data.total)} 个项目`, h("div", {}, list, pager(data.total || 0, data.offset || 0, data.limit || view.limit, "projects")));
  pageRoot.replaceChildren(
    pageHeading("Workspace", "项目列表", "按真实路径浏览、筛选和整理 Claude Code 项目记录。", [
      button("一键生成全部简介", "describe-all", { kind: "primary", iconName: "spark" }),
      button("刷新索引", "reindex", { kind: "secondary", iconName: "refresh" })
    ]),
    toolbar, browser, projectPanel, projectBatchBar()
  );
}

function directoryBrowser(data) {
  const crumbs = h("div", { className: "directory-crumbs" }, h("button", { type: "button", className: "crumb-link", text: "全部", dataset: { action: "project-dir-depth", depth: 0 } }));
  state.projects.dirParts.forEach((part, index) => crumbs.append(h("span", { text: "/" }), h("button", { type: "button", className: "crumb-link", text: part, dataset: { action: "project-dir-depth", depth: index + 1 } })));
  const chips = h("div", { className: "directory-chips" });
  (data.children || []).forEach((child) => chips.append(h("button", { type: "button", className: "chip", dataset: { action: "project-dir-enter", name: child.name } }, h("span", { text: child.name }), h("small", { text: child.count }))));
  if (!(data.children || []).length) chips.append(h("span", { className: "help-text", text: "当前层级没有更深目录。" }));
  return h("section", { className: "directory-browser" },
    h("div", { className: "directory-top" }, h("div", {}, h("strong", { text: "目录快速定位" }), h("span", { text: `当前范围 ${data.count || 0} 个项目` })), button("清空", "project-dir-clear", { kind: "ghost", small: true })),
    crumbs, chips
  );
}

function projectBatchBar() {
  const count = state.selectedProjects.size;
  return h("div", { className: "batch-bar", id: "project-batch-bar", hidden: !count },
    h("div", { className: "batch-count" }, h("strong", { id: "project-batch-count", text: count }), h("span", { text: "个项目已选择" })),
    h("div", { className: "batch-actions" },
      button("全选本页", "select-page-projects", { kind: "ghost", small: true }),
      button("清空", "clear-project-selection", { kind: "ghost", small: true }),
      button("批量移到回收站", "trash-selected-projects", { kind: "danger", iconName: "trash", small: true })
    )
  );
}

async function renderSessions(token) {
  setBreadcrumbs([{ label: "跨项目会话" }]);
  const view = state.sessions;
  const [data, orphanData] = await Promise.all([
    api(`/api/v2/sessions?q=${encode(view.q)}&limit=${view.limit}&offset=${view.offset}`),
    api(`/api/v2/orphan-history-sessions?q=${encode(view.q)}&limit=80`)
  ]);
  if (token !== state.renderToken) return;
  const toolbar = h("div", { className: "toolbar" },
    h("label", { className: "field field-grow" }, h("span", { text: "会话关键词" }), h("input", { id: "session-query", value: view.q, placeholder: "搜索标题、首条消息或目录…", dataset: { enter: "session-filter" } })),
    button("搜索", "session-filter", { kind: "primary", iconName: "search" })
  );
  const list = h("div", { className: "list" });
  (data.items || []).forEach((session) => list.append(...sessionEntry(session)));
  if (!(data.items || []).length) list.append(emptyState("没有匹配会话", "换一个关键词，或重建索引后再试。", "message"));
  const orphanList = h("div", { className: "list" });
  (orphanData.items || []).forEach((session) => orphanList.append(h("div", { className: "list-row" },
    h("div", { className: "list-main" },
      h("div", { className: "list-title", text: session.first_prompt || "历史会话" }),
      h("div", { className: "list-meta", text: `${session.project_path || "未知目录"} · ${session.substantive_count || 0}/${session.prompt_count || 0} 条有效指令 · ${session.session_id}` })
    ),
    h("span", { className: "tag warning", text: "主记录缺失·待人工处理" })
  )));
  if (!(orphanData.items || []).length) orphanList.append(emptyState("没有待恢复历史会话", "当前 history 记录均能找到对应主会话。", "message"));
  pageRoot.replaceChildren(
    pageHeading("Sessions", "跨项目会话", "服务端分页加载最近会话，不扫描全部 JSONL。"),
    toolbar,
    panel("主会话列表", `${formatNumber(data.total)} 个主会话`, h("div", {}, list, pager(data.total || 0, data.offset || 0, data.limit || view.limit, "sessions"))),
    panel("待恢复历史会话", `${formatNumber(orphanData.total || 0)} 个候选；仅提示，不会自动重建或重定向`, orphanList),
    automaticSessionsPanel(data)
  );
}

async function renderProject(token, projectId, force = false) {
  const view = state.projectViews.get(projectId) || { q: "", offset: 0, limit: 70 };
  state.projectViews.set(projectId, view);
  let projectData = state.projectData.get(projectId);
  if (!projectData || force) {
    const [sessions, descriptions, mappings] = await Promise.all([
      api(`/api/v2/project/${encode(projectId)}/sessions?q=${encode(view.q)}&limit=${view.limit}&offset=${view.offset}`),
      api("/api/descriptions"),
      api("/api/v2/path-mappings")
    ]);
    projectData = { sessions, descriptions, mappings };
    state.projectData.set(projectId, projectData);
    state.pathMappings = mappings || { mappings: {} };
  }
  if (token !== state.renderToken) return;
  const sessions = projectData.sessions || {};
  const first = (sessions.items || [])[0] || {};
  const path = state.projectNames.get(projectId) || first.project_name || first.cwd_initial || first.cwd || projectId;
  state.projectNames.set(projectId, path);
  const meta = state.projectCache.get(projectId) || {};
  const recordProjectId = meta.record_project_id || first.record_project_id || projectId;
  const virtualProject = projectId !== recordProjectId;
  const mapping = findProjectPathMapping(path);
  const openDirectoryPath = mapping?.new_path || path;
  const activeTab = state.projectTabs.get(projectId) || "sessions";
  setBreadcrumbs([{ label: "项目列表", route: "projects" }, { label: shortPath(path) }]);
  const oldPathMapping = findPathMapping(path);
  const launchKey = registerLaunchContext({ kind: "project", projectId, path: oldPathMapping ? mappedPath(path, oldPathMapping) : path, label: shortPath(path) });
  const tabs = h("div", { className: "tabs", role: "tablist", ariaLabel: "项目详情页签" });
  [["sessions", "会话列表"], ["location", "目录重定向与迁移"], ["ai", "AI 洞察与操作"], ["danger", "危险区域"]].forEach(([id, label]) => tabs.append(h("button", { type: "button", role: "tab", className: `tab-button${activeTab === id ? " is-active" : ""}`, ariaSelected: activeTab === id, text: label, dataset: { action: "project-tab", tab: id, projectId } })));
  const content = activeTab === "sessions" ? projectSessionsTab(projectId, sessions, view) : activeTab === "location" ? projectLocationTab(projectId, path, mapping, virtualProject) : activeTab === "ai" ? projectAiTab(projectId, projectData.descriptions || {}, sessions.total || 0, virtualProject) : projectDangerTab(projectId, path, virtualProject);
  pageRoot.replaceChildren(
    pageHeading("Project", shortPath(path), path, [
      button("打开项目目录", "open-project-directory", { kind: "secondary", iconName: "folder", dataset: { projectPath: openDirectoryPath } }),
      button("在当前路径启动", "open-launch", { kind: "primary", iconName: "play", dataset: { launchKey } })
    ]),
    h("div", { className: "project-summary-strip" },
      h("div", { className: "summary-metric path" }, h("span", { text: "项目路径" }), h("strong", { text: mapping?.new_path || path, title: mapping?.new_path || path })),
      h("div", { className: "summary-metric" }, h("span", { text: "主会话" }), h("strong", { text: formatNumber(sessions.total || meta.session_count) })),
      h("div", { className: "summary-metric" }, h("span", { text: "自动/下属" }), h("strong", { text: formatNumber(sessions.related_total || 0) })),
      h("div", { className: "summary-metric" }, h("span", { text: "Token（输入+输出）" }), h("strong", { text: meta.total_tokens === undefined ? "—" : formatNumber(meta.total_tokens) }))
    ),
    tabs,
    h("div", { className: "tab-panel" }, content)
  );
}

function projectSessionsTab(projectId, data, view) {
  const toolbar = h("div", { className: "toolbar" },
    h("label", { className: "field field-grow" }, h("span", { text: "项目内筛选" }), h("input", { id: "project-session-query", value: view.q, placeholder: "搜索会话标题、消息或目录…", dataset: { enter: "project-session-filter", projectId } })),
    button("搜索", "project-session-filter", { kind: "primary", iconName: "search", dataset: { projectId } })
  );
  const list = h("div", { className: "list" });
  (data.items || []).forEach((session) => list.append(...sessionEntry(session, { selectable: true })));
  if (!(data.items || []).length) list.append(emptyState("没有匹配会话", "当前项目没有符合筛选条件的会话。", "message"));
  return h("div", {}, toolbar, panel("项目主会话", `${formatNumber(data.total)} 个主会话`, h("div", {}, list, pager(data.total || 0, data.offset || 0, data.limit || view.limit, "project-sessions", projectId))), automaticSessionsPanel(data), sessionBatchBar(projectId));
}

function sessionBatchBar(projectId) {
  const count = selectedSessionSet(projectId).size;
  return h("div", { className: "batch-bar", id: "session-batch-bar", hidden: !count },
    h("div", { className: "batch-count" }, h("strong", { id: "session-batch-count", text: count }), h("span", { text: "个会话已选择" })),
    h("div", { className: "batch-actions" },
      button("全选本页", "select-page-sessions", { kind: "ghost", small: true, dataset: { projectId } }),
      button("清空", "clear-session-selection", { kind: "ghost", small: true, dataset: { projectId } }),
      button("批量移到回收站", "trash-selected-sessions", { kind: "danger", iconName: "trash", small: true, dataset: { projectId } })
    )
  );
}

function projectLocationTab(projectId, path, mapping, virtualProject = false) {
  const atTarget = isMappingTarget(path, mapping);
  const mappingCard = h("article", { className: "info-card" },
    h("h3", { text: mapping ? "当前目录重定向" : "设置目录重定向" }),
    h("p", { text: mapping ? "打开项目会优先进入新位置；路径映射本身不会移动会话记录。" : "项目工作区移动后，可为旧路径建立一个指向新位置的映射。" }),
    h("div", { className: "path-pair" },
      h("div", { className: "path-item" }, h("span", { text: "旧位置" }), h("code", { text: mapping?.old_path || path })),
      h("div", { className: "path-item" }, h("span", { text: "新位置" }), h("code", { text: mapping?.new_path || "尚未映射" }))
    ),
    h("div", { className: "form-actions" },
      button(mapping ? "重新选择位置" : "选择新位置", "map-project", { kind: "secondary", iconName: "folder", dataset: { projectId, oldPath: mapping?.old_path || path } }),
      mapping ? button("删除映射", "delete-path-map", { kind: "ghost", iconName: "x", dataset: { projectId, oldPath: mapping.old_path || path } }) : null
    )
  );
  const migrateCard = h("article", { className: "info-card" },
    h("h3", { text: atTarget ? "会话已位于重定向目录" : "迁移会话记录" }),
    h("p", { text: virtualProject ? "该项目来自一个发生编码碰撞的物理记录目录。为避免连带修改同目录中的其他项目，只能逐会话处理，不能整目录迁移。" : (atTarget ? "当前索引项目已经对应重定向后的目录，无需再次迁移会话记录。" : "把旧项目 JSONL 迁移到新路径对应的 Claude 项目目录，并重写其中的 cwd 前缀。") }),
    h("div", { className: "callout" }, icon("alert"), h("span", { text: "迁移会修改 JSONL 内容；原始文件会先备份到 data/migrations/。此操作不移动真实项目文件。" })),
    h("div", { className: "form-actions" }, button(virtualProject ? "编码碰撞项目仅支持逐会话处理" : (atTarget ? "已完成重定向" : "迁移会话"), "migrate-project", { kind: "primary", iconName: atTarget ? "check" : "refresh", disabled: virtualProject || !mapping || atTarget, dataset: { projectId, oldPath: mapping?.old_path || path, newPath: mapping?.new_path || "" } }))
  );
  return h("div", { className: "location-grid" }, mappingCard, migrateCard);
}

function projectAiTab(projectId, descriptions, total, virtualProject = false) {
  const description = descriptions[projectId] || {};
  const progress = state.summaryProgress.get(projectId);
  const progressBox = h("div", { className: "progress-box", hidden: !progress },
    h("div", { className: "progress-track" }, h("div", { className: `progress-fill${progress?.running ? " is-running" : ""}`, style: progress && !progress.running ? `width:${progress.percent || 100}%` : "" })),
    h("div", { className: "progress-counts" },
      h("span", { text: `已处理：${progress?.processed || 0}/${progress?.total ?? total}` }),
      h("span", { text: `跳过：${progress?.skipped || 0}` }),
      h("span", { text: `失败：${progress?.failed || 0}` })
    )
  );
  return h("div", { className: "ai-grid" },
    h("article", { className: "info-card" },
      h("h3", { text: "项目简介" }),
      h("p", { text: "仅在主动生成时，将用于简介的内容发送至已配置的 AI Provider。" }),
      h("div", { className: "description-content", text: description.description || "尚未生成项目简介。" }),
      description.updated_at ? h("div", { className: "description-meta", text: `更新于 ${description.updated_at}${description.model ? ` · ${description.model}` : ""}` }) : null,
      h("div", { className: "form-actions" }, button(virtualProject ? "逻辑项目暂不支持整项目 AI 操作" : (description.description ? "重新生成" : "生成项目简介"), "describe-project", { kind: "secondary", iconName: "spark", disabled: virtualProject, dataset: { projectId } }))
    ),
    h("article", { className: "info-card" },
      h("h3", { text: "批量总结会话" }),
      h("p", { text: `连续调用 AI，为尚无摘要的会话生成总结；已有摘要会跳过。当前项目共 ${total} 个会话，后端最多处理 500 个。` }),
      button(progress?.running ? "正在生成…" : (virtualProject ? "逻辑项目暂不支持批量总结" : "开始批量总结"), "summarize-project", { kind: "primary", iconName: "spark", disabled: virtualProject || progress?.running, dataset: { projectId, total } }),
      progressBox
    )
  );
}

function projectDangerTab(projectId, path, virtualProject = false) {
  return h("section", { className: "danger-zone" },
    h("h2", { text: "将项目记录移到回收站" }),
    h("p", { text: virtualProject ? "该逻辑项目与其他项目共用 Claude 物理记录目录。整目录移动会误伤其他项目，因此已禁用；可在会话列表中逐条移到回收站。" : "此操作会移动该项目目录下的原始 JSONL 记录至 data/trash/projects/。项目工作区文件不会被删除，但当前界面暂不提供回收站恢复功能。" }),
    button(virtualProject ? "编码碰撞项目禁止整目录移动" : "移到回收站", "trash-project", { kind: "danger", iconName: "trash", disabled: virtualProject, dataset: { projectId, projectPath: path } })
  );
}

async function renderSession(token, projectId, sessionId) {
  const key = `${projectId}/${sessionId}`;
  const view = state.sessionViews.get(key) || { role: "", offset: 0, limit: 120 };
  state.sessionViews.set(key, view);
  const [data, mappings] = await Promise.all([
    api(`/api/v2/session/${encode(projectId)}/${encode(sessionId)}?role=${encode(view.role)}&limit=${view.limit}&offset=${view.offset}`),
    api("/api/v2/path-mappings")
  ]);
  if (token !== state.renderToken) return;
  state.pathMappings = mappings || { mappings: {} };
  const session = data.session || {};
  const isPrimary = (session.session_kind || "primary") === "primary" && !session.parent_session_id;
  const recordProjectId = session.record_project_id || projectId;
  const projectPath = session.project_name || session.cwd_initial || session.cwd || projectId;
  state.projectNames.set(projectId, projectPath);
  setBreadcrumbs([{ label: "项目列表", route: "projects" }, { label: shortPath(projectPath), route: "project", projectId, projectPath }, { label: `会话：${session.title || sessionId}` }]);
  const launchKey = isPrimary ? registerLaunchContext({ kind: "session", projectId: recordProjectId, logicalProjectId: projectId, sessionId, path: session.cwd_initial || session.cwd || projectPath, label: session.title || sessionId }) : "";
  const roleButtons = h("div", { className: "segmented" });
  [["", "全部"], ["user", "用户"], ["assistant", "助手"]].forEach(([role, label]) => roleButtons.append(h("button", { type: "button", className: `segmented-button${view.role === role ? " is-active" : ""}`, text: label, dataset: { action: "message-role", role, projectId, sessionId } })));
  const messages = h("div", { className: "message-list" });
  (data.messages || []).forEach((message) => messages.append(messageBlock(message)));
  if (!(data.messages || []).length) messages.append(emptyState("没有匹配消息", "此角色筛选下没有可显示的消息。", "message"));
  const reader = h("section", { className: "panel" },
    h("div", { className: "reader-toolbar" }, h("div", {}, h("strong", { text: "消息阅读器" })), roleButtons),
    messages,
    pager(data.total || 0, data.offset || 0, data.limit || view.limit, "messages", projectId)
  );
  reader.dataset.sessionId = sessionId;
  const lineage = !isPrimary ? h("div", { className: "lineage-callout" },
    icon("activity"),
    h("div", {}, h("strong", { text: sessionKindLabel(session.session_kind) }), h("p", { text: session.parent ? `归属于母会话：${session.parent.title || session.parent.id}` : "这是自动创建的会话，目前没有足够证据确定母会话。" })),
    session.parent ? button("查看母会话", "open-session", { kind: "secondary", small: true, dataset: { projectId: session.parent.project_id, sessionId: session.parent.id } }) : null
  ) : h("div", { hidden: true });
  const actions = [];
  if (isPrimary) actions.push(button("生成总结", "summarize-session", { kind: "secondary", iconName: "spark", dataset: { projectId: recordProjectId, sessionId } }), button("恢复会话", "open-launch", { kind: "primary", iconName: "play", dataset: { launchKey } }), button("移到回收站", "trash-session", { kind: "danger", iconName: "trash", dataset: { projectId: recordProjectId, logicalProjectId: projectId, sessionId } }));
  pageRoot.replaceChildren(
    pageHeading("Session", session.title || sessionId, isPrimary ? "按角色进行服务端分页，工具调用默认折叠。" : "自动会话仅供查看，默认不提供恢复和删除操作。", actions),
    lineage,
    h("div", { className: "session-overview" },
      summaryMetric("消息", formatNumber(session.total_msgs)), summaryMetric("Token（输入+输出）", formatNumber(session.total_tokens)), summaryMetric("模型", session.model || "unknown"), summaryMetric("最近活跃", session.last_active || session.created_at || "未知")
    ),
    h("div", { className: "cwd-grid" },
      h("div", { className: "cwd-card is-initial" }, h("span", { text: "起始目录 · Initial CWD" }), h("code", { text: session.cwd_initial || session.cwd || "未知" })),
      h("div", { className: "cwd-card" }, h("span", { text: "当前目录 · Current CWD" }), h("code", { text: session.cwd || "未知" }))
    ),
    session.path_exists === 0 && !findPathMapping(session.cwd_initial || session.cwd || projectPath) ? h("div", { className: "lineage-callout" }, icon("alert"), h("div", {}, h("strong", { text: "原目录不存在，可能已经移动" }), h("p", { text: "管理器不会自动选择目标位置。请回到项目的“目录重定向与迁移”页签，由你确认新的目录。" }))) : null,
    h("div", { className: "session-summary-card" }, h("span", { text: "AI 会话总结" }), h("p", { text: session.ai_summary || "尚未生成会话总结。" })),
    reader
  );
}

function summaryMetric(label, value) { return h("div", { className: "summary-metric" }, h("span", { text: label }), h("strong", { text: value })); }

function messageBlock(message) {
  const original = String(message.text || "");
  const truncated = original.length > 16000;
  const raw = truncated ? original.slice(0, 16000) : original;
  const role = message.role === "user" ? "user" : "assistant";
  const article = h("article", { className: `message is-${role}` },
    h("header", { className: "message-head" },
      h("span", { className: "message-role", text: role === "user" ? "用户" : "助手" }),
      h("span", { text: `#${message.idx ?? "—"}` }),
      h("span", { text: message.timestamp || "" }),
      h("span", { text: `${formatNumber(message.total_tokens)} tokens` })
    )
  );
  const isTool = /^\s*\[(tool_use|tool_result)\]/.test(raw);
  if (isTool) {
    const details = h("details", { className: "tool-detail" }, h("summary", { text: raw.split("\n")[0].slice(0, 180) || "工具调用" }));
    const body = h("div", { className: "message-body" });
    appendMessageContent(body, raw);
    details.append(body);
    article.append(details);
  } else {
    const body = h("div", { className: "message-body" });
    appendMessageContent(body, raw);
    article.append(body);
  }
  if (truncated) article.append(h("div", { className: "truncation-note" }, icon("alert"), h("span", { text: "消息超过 16,000 字符，已在前端安全截断。" })));
  return article;
}

function appendMessageContent(container, raw) {
  const parts = String(raw || "").split("```");
  parts.forEach((part, index) => {
    if (index % 2 === 0) {
      if (part) container.append(h("p", { className: "message-text", text: part }));
      return;
    }
    let code = part;
    let language = "";
    const lineBreak = code.indexOf("\n");
    if (lineBreak >= 0 && code.slice(0, lineBreak).trim().length < 32) {
      language = code.slice(0, lineBreak).trim();
      code = code.slice(lineBreak + 1);
    }
    const pre = h("pre", { className: "code-block" });
    if (language) pre.append(h("span", { className: "code-label", text: language }));
    pre.append(h("code", { text: code }));
    container.append(pre);
  });
}

async function renderSearch(token, query) {
  state.search.q = query;
  setBreadcrumbs([{ label: "工作台", route: "dashboard" }, { label: "搜索结果" }]);
  $("#global-search-input").value = query;
  const data = await api(`/api/v2/search?q=${encode(query)}&limit=${state.search.limit}&offset=${state.search.offset}`);
  if (token !== state.renderToken) return;
  const list = h("div", { className: "list" });
  (data.items || []).forEach((result) => list.append(searchResultRow(result)));
  if (!(data.items || []).length) list.append(emptyState(query ? "没有匹配结果" : "输入关键词开始搜索", query ? "尝试更短或更具体的关键词。" : "全局搜索会匹配项目路径、会话标题和消息正文。", "search"));
  pageRoot.replaceChildren(
    pageHeading("Search", "搜索结果", query ? `关键词：${query}` : "使用顶部搜索框检索本地 FTS5 索引。"),
    panel("匹配项", `${formatNumber(data.total ?? (data.items || []).length)} 个结果`, list)
  );
}

function searchResultRow(result) {
  const isProject = result.type === "project";
  const isAutomatic = !isProject && result.session_kind && result.session_kind !== "primary";
  const title = result.title || result.session_id || result.project_id || "未命名";
  const buttonNode = h("button", { className: "row-click", type: "button", dataset: isProject ? { action: "open-project", projectId: result.project_id, projectPath: result.path || result.title || "" } : { action: "open-session", projectId: result.project_id, sessionId: result.session_id } },
    h("div", { className: "row-title-line" }, tag(isProject ? "项目" : (isAutomatic ? sessionKindLabel(result.session_kind) : "会话"), isProject || isAutomatic ? "info" : "success"), h("span", { className: "row-title", text: title }), result.parent_session_id ? tag("来自下属会话", "warning") : null),
    highlightedSnippet(result.snippet || ""),
    rowMeta([{ icon: "folder", text: result.path || "" }, { icon: "clock", text: result.last_active || "" }])
  );
  return h("div", { className: "list-row search-result" }, buttonNode, h("span", { className: "icon-button", ariaHidden: "true" }, icon("chevronRight")));
}

function highlightedSnippet(value) {
  const paragraph = h("p", { className: "row-description" });
  const parts = String(value).split(/(<mark>|<\/mark>)/i);
  let marked = false;
  parts.forEach((part) => {
    if (/^<mark>$/i.test(part)) { marked = true; return; }
    if (/^<\/mark>$/i.test(part)) { marked = false; return; }
    if (!part) return;
    paragraph.append(marked ? h("mark", { text: part }) : document.createTextNode(part));
  });
  return paragraph;
}

async function renderSettings(token) {
  setBreadcrumbs([{ label: "系统设置" }]);
  const [config, mappings] = await Promise.all([api("/api/config"), api("/api/v2/path-mappings")]);
  if (token !== state.renderToken) return;
  state.config = config;
  state.pathMappings = mappings || { mappings: {} };
  const prefs = loadLaunchPreferences(config);
  const aiSection = settingsSection("AI 服务配置", "Provider、Endpoint、模型与密钥。旧密钥绝不回显。", "spark", aiConfigForm(config));
  const launchSection = settingsSection("启动与偏好", "默认工作区与统一权限模式保存在本机。", "terminal", launchPreferencesForm(prefs));
  const maintenance = settingsSection("数据索引维护", "维护 SQLite / FTS5 索引及批量 AI 能力。", "database", h("div", { className: "form-stack" },
    h("p", { className: "help-text", text: "“刷新索引”只解析新增或变化的记录，适合日常使用；“完整重建”会重新解析全部 JSONL，仅用于索引损坏或升级后的深度维护。" }),
    h("div", { className: "form-actions" }, button("刷新索引", "reindex", { kind: "secondary", iconName: "refresh" }), button("完整重建", "reindex-full", { kind: "ghost", iconName: "database" }), button("为所有项目生成简介", "describe-all", { kind: "secondary", iconName: "spark" }))
  ));
  const redirects = directoryRedirectSettings(state.pathMappings);
  const appSection = settingsSection("应用与高级操作", "关闭本地 HTTP 服务的最终安全出口。", "settings", h("div", { className: "form-stack" },
    h("p", { className: "help-text", text: "关闭管理器不会删除任何项目、会话或索引数据。" }),
    h("div", { className: "form-actions" }, button("关闭管理器", "settings-shutdown", { kind: "danger", iconName: "x" }))
  ), "danger-section");
  pageRoot.replaceChildren(pageHeading("Preferences", "系统设置", "集中管理 AI 服务、启动偏好、目录重定向、索引维护与应用操作。"), h("div", { className: "settings-grid" }, aiSection, launchSection, redirects, maintenance, appSection));
}

function directoryRedirectSettings(mappings) {
  const entries = Object.values(mappings?.mappings || {});
  const content = h("div", { className: "mapping-list" });
  if (!entries.length) {
    content.append(emptyState("暂无目录重定向", "在项目详情的“目录重定向与迁移”页签中可以新增映射。", "folder"));
  } else {
    entries.forEach((mapping) => content.append(h("div", { className: "mapping-row" },
      h("div", { className: "mapping-path" }, h("span", { text: "原目录" }), h("code", { text: mapping.old_path || "", title: mapping.old_path || "" })),
      h("span", { className: "mapping-arrow" }, icon("arrow")),
      h("div", { className: "mapping-path" }, h("span", { text: "重定向到" }), h("code", { text: mapping.new_path || "", title: mapping.new_path || "" })),
      button("删除", "delete-global-path-map", { kind: "ghost", iconName: "x", small: true, dataset: { oldPath: mapping.old_path || "" } })
    )));
  }
  return settingsSection("目录重定向", `当前共有 ${entries.length} 条映射。项目启动时会优先使用重定向后的目录。`, "folder", content, "span-2");
}

function settingsSection(title, description, iconName, content, extraClass = "") {
  return h("section", { className: `settings-section ${extraClass}`.trim() },
    h("div", { className: "section-heading" }, h("span", { className: "section-icon" }, icon(iconName)), h("div", {}, h("h2", { text: title }), h("p", { text: description }))),
    content
  );
}

function aiConfigForm(config) {
  const provider = h("select", { id: "config-provider", dataset: { change: "provider-change" } }, h("option", { value: "deepseek", text: "DeepSeek", selected: config.provider === "deepseek" }), h("option", { value: "anthropic", text: "Anthropic", selected: config.provider === "anthropic" }));
  const model = h("select", { id: "config-model" });
  populateModels(model, config.provider || "deepseek", config.api_model);
  return h("form", { className: "form-stack", id: "ai-config-form" },
    h("label", { className: "field" }, h("span", { text: "Provider" }), provider),
    h("label", { className: "field" }, h("span", { text: "Endpoint" }), h("input", { id: "config-endpoint", value: config.api_endpoint || "", autocomplete: "off", spellcheck: false })),
    h("label", { className: "field" }, h("span", { text: "Model" }), model),
    h("label", { className: "field" }, h("span", { text: "API Key" }), h("input", { id: "config-key", type: "password", value: "", autocomplete: "new-password", placeholder: config.api_key_available ? `${config.api_key_masked || "已配置"}；留空保留原密钥` : "尚未配置" })),
    h("div", { className: "config-status" }, h("span", { className: `status-dot ${config.api_key_available ? "is-ok" : "is-error"}` }), h("span", { text: config.api_key_available ? `API Key 已保留${config.api_key_masked ? `（${config.api_key_masked}）` : ""}` : "AI 功能当前不可用" })),
    h("div", { className: "form-actions" }, button("保存 AI 配置", "save-ai-config", { kind: "primary" }))
  );
}

function populateModels(select, provider, selected = "") {
  select.replaceChildren();
  const models = MODEL_CATALOG[provider] || {};
  Object.entries(models).forEach(([value, label], index) => select.append(h("option", { value, text: label, selected: value === selected || (!selected && index === 0) })));
}

function loadLaunchPreferences(config = {}) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("ccm.launchPreferences") || "{}"); } catch { /* ignore invalid local state */ }
  return { path: saved.path || config.ql_path || config.ql_default_path || "", permission: saved.permission || config.ql_perm || "std" };
}

function launchPreferencesForm(prefs) {
  const permission = h("select", { id: "preference-permission" });
  Object.entries(PERMISSIONS).forEach(([value, item]) => permission.append(h("option", { value, text: item.label, selected: prefs.permission === value })));
  return h("form", { className: "form-stack", id: "launch-preferences-form" },
    h("label", { className: "field" }, h("span", { text: "默认工作区" }), h("input", { id: "preference-path", value: prefs.path, spellcheck: false, autocomplete: "off" })),
    h("div", { className: "form-actions" }, button("选择目录", "pick-preference-folder", { kind: "ghost", iconName: "folder" })),
    h("label", { className: "field" }, h("span", { text: "默认权限" }), permission),
    h("p", { className: "help-text", text: "启动偏好存储在当前浏览器的 LocalStorage；实际启动时后端也会保存该路径与权限。" }),
    h("div", { className: "form-actions" }, button("保存启动偏好", "save-launch-preferences", { kind: "primary" }), button("使用此配置启动", "settings-quick-launch", { kind: "secondary", iconName: "play" }))
  );
}

function openLaunchCenter(context) {
  const config = state.config || {};
  const prefs = loadLaunchPreferences(config);
  const mapping = context.kind === "session" ? findPathMapping(context.path) : null;
  const blocked = Boolean(context.kind === "session" && mapping);
  const finalContext = { ...context, migrationBlocked: blocked, mapping };
  if (context.kind === "project") {
    const projectMapping = findPathMapping(context.path);
    if (projectMapping) finalContext.path = mappedPath(context.path, projectMapping);
  }
  if (context.kind === "quick" && !finalContext.path) finalContext.path = prefs.path;
  state.launchContext = finalContext;
  $("#launch-context-label").textContent = context.kind === "session" ? "恢复已有会话" : context.kind === "project" ? "打开项目工作区" : "快速启动";
  const contextCard = $("#launch-context-card");
  contextCard.replaceChildren(h("span", { text: context.kind === "session" ? "会话上下文" : context.kind === "project" ? "项目上下文" : "空上下文" }), h("strong", { text: context.label || "新建 Claude Code 会话" }));
  const pathInput = $("#launch-path");
  pathInput.value = finalContext.path || "";
  pathInput.readOnly = context.kind === "session";
  $("#launch-pick-folder").hidden = context.kind === "session";
  const permissions = $("#launch-permissions");
  permissions.replaceChildren();
  Object.entries(PERMISSIONS).forEach(([value, item]) => {
    const input = h("input", { type: "radio", name: "launch-permission", value, checked: (prefs.permission || "std") === value, dataset: { change: "launch-permission" } });
    permissions.append(h("label", { className: "permission-option" }, input, h("span", {}, h("strong", { text: item.label }), h("small", { text: item.description }))));
  });
  updatePermissionPreview();
  $("#launch-migration-warning").hidden = !blocked;
  $("#launch-submit").disabled = blocked;
  $("#launch-error").hidden = true;
  launchDialog.showModal();
}

function updatePermissionPreview() {
  const selected = $("input[name='launch-permission']:checked");
  $("#permission-preview").textContent = PERMISSIONS[selected?.value || "std"].command;
}

async function submitLaunch() {
  const context = state.launchContext;
  if (!context || context.migrationBlocked) return;
  const path = $("#launch-path").value.trim();
  const permission = $("input[name='launch-permission']:checked")?.value || "std";
  const error = $("#launch-error");
  if (!path) { error.textContent = "请选择或输入有效工作目录。"; error.hidden = false; return; }
  const submit = $("#launch-submit");
  submit.disabled = true;
  submit.textContent = "正在启动…";
  error.hidden = true;
  try {
    let result;
    if (context.kind === "quick") result = await post("/api/quick-launch", { path, permission });
    else result = await post("/api/open-claude", { path, project_id: context.projectId || "", session_id: context.sessionId || "", resume: context.kind === "session", permission });
    localStorage.setItem("ccm.launchPreferences", JSON.stringify({ path: context.kind === "quick" ? path : loadLaunchPreferences().path, permission }));
    launchDialog.close();
    toast(result.message || "启动请求已发送", result.ok === false ? "error" : "success");
  } catch (err) {
    if (err.data?.needs_migration) {
      context.migrationBlocked = true;
      $("#launch-migration-warning").hidden = false;
    }
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    submit.textContent = "启动 Claude Code";
    submit.disabled = Boolean(context.migrationBlocked);
  }
}

async function pickFolder() {
  const result = await api("/api/pick-folder");
  if (!result.path) throw new Error(result.error || "未选择目录");
  return result.path;
}

function askConfirm({ title, message, detail = "", confirmText = "确认", tone = "danger", eyebrow = "安全确认" }) {
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  $("#confirm-eyebrow").textContent = eyebrow;
  const detailNode = $("#confirm-detail");
  detailNode.textContent = detail;
  detailNode.hidden = !detail;
  const submit = $("#confirm-submit");
  submit.textContent = confirmText;
  submit.className = `button button-${tone}`;
  confirmDialog.showModal();
  return new Promise((resolve) => {
    const onClose = () => { confirmDialog.removeEventListener("close", onClose); resolve(confirmDialog.returnValue === "confirm"); };
    confirmDialog.addEventListener("close", onClose);
  });
}

async function reindex(full = false) {
  setGlobalLoading(true, full ? "正在完整重建索引" : "正在刷新索引", full ? "重新解析全部 JSONL 并更新 SQLite / FTS5…" : "仅解析新增或发生变化的 JSONL…");
  try {
    const result = await post("/api/v2/reindex", { full });
    state.projectData.clear();
    toast(`索引完成：${result.stats?.indexed || 0} 个会话已更新`, "success");
    await renderCurrentPage();
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

async function shutdownManager() {
  $("#shutdown-popover").hidden = true;
  try {
    await post("/api/shutdown", {});
    pageRoot.replaceChildren(h("div", { className: "empty-state" }, icon("check"), h("div", {}, h("strong", { text: "管理器已关闭" }), h("p", { text: "本地服务已停止，现在可以关闭此页面。" }))));
  } catch (error) { toast(error.message, "error"); }
}

async function executeAction(action, target) {
  const data = target.dataset;
  if (action === "retry-page") return renderCurrentPage();
  if (action === "open-quick-launch") return openLaunchCenter({ kind: "quick", path: loadLaunchPreferences(state.config || {}).path, label: "新建 Claude Code 会话" });
  if (action === "open-launch") return openLaunchCenter(state.launchContexts.get(data.launchKey));
  if (action === "submit-launch") return submitLaunch();
  if (action === "pick-launch-folder") {
    try { $("#launch-path").value = await pickFolder(); } catch (error) { toast(error.message, "error"); }
    return;
  }
  if (action === "go-to-migration") {
    const context = state.launchContext;
    launchDialog.close();
    state.projectTabs.set(context.projectId, "location");
    return navigate("project", { projectId: context.projectId, projectPath: state.projectNames.get(context.projectId) || context.path });
  }
  if (action === "breadcrumb") return navigate(data.route, data.route === "project" ? { projectId: data.projectId, projectPath: data.projectPath } : {});
  if (action === "open-project") return navigate("project", { projectId: data.projectId, projectPath: data.projectPath });
  if (action === "open-session") return navigate("session", { projectId: data.projectId, sessionId: data.sessionId });
  if (action === "open-project-directory") return openProjectDirectory(data.projectPath);
  if (action === "reindex") return reindex();
  if (action === "reindex-full") return reindex(true);
  if (action === "project-filter") {
    state.projects.q = $("#project-query")?.value.trim() || "";
    state.projects.drive = $("#project-drive")?.value || "";
    state.projects.sort = $("#project-sort")?.value || "active";
    state.projects.offset = 0;
    return renderCurrentPage();
  }
  if (action === "session-filter") { state.sessions.q = $("#session-query")?.value.trim() || ""; state.sessions.offset = 0; return renderCurrentPage(); }
  if (action === "project-dir-enter") { state.projects.dirParts.push(data.name); state.projects.offset = 0; return renderCurrentPage(); }
  if (action === "project-dir-depth") { state.projects.dirParts = state.projects.dirParts.slice(0, Number(data.depth)); state.projects.offset = 0; return renderCurrentPage(); }
  if (action === "project-dir-clear") { state.projects.dirParts = []; state.projects.offset = 0; return renderCurrentPage(); }
  if (action === "project-tab") { state.projectTabs.set(data.projectId, data.tab); return renderProject(++state.renderToken, data.projectId); }
  if (action === "project-session-filter") {
    const view = state.projectViews.get(data.projectId);
    view.q = $("#project-session-query")?.value.trim() || "";
    view.offset = 0;
    state.projectData.delete(data.projectId);
    return renderProject(++state.renderToken, data.projectId, true);
  }
  if (action === "page-prev" || action === "page-next") return changePage(data.scope, action === "page-next" ? 1 : -1, data.projectId, target.closest(".panel")?.dataset.sessionId || "");
  if (action === "select-page-projects") {
    (state.projects.data?.items || []).forEach((project) => state.selectedProjects.add(project.id));
    return renderCurrentPage();
  }
  if (action === "clear-project-selection") { state.selectedProjects.clear(); return renderCurrentPage(); }
  if (action === "select-page-sessions") {
    const items = state.projectData.get(data.projectId)?.sessions?.items || [];
    items.forEach((session) => selectedSessionSet(data.projectId).add(session.id));
    return renderProject(++state.renderToken, data.projectId);
  }
  if (action === "clear-session-selection") { selectedSessionSet(data.projectId).clear(); return renderProject(++state.renderToken, data.projectId); }
  if (action === "trash-selected-projects") return trashSelectedProjects();
  if (action === "trash-selected-sessions") return trashSelectedSessions(data.projectId);
  if (action === "map-project") {
    try {
      const path = await pickFolder();
      const result = await post("/api/v2/path-map", { old_path: data.oldPath, new_path: path });
      state.projectData.delete(data.projectId);
      toast(result.message || "路径映射已保存", "success");
      return renderProject(++state.renderToken, data.projectId, true);
    } catch (error) { toast(error.message, "error"); }
    return;
  }
  if (action === "delete-path-map") return deletePathMap(data.projectId, data.oldPath);
  if (action === "delete-global-path-map") return deleteGlobalPathMap(data.oldPath);
  if (action === "migrate-project") return migrateProject(data.projectId, data.oldPath, data.newPath);
  if (action === "describe-project") return describeProject(data.projectId);
  if (action === "summarize-project") return summarizeProject(data.projectId, Number(data.total || 0));
  if (action === "trash-project") return trashProject(data.projectId, data.projectPath);
  if (action === "message-role") {
    const view = state.sessionViews.get(`${data.projectId}/${data.sessionId}`);
    view.role = data.role;
    view.offset = 0;
    return renderCurrentPage();
  }
  if (action === "summarize-session") return summarizeSession(data.projectId, data.sessionId);
  if (action === "trash-session") return trashSession(data.projectId, data.sessionId, data.logicalProjectId || data.projectId);
  if (action === "save-ai-config") return saveAiConfig();
  if (action === "pick-preference-folder") {
    try { $("#preference-path").value = await pickFolder(); } catch (error) { toast(error.message, "error"); }
    return;
  }
  if (action === "save-launch-preferences") return saveLaunchPreferences();
  if (action === "settings-quick-launch") {
    saveLaunchPreferences(false);
    return openLaunchCenter({ kind: "quick", path: $("#preference-path").value.trim(), label: "使用设置中的启动偏好" });
  }
  if (action === "describe-all") return describeAll();
  if (action === "settings-shutdown") {
    if (await askConfirm({ title: "关闭管理器", message: "确认停止本地 HTTP 服务？当前页面随后将不可用。", confirmText: "关闭管理器" })) await shutdownManager();
    return;
  }
  if (action === "cancel-shutdown") { $("#shutdown-popover").hidden = true; $("#shutdown-menu-button").setAttribute("aria-expanded", "false"); return; }
  if (action === "confirm-shutdown") return shutdownManager();
}

function changePage(scope, direction, projectId, sessionId) {
  if (scope === "projects") state.projects.offset = Math.max(0, state.projects.offset + direction * state.projects.limit);
  else if (scope === "sessions") state.sessions.offset = Math.max(0, state.sessions.offset + direction * state.sessions.limit);
  else if (scope === "project-sessions") {
    const view = state.projectViews.get(projectId); view.offset = Math.max(0, view.offset + direction * view.limit); state.projectData.delete(projectId);
  } else if (scope === "messages") {
    const sid = sessionId || state.params.sessionId;
    const view = state.sessionViews.get(`${projectId}/${sid}`); view.offset = Math.max(0, view.offset + direction * view.limit);
  }
  pageScroll.scrollTop = 0;
  return renderCurrentPage();
}

async function openProjectDirectory(path) {
  try {
    const result = await post("/api/open-directory", { path });
    toast(result.message || "已打开项目目录", "success");
  } catch (error) {
    toast(error.message || "无法打开项目目录", "error");
  }
}

async function deletePathMap(projectId, oldPath) {
  const approved = await askConfirm({ title: "删除路径映射", message: "删除后，“打开项目”将不再自动进入新位置。此操作不会移动或删除任何 JSONL 文件。", detail: oldPath, confirmText: "删除映射", tone: "danger" });
  if (!approved) return;
  try {
    const result = await post("/api/v2/path-map-delete", { old_path: oldPath });
    state.projectData.delete(projectId);
    toast(result.message || "路径映射已删除", "success");
    await renderProject(++state.renderToken, projectId, true);
  } catch (error) { toast(error.message, "error"); }
}

async function deleteGlobalPathMap(oldPath) {
  const approved = await askConfirm({ title: "删除目录重定向", message: "删除后，项目启动将不再自动进入重定向后的目录。此操作不会移动或删除任何 JSONL 文件。", detail: oldPath, confirmText: "删除重定向", tone: "danger" });
  if (!approved) return;
  try {
    const result = await post("/api/v2/path-map-delete", { old_path: oldPath });
    state.pathMappings = await api("/api/v2/path-mappings");
    state.projectData.clear();
    toast(result.message || "目录重定向已删除", "success");
    await renderSettings(++state.renderToken);
  } catch (error) { toast(error.message, "error"); }
}

async function migrateProject(projectId, oldPath, newPath) {
  const approved = await askConfirm({
    eyebrow: "中风险维护",
    title: "迁移项目会话",
    message: "此操作将迁移 Claude 会话记录，并重写 JSONL 顶层 cwd 的旧路径前缀。真实项目工作区不会被移动。",
    detail: `旧位置：${oldPath}\n新位置：${newPath}\n备份目录：data/migrations/`,
    confirmText: "确认迁移",
    tone: "primary"
  });
  if (!approved) return;
  setGlobalLoading(true, "正在迁移会话", "备份原始 JSONL 并重写 cwd 前缀…");
  try {
    const result = await post("/api/v2/migrate-project", { project_id: projectId, new_path: newPath });
    state.projectData.clear();
    state.pathMappings = await api("/api/v2/path-mappings");
    toast(result.message || "会话迁移完成", result.failed ? "error" : "success");
    const nextId = result.new_project_id || projectId;
    navigate("project", { projectId: nextId, projectPath: result.new_path || newPath });
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

async function describeProject(projectId) {
  setGlobalLoading(true, "正在生成项目简介", "仅本次操作会调用已配置的 AI 服务…");
  try {
    const result = await post("/api/describe-project", { project_id: projectId });
    state.projectData.delete(projectId);
    toast(result.ok ? "项目简介已更新" : result.message || "生成失败", result.ok ? "success" : "error");
    await renderProject(++state.renderToken, projectId, true);
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

async function summarizeProject(projectId, total) {
  const approved = await askConfirm({
    eyebrow: "AI 消耗确认",
    title: "批量总结项目会话",
    message: "此操作会连续调用 AI API，为尚无摘要的会话生成总结。已有摘要会自动跳过，可能产生 API 费用并需要较长时间。",
    detail: `项目会话：${total} 个\n单次后端处理上限：500 个`,
    confirmText: "开始总结",
    tone: "primary"
  });
  if (!approved) return;
  state.summaryProgress.set(projectId, { running: true, total, processed: 0, skipped: 0, failed: 0 });
  await renderProject(++state.renderToken, projectId);
  try {
    const result = await post("/api/summarize-all", { project_id: projectId });
    state.summaryProgress.set(projectId, { running: false, total: result.total || total, processed: (result.success || 0) + (result.skipped || 0) + (result.failed || 0), skipped: result.skipped || 0, failed: result.failed || 0, percent: 100 });
    state.projectData.delete(projectId);
    toast(result.message || "批量总结完成", result.failed ? "error" : "success");
  } catch (error) {
    state.summaryProgress.set(projectId, { running: false, total, processed: 0, skipped: 0, failed: 1, percent: 100 });
    toast(error.message, "error");
  }
  await renderProject(++state.renderToken, projectId, true);
}

async function summarizeSession(projectId, sessionId) {
  setGlobalLoading(true, "正在生成会话总结", "正在提取用户与助手文本并调用 AI…");
  try {
    const result = await api(`/api/summarize?project=${encode(projectId)}&session=${encode(sessionId)}`);
    toast(result.ok ? "会话总结已更新" : result.error || "生成失败", result.ok ? "success" : "error");
    await renderCurrentPage();
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

async function trashProject(projectId, path) {
  const approved = await askConfirm({ title: "将项目移到回收站", message: "此操作会移动该项目的原始 Claude JSONL 记录。当前 UI 暂不提供恢复入口，请确认后继续。", detail: `${path}\n→ data/trash/projects/`, confirmText: "移到回收站" });
  if (!approved) return;
  try {
    const result = await post("/api/v2/trash-project", { project_id: projectId });
    state.projectData.delete(projectId);
    toast(result.message || "项目已移到回收站", "success");
    navigate("projects");
  } catch (error) { toast(error.message, "error"); }
}

async function trashSession(projectId, sessionId, logicalProjectId = projectId) {
  const approved = await askConfirm({ title: "将会话移到回收站", message: "只移动当前主会话 JSONL；下属会话不会被连带删除。项目工作区文件不会被修改。", detail: `会话：${sessionId}\n→ data/trash/sessions/${projectId}/`, confirmText: "移到回收站" });
  if (!approved) return;
  try {
    const result = await post("/api/v2/trash-session", { project_id: projectId, session_id: sessionId });
    state.projectData.delete(logicalProjectId);
    toast(result.message || "会话已移到回收站", "success");
    navigate("project", { projectId: logicalProjectId, projectPath: state.projectNames.get(logicalProjectId) || "" });
  } catch (error) { toast(error.message, "error"); }
}

async function trashSelectedProjects() {
  const ids = [...state.selectedProjects];
  if (!ids.length) return;
  const approved = await askConfirm({ title: `移动 ${ids.length} 个项目到回收站`, message: "选中项目的原始 JSONL 目录将移动到 data/trash/projects/。这是批量文件移动操作。", detail: ids.join("\n"), confirmText: "批量移到回收站" });
  if (!approved) return;
  setGlobalLoading(true, "正在批量移动项目", `处理 ${ids.length} 个项目…`);
  try {
    const result = await post("/api/v2/trash-projects", { project_ids: ids });
    state.selectedProjects.clear();
    state.projectData.clear();
    toast(result.message || "批量移动完成", result.failed ? "error" : "success");
    await renderCurrentPage();
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

async function trashSelectedSessions(projectId) {
  const ids = [...selectedSessionSet(projectId)];
  if (!ids.length) return;
  const approved = await askConfirm({ title: `移动 ${ids.length} 个会话到回收站`, message: "只移动选中的主会话 JSONL，下属会话不会被连带删除。单次最多处理 500 个会话。", detail: ids.join("\n"), confirmText: "批量移到回收站" });
  if (!approved) return;
  setGlobalLoading(true, "正在批量移动会话", `处理 ${ids.length} 个会话…`);
  try {
    const result = await post("/api/v2/trash-sessions", { project_id: projectId, session_ids: ids });
    selectedSessionSet(projectId).clear();
    state.projectData.delete(projectId);
    toast(result.message || "批量移动完成", result.failed ? "error" : "success");
    await renderProject(++state.renderToken, projectId, true);
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

async function saveAiConfig() {
  const payload = {
    provider: $("#config-provider").value,
    api_endpoint: $("#config-endpoint").value.trim(),
    api_model: $("#config-model").value
  };
  const key = $("#config-key").value.trim();
  if (key) payload.api_key = key;
  try {
    await post("/api/set-api-config", payload);
    state.config = await api("/api/config");
    toast("AI 配置已保存", "success");
    await renderSettings(++state.renderToken);
    pollStatus();
  } catch (error) { toast(error.message, "error"); }
}

function saveLaunchPreferences(showToast = true) {
  const path = $("#preference-path")?.value.trim() || "";
  const permission = $("#preference-permission")?.value || "std";
  localStorage.setItem("ccm.launchPreferences", JSON.stringify({ path, permission }));
  if (showToast) toast("启动偏好已保存在本机", "success");
}

async function describeAll() {
  const approved = await askConfirm({ eyebrow: "AI 消耗确认", title: "为所有项目生成简介", message: "此操作会依次为所有项目调用 AI 服务，可能耗时较长并产生 API 费用。", confirmText: "开始生成", tone: "primary" });
  if (!approved) return;
  setGlobalLoading(true, "正在生成全部项目简介", "请保持管理器运行，完成后会显示结果…");
  try {
    const result = await post("/api/describe-all", {});
    state.projectData.clear();
    toast(result.message || "全部项目简介生成完成", result.failed ? "error" : "success");
    await renderCurrentPage();
  } catch (error) { toast(error.message, "error"); }
  finally { setGlobalLoading(false); }
}

function updateBatchVisibility(kind) {
  if (kind === "project") {
    const bar = $("#project-batch-bar");
    if (!bar) return;
    bar.hidden = state.selectedProjects.size === 0;
    $("#project-batch-count").textContent = state.selectedProjects.size;
  } else {
    const projectId = state.params.projectId;
    const count = selectedSessionSet(projectId).size;
    const bar = $("#session-batch-bar");
    if (!bar) return;
    bar.hidden = count === 0;
    $("#session-batch-count").textContent = count;
  }
}

async function pollStatus() {
  const [claude, ai] = await Promise.allSettled([api("/api/claude-status"), api("/api/api-key-status")]);
  const claudeOk = claude.status === "fulfilled" && claude.value.available;
  const aiOk = ai.status === "fulfilled" && ai.value.available;
  $("#claude-status-dot").className = `status-dot ${claudeOk ? "is-ok" : "is-error"}`;
  $("#claude-status-text").textContent = claudeOk ? "可用" : "不可用";
  $("#ai-status-dot").className = `status-dot ${aiOk ? "is-ok" : "is-error"}`;
  $("#ai-status-text").textContent = aiOk ? "已配置" : "未配置";
}

document.addEventListener("click", async (event) => {
  const routeTarget = event.target.closest("[data-route]");
  if (routeTarget) { navigate(routeTarget.dataset.route); return; }
  const actionTarget = event.target.closest("[data-action]");
  if (actionTarget) {
    event.preventDefault();
    try { await executeAction(actionTarget.dataset.action, actionTarget); } catch (error) { toast(error.message || "操作失败", "error"); }
    return;
  }
  if (!event.target.closest(".shutdown-wrap")) {
    $("#shutdown-popover").hidden = true;
    $("#shutdown-menu-button").setAttribute("aria-expanded", "false");
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  const action = target.dataset.change;
  if (action === "select-project") {
    target.checked ? state.selectedProjects.add(target.dataset.projectId) : state.selectedProjects.delete(target.dataset.projectId);
    updateBatchVisibility("project");
  } else if (action === "select-session") {
    const set = selectedSessionSet(target.dataset.projectId);
    target.checked ? set.add(target.dataset.sessionId) : set.delete(target.dataset.sessionId);
    updateBatchVisibility("session");
  } else if (action === "project-filter") executeAction("project-filter", target);
  else if (action === "provider-change") {
    const model = $("#config-model");
    populateModels(model, target.value);
    const endpoint = $("#config-endpoint");
    if (target.value === "deepseek" && /anthropic/i.test(endpoint.value)) endpoint.value = "https://api.deepseek.com/v1/chat/completions";
    if (target.value === "anthropic" && /deepseek/i.test(endpoint.value)) endpoint.value = "https://api.anthropic.com/v1/messages";
    toast("模型列表已切换，请保存配置后生效", "info");
  } else if (action === "launch-permission") updatePermissionPreview();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing) return;
  const action = event.target.dataset.enter;
  if (action) { event.preventDefault(); executeAction(action, event.target); }
});

$("#global-search").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = $("#global-search-input").value.trim();
  state.search.offset = 0;
  navigate("search", { q: query });
});

$("#shutdown-menu-button").addEventListener("click", () => {
  const popover = $("#shutdown-popover");
  popover.hidden = !popover.hidden;
  $("#shutdown-menu-button").setAttribute("aria-expanded", String(!popover.hidden));
});

window.addEventListener("popstate", (event) => {
  if (event.state?.route) navigate(event.state.route, event.state.params || {}, { push: false });
  else navigate("dashboard", {}, { push: false });
});

async function initialize() {
  try {
    const [config, mappings] = await Promise.all([api("/api/config"), api("/api/v2/path-mappings")]);
    state.config = config;
    state.pathMappings = mappings || { mappings: {} };
  } catch { /* page-specific rendering will expose connection errors */ }
  await pollStatus();
  window.setInterval(pollStatus, 30000);
  history.replaceState({ route: "dashboard", params: {} }, "", "#/dashboard");
  updateActiveNav();
  renderCurrentPage();
}

initialize();
