(function () {
  "use strict";

  var API = "";

  function api(url, opts) {
    opts = opts || {};
    var separator = url.indexOf("?") === -1 ? "?" : "&";
    url = url + separator + "_t=" + Date.now();
    return fetch(API + url, opts).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.message || e.error || "HTTP " + r.status); });
      return r.json();
    });
  }

  function esc(s) {
    if (typeof s !== "string") return "";
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function escA(s) { return esc(s).replace(/\\/g, "\\\\").replace(/'/g, "\\x27"); }
  function F(n) { if (n >= 1e6) return (n / 1e6).toFixed(1) + "M"; if (n >= 1e3) return (n / 1e3).toFixed(1) + "K"; return String(n); }
  function toast(m, t) { t = t || "info"; var d = document.createElement("div"); d.className = "toast " + t; d.textContent = m; document.body.appendChild(d); setTimeout(function () { d.remove(); }, 3000); }

  var LOADING = '<div class="loading"><div class="spinner"></div><p>Loading...</p></div>';

  var _navStack = [];

  // ---- Navigation ----
  function go(page, param) {
    var items = document.querySelectorAll(".nav-list li");
    for (var i = 0; i < items.length; i++) items[i].classList.remove("active");
    var nv = document.querySelector('[data-page="' + page + '"]');
    if (nv) nv.classList.add("active");
    var el = document.getElementById("page-content");
    if (!el) return;

    var isDetail = page === "project" || page === "session" || page === "search";
    var sb = document.getElementById("sidebar-back");
    if (sb) sb.style.display = isDetail ? "block" : "none";

    if (page === "project" || page === "session") {
      _navStack.push({page: page, param: param});
    } else {
      _navStack = [];
    }

    switch (page) {
      case "dashboard": dash(el); break;
      case "projects":  projs(el); break;
      case "project":   proj(el, param); break;
      case "session":   sess(el, param); break;
      case "search":    search(el, param); break;
      case "settings":  setts(el); break;
      default: dash(el);
    }
  }

  function goBack() {
    if (_navStack.length < 2) { go("projects"); return; }
    _navStack.pop();
    var prev = _navStack[_navStack.length - 1];
    if (prev) go(prev.page, prev.param);
    else go("projects");
  }

  // ---- Claude Launcher ----
  function openCC(path, btn, resume, sessionId) {
    resume = resume || false;
    if (btn) { btn.disabled = true; btn.textContent = "Starting..."; }
    var body = { path: path, resume: resume };
    if (sessionId) body.session_id = sessionId;
    api("/api/open-claude", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { toast(r.ok ? "Claude Code started" : r.message, r.ok ? "success" : "error"); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "Open Claude Code"; } });
  }

  // ---- Quick Launch (sidebar) ----
  function initSidebarQL() {
    api("/api/config").then(function (cfg) {
      var perm = document.getElementById("sidebar-ql-perm");
      if (perm) perm.value = cfg.ql_perm || "std";
    });
  }

  function onSidebarQlPath() {}
  function onSidebarQlPerm() {}

  function pickFolder() {
    return api("/api/pick-folder").then(function (r) { return r.path || ""; });
  }

  function quickLaunch() {
    var btn = document.querySelector(".btn-ql-launch");
    if (btn) { btn.disabled = true; btn.textContent = "Starting..."; }

    var sel = document.getElementById("sidebar-ql-path");
    var perm = document.getElementById("sidebar-ql-perm");
    var permVal = perm ? perm.value : "std";

    function doLaunch(path) {
      api("/api/quick-launch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path, permission: permVal })
      }).then(function (r) {
        toast(r.ok ? "Claude Code started (" + path + ")" : r.message, r.ok ? "success" : "error");
      }).catch(function (e) {
        toast(e.message, "error");
      }).finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = "Open Claude Code"; }
      });
    }

    if (sel && sel.value === "custom") {
      pickFolder().then(function (folderPath) {
        if (folderPath) {
          var opt = sel.querySelector('option[value="custom"]');
          if (opt) opt.textContent = folderPath.length > 35 ? "..." + folderPath.slice(-33) : folderPath;
          doLaunch(folderPath);
        } else {
          if (btn) { btn.disabled = false; btn.textContent = "Open Claude Code"; }
        }
      });
    } else {
      api("/api/config").then(function (cfg) {
        doLaunch(cfg.ql_default_path || "~/projects");
      });
    }
  }

  // ---- AI Describe ----
  function descOne(id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "AI generating..."; }
    api("/api/describe-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: id }) })
      .then(function (r) { if (r.ok) { toast("Description updated", "success"); go("project", id); } else toast(r.message || "Failed", "error"); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "AI Generate Description"; } });
  }
  function descAll(btn) {
    if (btn) { btn.disabled = true; btn.textContent = "Batch generating..."; }
    api("/api/describe-all", { method: "POST", headers: { "Content-Type": "application/json" } })
      .then(function (r) { toast(r.message || "Done", r.success ? "success" : "error"); var pg = (document.querySelector(".nav-list li.active") || {}).getAttribute("data-page"); if (pg) go(pg); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "Update All Project Descriptions"; } });
  }

  function sumAll(pid, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "Batch summarizing..."; }
    api("/api/summarize-all", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: pid }) })
      .then(function (r) { toast(r.message || "Done", r.ok ? "success" : "error"); if (r.ok) go("project", pid); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "Batch AI Summarize"; } });
  }

  // ---- Project Card ----
  function pcard(p, descs) {
    descs = descs || {};
    var d = descs[p.id], cwd = p.cwd || "";
    var ai = d && d.description ? '<div class="ai-desc">AI: ' + esc(d.description) + "</div>" : "";
    var obtn = cwd ? '<button class="btn-sm btn-open" onclick="event.stopPropagation();CM.occ(\'' + escA(cwd) + '\',this)">Open Claude Code</button>' : "";
    var dbtn = '<button class="btn-sm btn-del" onclick="event.stopPropagation();CM.del(\'' + escA(p.id) + '\',\'' + escA(p.name) + '\',this)">Delete</button>';
    return '<div class="project-card" onclick="CM.go(\'project\',\'' + escA(p.id) + '\')">' +
      '<div class="project-name">' + esc(p.name) + "</div>" +
      '<div class="project-meta">' + p.session_count + " sessions  " + F(p.total_tokens) + " tokens" + (p.last_active ? "  " + p.last_active.slice(0, 10) : "") + "</div>" +
      ai + (cwd ? '<div class="project-cwd">' + esc(cwd) + "</div>" : "") +
      '<div class="project-actions">' + obtn + dbtn + "</div></div>";
  }

  // ---- Dashboard ----
  function dash(el) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/stats"), api("/api/projects"), api("/api/claude-status"), api("/api/descriptions"), api("/api/config")])
      .then(function (r) {
        var stats = r[0], projs = r[1], cc = r[2], descs = r[3], cfg = r[4], hasK = cfg.api_key_available;
        var h = '<div class="page-header"><h1>Dashboard</h1><p>' +
          '<span class="status-badge ' + (cc.available ? "status-ok" : "status-missing") + '">Claude Code: ' + (cc.available ? "Available" : "Not installed") + "</span>" +
          (hasK ? '<span class="status-badge status-ok" style="margin-left:6px;">API: Configured</span>' : '<span class="status-badge status-missing" style="margin-left:6px;">API: Not configured</span>') +
          "</p></div>" +
          '<div class="stats-grid">' +
          '<div class="stat-card"><div class="stat-value">' + stats.total_projects + '</div><div class="stat-label">Projects</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + stats.total_sessions + '</div><div class="stat-label">Sessions</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + F(stats.total_messages) + '</div><div class="stat-label">Messages</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + F(stats.total_tokens) + '</div><div class="stat-label">Total Tokens</div></div></div>';
        if (hasK) h += '<div style="margin-bottom:16px;"><button class="btn btn-primary" onclick="CM.descAll(this)">Update All Project Descriptions</button></div>';
        h += '<h2 style="margin:24px 0 12px;">Recent Projects</h2><div class="project-list">';
        var lim = Math.min(projs.length, 10);
        for (var i = 0; i < lim; i++) h += pcard(projs[i], descs);
        h += "</div>";
        if (projs.length > 10) h += '<p style="text-align:center;margin-top:12px;"><a href="#" onclick="CM.go(\'projects\');return false;">View all ' + projs.length + " projects</a></p>";
        el.innerHTML = h;
      }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">Load failed: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Projects ----
  function projs(el) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/projects"), api("/api/descriptions"), api("/api/config")])
      .then(function (r) {
        var projs = r[0], descs = r[1], cfg = r[2], hasK = cfg.api_key_available;
        var h = '<div class="page-header"><h1>Projects</h1><p>' + projs.length + " projects  " + (hasK ? "API: configured" : "API: not configured") + "</p></div>";
        if (hasK) h += '<div style="margin-bottom:16px;"><button class="btn btn-primary" onclick="CM.descAll(this)">Update All Project Descriptions</button></div>';
        h += '<div class="project-list">';
        for (var i = 0; i < projs.length; i++) h += pcard(projs[i], descs);
        h += "</div>";
        el.innerHTML = h;
      }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">Load failed: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Project Detail ----
  function proj(el, pid) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/project/" + pid), api("/api/descriptions")]).then(function (r) {
      var p = r[0], descs = r[1], d = descs[pid], cwd = p.cwd || "";
      var ai = d && d.description ? '<div class="ai-description ai-description-lg"><span class="ai-desc-label">AI Description</span> ' + esc(d.description) + "</div>"
        : '<div class="ai-description ai-description-empty">No AI description yet</div>';
      var obtn = cwd ? '<button class="btn-sm btn-open" onclick="CM.occ(\'' + escA(cwd) + '\',this)">Open Claude Code</button>' : "";
      var sh = "";
      for (var i = 0; i < (p.sessions || []).length; i++) {
        var s = p.sessions[i];
        var storedAi = s.ai_summary || "";
        var aiDiv = storedAi
          ? '<div class="session-ai-summary" id="ai-summary-' + escA(s.id) + '">' + esc(storedAi) + "</div>"
          : '<div class="session-ai-summary" id="ai-summary-' + escA(s.id) + '"></div>';
        sh += '<div class="session-item" onclick="CM.go(\'session\',{p:\'' + escA(pid) + '\',s:\'' + escA(s.id) + '\'})">' +
          '<div class="session-title">' + esc(s.title) + "</div>" +
          '<div class="session-meta">' + s.total_msgs + " messages  " + F(s.total_tokens) + " tokens  " + esc(s.model) + (s.created_at ? "  " + s.created_at : "") +
          '  <button class="btn-xs btn-sum" onclick="event.stopPropagation();CM.sumSess(\'' + escA(pid) + '\',\'' + escA(s.id) + '\',this)">AI Summarize</button>' +
          '  <button class="btn-xs btn-del" onclick="event.stopPropagation();CM.delSess(\'' + escA(pid) + '\',\'' + escA(s.id) + '\',\'' + escA(s.title) + '\',this)">Delete</button>' +
          "</div>" +
          '<div class="session-summary">' + esc(s.chinese_summary || "") + "</div>" +
          aiDiv + "</div>";
      }
      var dbtn = '<button class="btn-sm btn-del" onclick="CM.del(\'' + escA(pid) + '\',\'' + escA(p.name) + '\',this)">Delete this project</button>';
      el.innerHTML = '<button class="back-btn" onclick="CM.go(\'projects\')">&larr; Back to projects</button>' +
        '<div class="page-header"><h1>' + esc(p.name) + "</h1><p>" + p.session_count + " sessions  " + F(p.total_tokens) + " tokens  " + F(p.total_msgs) + " messages</p></div>" +
        ai + '<div style="margin:12px 0;display:flex;gap:8px;">' +
        '<button class="btn btn-primary" onclick="CM.descOne(\'' + escA(pid) + '\',this)">AI Generate Description</button>' +
        '<button class="btn btn-primary" onclick="CM.sumAll(\'' + escA(pid) + '\',this)" style="margin-left:8px;">Batch AI Summarize</button>' + (obtn || "") + dbtn + "</div>" +
        (cwd ? '<div class="project-cwd" style="margin-bottom:12px;">Working directory: ' + esc(cwd) + "</div>" : "") +
        '<h2 style="margin:16px 0 12px;">Session History</h2>' + sh;
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">Load failed: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Session View ----
  function _vt(c) {
    if (!c) return false;
    if (typeof c === "string") return c.trim().length > 0;
    if (Array.isArray(c)) {
      for (var i = 0; i < c.length; i++) {
        if (c[i].type === "text" && c[i].text && c[i].text.trim()) return true;
      }
    }
    return false;
  }
  function _isToolResult(c) {
    if (!Array.isArray(c)) return false;
    for (var i = 0; i < c.length; i++) { if (c[i].type === "tool_result") return true; }
    return false;
  }
  function _toolNames(c) {
    if (!Array.isArray(c)) return "";
    var n = [];
    for (var i = 0; i < c.length; i++) { if (c[i].type === "tool_use" && c[i].name) n.push(c[i].name); }
    return n.join(", ");
  }
  function _resultPreview(c, maxLen) {
    maxLen = maxLen || 300;
    if (!Array.isArray(c)) return "";
    var t = [];
    for (var i = 0; i < c.length; i++) {
      if (c[i].type === "tool_result") {
        var rc = c[i].content;
        if (typeof rc === "string") t.push(rc.length > maxLen ? rc.substring(0, maxLen) + "..." : rc);
        else if (Array.isArray(rc)) {
          for (var j = 0; j < rc.length; j++) {
            if (rc[j].type === "text" && rc[j].text) {
              var txt = rc[j].text;
              t.push(txt.length > maxLen ? txt.substring(0, maxLen) + "..." : txt);
            }
          }
        }
      }
    }
    return t.join("\n");
  }
  function md(t) {
    if (!t) return "";
    var h = esc(t);
    h = h.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) { return "<pre><code>" + esc(code) + "</code></pre>"; });
    h = h.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
    return h;
  }
  function sess(el, param) {
    var pid = param.p, sid = param.s;
    if (!pid || !sid) { el.innerHTML = "<p>Invalid session</p>"; return; }
    el.innerHTML = LOADING;
    api("/api/session/" + pid + "/" + sid).then(function (data) {
      var meta = data.metadata, summary = data.chinese_summary || "", cwd = meta.cwd || "", ch = "";
      var msgs = data.conversation || [];
      var i = 0;
      while (i < msgs.length) {
        var msg = msgs[i];
        var role = msg.role === "user" ? "user" : "assistant";

        if (role === "assistant" && !_vt(msg.content)) {
          var mergedInput = 0, mergedOutput = 0, toolCount = 0;
          var detailRows = "";
          var j = i;
          while (j < msgs.length) {
            var mj = msgs[j];
            if (mj.role === "assistant" && !_vt(mj.content)) {
              var u = mj.usage || {};
              mergedInput += u.input_tokens || 0;
              mergedOutput += u.output_tokens || 0;
              toolCount++;
              var names = _toolNames(mj.content);
              detailRows += '<div class="tool-detail-row"><span class="tool-detail-label">Tool call</span> ' + esc(names || "(unnamed)") +
                ' <span class="tool-tokens">in ' + F(u.input_tokens || 0) + ' / out ' + F(u.output_tokens || 0) + '</span></div>';
              j++;
              if (j < msgs.length && msgs[j].role === "user" && _isToolResult(msgs[j].content)) {
                var preview = _resultPreview(msgs[j].content);
                if (preview) detailRows += '<div class="tool-detail-row tool-result"><span class="tool-detail-label">Result</span> <pre class="tool-result-pre">' + esc(preview) + '</pre></div>';
                j++;
              }
            } else if (mj.role === "user" && _isToolResult(mj.content)) {
              var preview2 = _resultPreview(mj.content);
              if (preview2) detailRows += '<div class="tool-detail-row tool-result"><span class="tool-detail-label">Result</span> <pre class="tool-result-pre">' + esc(preview2) + '</pre></div>';
              j++;
            } else {
              break;
            }
          }
          var gid = "tg" + (Math.random() + "").slice(2, 10);
          ch += '<div class="message tool-group">' +
            '<input type="checkbox" id="' + gid + '" class="tool-toggle-check">' +
            '<div class="message-header"><label class="tool-toggle" for="' + gid + '">Agent working - ' + toolCount + ' tool calls | in ' + F(mergedInput) + ' | out ' + F(mergedOutput) + ' tokens  <span class="tool-toggle-arrow">&#9660;</span></label></div>' +
            '<div class="tool-detail">' + detailRows + '</div></div>';
          i = j;
        } else {
          var ct = "";
          if (Array.isArray(msg.content)) {
            for (var k = 0; k < msg.content.length; k++) {
              var b = msg.content[k];
              if (b.type === "text" && b.text) ct += md(b.text);
            }
          } else if (typeof msg.content === "string") ct = md(msg.content);

          ch += '<div class="message ' + role + '"><div class="message-header">' +
            (role === "user" ? "User" : "Claude") + " " +
            (msg.model ? '<span class="tag tag-model">' + esc(msg.model) + "</span>" : "") +
            ((msg.usage && (msg.usage.input_tokens || msg.usage.output_tokens)) ?
              '<span class="usage-badge">in:' + (msg.usage.input_tokens || 0) + " out:" + (msg.usage.output_tokens || 0) + "</span>" : "") +
            "</div><div class=\"message-content\">" + ct + "</div></div>";
          i++;
        }
      }
      var aiSum = data.ai_summary || "";
      var openBtn = cwd ? '<div style="margin-top:8px;"><button class="btn-ai-summary" onclick="CM.occ(\'' + escA(cwd) + '\',this,true,\'' + escA(sid) + '\')">Open Claude Code</button></div>' : "";
      var autoBox = '<div class="summary-box" style="background:#f5f5f5;color:#555;"><div class="summary-label">Session Overview</div>' + esc(summary) + openBtn + "</div>";
      var aiBox = aiSum
        ? '<div class="summary-box"><div class="summary-label">AI Detailed Summary</div>' + esc(aiSum) + "</div>"
        : "";

      el.innerHTML = '<button class="back-btn" onclick="CM.go(\'project\',\'' + escA(pid) + '\')">&larr; Back to project</button>' +
        '<div class="page-header"><h1>' + esc(meta.title) + "</h1><p>" + meta.total_msgs + " messages  " + F(meta.total_tokens) + " tokens  " + esc(meta.model) +
        (meta.created_at ? "  " + meta.created_at : "") + (meta.git_branch ? "  " + esc(meta.git_branch) : "") + "</p></div>" +
        autoBox + aiBox +
        '<div class="conversation">' + ch + "</div>";
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">Load failed: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Settings ----
  function setts(el) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/config"), api("/api/claude-status")]).then(function (r) {
      var cfg = r[0], cc = r[1], models = cfg.summary_models || {}, cur = cfg.api_model || "";
      var mopts = "";
      for (var k in models) { if (models.hasOwnProperty(k)) mopts += '<option value="' + escA(k) + '"' + (k === cur ? " selected" : "") + ">" + esc(models[k]) + "</option>"; }
      var provOpts = '<option value="deepseek"' + (cfg.provider === "deepseek" ? " selected" : "") + ">DeepSeek (OpenAI-compatible)</option>" +
        '<option value="anthropic"' + (cfg.provider === "anthropic" ? " selected" : "") + ">Anthropic</option>";

      el.innerHTML =
        '<div class="page-header"><h1>Settings</h1></div>' +
        '<div class="settings-section"><h3>Claude Code</h3><p>' + (cc.available ? "Installed: " + esc(cc.path) : "Claude command not found") + "</p></div>" +
        '<div class="settings-section"><h3>AI API Configuration</h3>' +
        '<p style="font-size:13px;color:#888;margin-bottom:8px;">Configure DeepSeek or Anthropic API key, endpoint, and model.</p>' +
        '<label>Provider</label><select id="cfg-provider" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' + provOpts + "</select>" +
        '<label>API Endpoint</label><input id="cfg-endpoint" value="' + escA(cfg.api_endpoint || "") + '" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' +
        '<label>API Key</label><input type="password" id="cfg-key" placeholder="sk-..." style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' +
        '<label>Model</label><select id="cfg-model" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' + mopts + "</select>" +
        '<button class="btn btn-primary" onclick="CM.saveCfg()">Save Configuration</button>' +
        '<span id="cfg-status" style="margin-left:10px;font-size:13px;">' + (cfg.api_key_available ? "API configured" : "API not configured") + "</span>" +
        "</div>" +
        '<div class="settings-section"><h3>API Configuration File</h3>' +
        '<p style="font-size:13px;color:#888;">Configuration file at <code>data/api-config.json</code>. Edit manually and restart:</p>' +
        '<pre style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:8px;font-size:12px;overflow-x:auto;">{\n  "provider": "deepseek",\n  "api_key": "sk-your-key-here",\n  "api_endpoint": "https://api.deepseek.com/v1/chat/completions",\n  "api_model": "deepseek-v4-flash"\n}</pre>' +
        '<p style="font-size:12px;color:#888;margin-top:4px;">provider: <code>deepseek</code> / <code>anthropic</code></p></div>' +
        '<div class="settings-section"><h3>settings.json</h3>' +
        '<pre style="background:#f5f5f5;padding:12px;border-radius:8px;font-size:13px;overflow-x:auto;">' + esc(JSON.stringify(cfg.settings || {}, null, 2)) + "</pre></div>";
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">Load failed: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Public API ----
  function delSession(pid, sid, title, btn) {
    var msg = "Delete session\n\n" + title + "\n\n? This cannot be undone.";
    if (!confirm(msg)) return;
    if (btn) { btn.disabled = true; btn.textContent = "Deleting..."; }
    api("/api/delete-session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: pid, session_id: sid }) })
      .then(function (r) {
        if (r.ok) { toast("Session deleted", "success"); go("project", pid); }
        else toast(r.message || "Delete failed", "error");
      }).catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "Delete"; } });
  }

  function summarizeSession(pid, sid, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "AI generating..."; }
    api("/api/summarize?project=" + encodeURIComponent(pid) + "&session=" + encodeURIComponent(sid))
      .then(function (r) {
        if (r.summary) {
          var el = document.getElementById("ai-summary-" + sid);
          if (el) el.innerHTML = esc(r.summary);
          toast("Session summary generated", "success");
        } else {
          toast(r.error || r.message || "Generation failed", "error");
        }
      }).catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "AI Summarize"; } });
  }

  function delProject(id, name, btn) {
    var msg = "Delete project\n\n" + name + "\n\nand all its sessions? This cannot be undone.";
    if (!confirm(msg)) return;
    if (btn) { btn.disabled = true; btn.textContent = "Deleting..."; }
    api("/api/delete-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: id }) })
      .then(function (r) {
        if (r.ok) { toast("Deleted", "success"); go("projects"); }
        else toast(r.message || "Delete failed", "error");
      }).catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "Delete"; } });
  }

  // ---- Search ----
  function search(el, q) {
    q = (q || "").trim();
    if (!q) { el.innerHTML = '<div class="empty-state"><p>Enter keywords in the sidebar to search AI summaries.</p></div>'; return; }
    el.innerHTML = '<div class="page-header"><h1>Search: ' + esc(q) + '</h1></div><div class="loading"><div class="spinner"></div><p>Searching...</p></div>';
    api("/api/search?q=" + encodeURIComponent(q)).then(function (r) {
      var rs = r.results || [];
      if (rs.length === 0) {
        el.innerHTML = '<div class="page-header"><h1>Search: ' + esc(q) + '</h1></div><div class="empty-state"><p>No results found.</p></div>';
        return;
      }
      var h = '<div class="page-header"><h1>Search: ' + esc(q) + '</h1><p>' + rs.length + ' results</p></div>';
      for (var i = 0; i < rs.length; i++) {
        var r2 = rs[i];
        if (r2.type === "project") {
          h += '<div class="session-item" onclick="CM.go(\'project\',\'' + escA(r2.id) + '\')">' +
            '<span class="tag tag-project">Project</span> ' + esc(r2.name) + '<br><small>' + esc(r2.matched_text || "") + '</small></div>';
        } else {
          h += '<div class="session-item" onclick="CM.go(\'session\',{p:\'' + escA(r2.project_id) + '\',s:\'' + escA(r2.session_id) + '\'})">' +
            '<span class="tag tag-session">Session</span> ' + esc(r2.title) + '<br><small>' + esc(r2.matched_text || "") + '</small></div>';
        }
      }
      el.innerHTML = h;
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">Search failed: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Public API surface ----
  window.CM = {
    go: go,
    goBack: goBack,
    occ: openCC,
    quickLaunch: quickLaunch,
    onSidebarQlPath: onSidebarQlPath,
    onSidebarQlPerm: onSidebarQlPerm,
    descOne: descOne,
    descAll: descAll,
    del: delProject,
    delSess: delSession,
    sumAll: sumAll,
    sumSess: summarizeSession,
    saveCfg: function () {
      var provider = document.getElementById("cfg-provider").value;
      var endpoint = document.getElementById("cfg-endpoint").value;
      var key = document.getElementById("cfg-key").value;
      var model = document.getElementById("cfg-model").value;
      var body = { provider: provider, api_endpoint: endpoint, api_key: key, api_model: model };
      api("/api/set-api-config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (r) { toast(r.ok ? "Configuration saved" : (r.message || "Save failed"), r.ok ? "success" : "error"); if (r.ok) { document.getElementById("cfg-status").textContent = "API configured"; } })
        .catch(function (e) { toast(e.message, "error"); });
    }
  };

  // ---- Boot ----
  initSidebarQL();
  go("dashboard");
})();
