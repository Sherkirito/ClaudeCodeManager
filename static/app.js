(function () {
  "use strict";

  var API = "";

  function api(url, opts) {
    opts = opts || {};
    return fetch(API + url, opts).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.message || e.error || "HTTP " + r.status); });
      return r.json();
    });
  }

  function esc(s) {
    if (typeof s !== "string") return "";
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function escA(s) { return esc(s).replace(/\\/g, "\\\\").replace(/'/g, "&#39;"); }
  function F(n) { if (n >= 1e6) return (n / 1e6).toFixed(1) + "M"; if (n >= 1e3) return (n / 1e3).toFixed(1) + "K"; return String(n); }
  function toast(m, t) { t = t || "info"; var d = document.createElement("div"); d.className = "toast " + t; d.textContent = m; document.body.appendChild(d); setTimeout(function () { d.remove(); }, 3000); }

  var LOADING = '<div class="loading"><div class="spinner"></div><p>加载中...</p></div>';

  // ---- Navigation ----
  function go(page, param) {
    var items = document.querySelectorAll(".nav-list li");
    for (var i = 0; i < items.length; i++) items[i].classList.remove("active");
    var nv = document.querySelector('[data-page="' + page + '"]');
    if (nv) nv.classList.add("active");
    var el = document.getElementById("page-content");
    if (!el) return;
    switch (page) {
      case "dashboard": dash(el); break;
      case "projects":  projs(el); break;
      case "project":   proj(el, param); break;
      case "session":   sess(el, param); break;
      case "settings":  setts(el); break;
      default: dash(el);
    }
  }

  // ---- Claude Launcher ----
  function openCC(path, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "启动中..."; }
    api("/api/open-claude", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: path }) })
      .then(function (r) { toast(r.ok ? "Claude Code 已启动" : r.message, r.ok ? "success" : "error"); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "打开 Claude Code"; } });
  }

  // ---- AI Describe ----
  function descOne(id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "AI 生成中..."; }
    api("/api/describe-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: id }) })
      .then(function (r) { if (r.ok) { toast("简介已更新", "success"); go("project", id); } else toast(r.message || "失败", "error"); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "AI 生成简介"; } });
  }
  function descAll(btn) {
    if (btn) { btn.disabled = true; btn.textContent = "批量生成中..."; }
    api("/api/describe-all", { method: "POST", headers: { "Content-Type": "application/json" } })
      .then(function (r) { toast(r.message || "完成", r.success ? "success" : "error"); var pg = (document.querySelector(".nav-list li.active") || {}).getAttribute("data-page"); if (pg) go(pg); })
      .catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "更新全部项目简介"; } });
  }

  // ---- Project Card ----
  function pcard(p, descs) {
    descs = descs || {};
    var d = descs[p.id], cwd = p.cwd || "";
    var ai = d && d.description ? '<div class="ai-desc">AI: ' + esc(d.description) + "</div>" : "";
    var obtn = cwd ? '<button class="btn-sm btn-open" onclick="event.stopPropagation();CM.occ(\'' + escA(cwd) + '\',this)">打开 Claude Code</button>' : "";
    var dbtn = '<button class="btn-sm btn-del" onclick="event.stopPropagation();CM.del(\'' + escA(p.id) + '\',\'' + escA(p.name) + '\',this)">删除</button>';
    return '<div class="project-card" onclick="CM.go(\'project\',\'' + escA(p.id) + '\')">' +
      '<div class="project-name">' + esc(p.name) + "</div>" +
      '<div class="project-meta">' + p.session_count + " 个会话  " + F(p.total_tokens) + " tokens" + (p.last_active ? "  " + p.last_active.slice(0, 10) : "") + "</div>" +
      ai + (cwd ? '<div class="project-cwd">' + esc(cwd) + "</div>" : "") +
      '<div class="project-actions">' + obtn + dbtn + "</div></div>";
  }

  // ---- Dashboard ----
  function dash(el) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/stats"), api("/api/projects"), api("/api/claude-status"), api("/api/descriptions"), api("/api/config")])
      .then(function (r) {
        var stats = r[0], projs = r[1], cc = r[2], descs = r[3], cfg = r[4], hasK = cfg.api_key_available;
        var h = '<div class="page-header"><h1>总览</h1><p>' +
          '<span class="status-badge ' + (cc.available ? "status-ok" : "status-missing") + '">Claude Code: ' + (cc.available ? "可用" : "未安装") + "</span>" +
          (hasK ? '<span class="status-badge status-ok" style="margin-left:6px;">API: 已配置</span>' : '<span class="status-badge status-missing" style="margin-left:6px;">API: 未配置</span>') +
          "</p></div>" +
          '<div class="stats-grid">' +
          '<div class="stat-card"><div class="stat-value">' + stats.total_projects + '</div><div class="stat-label">项目数</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + stats.total_sessions + '</div><div class="stat-label">会话数</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + F(stats.total_messages) + '</div><div class="stat-label">消息总数</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + F(stats.total_tokens) + '</div><div class="stat-label">Token 总量</div></div></div>';
        if (hasK) h += '<div style="margin-bottom:16px;"><button class="btn btn-primary" onclick="CM.descAll(this)">更新全部项目简介</button></div>';
        h += '<h2 style="margin:24px 0 12px;">最近项目</h2><div class="project-list">';
        var lim = Math.min(projs.length, 10);
        for (var i = 0; i < lim; i++) h += pcard(projs[i], descs);
        h += "</div>";
        if (projs.length > 10) h += '<p style="text-align:center;margin-top:12px;"><a href="#" onclick="CM.go(\'projects\');return false;">查看全部 ' + projs.length + " 个项目</a></p>";
        el.innerHTML = h;
      }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">加载失败: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Projects ----
  function projs(el) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/projects"), api("/api/descriptions"), api("/api/config")])
      .then(function (r) {
        var projs = r[0], descs = r[1], cfg = r[2], hasK = cfg.api_key_available;
        var h = '<div class="page-header"><h1>项目列表</h1><p>共 ' + projs.length + " 个项目  " + (hasK ? "API: 已配置" : "API: 未配置") + "</p></div>";
        if (hasK) h += '<div style="margin-bottom:16px;"><button class="btn btn-primary" onclick="CM.descAll(this)">更新全部项目简介</button></div>';
        h += '<div class="project-list">';
        for (var i = 0; i < projs.length; i++) h += pcard(projs[i], descs);
        h += "</div>";
        el.innerHTML = h;
      }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">加载失败: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Project Detail ----
  function proj(el, pid) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/project/" + pid), api("/api/descriptions")]).then(function (r) {
      var p = r[0], descs = r[1], d = descs[pid], cwd = p.cwd || "";
      var ai = d && d.description ? '<div class="ai-description ai-description-lg"><span class="ai-desc-label">AI 简介</span> ' + esc(d.description) + "</div>"
        : '<div class="ai-description ai-description-empty">暂无 AI 简介</div>';
      var obtn = cwd ? '<button class="btn-sm btn-open" onclick="CM.occ(\'' + escA(cwd) + '\',this)">打开 Claude Code</button>' : "";
      var sh = "";
      for (var i = 0; i < (p.sessions || []).length; i++) {
        var s = p.sessions[i];
        var storedAi = s.ai_summary || "";
        var aiDiv = storedAi
          ? '<div class="session-ai-summary" id="ai-summary-' + escA(s.id) + '">' + esc(storedAi) + "</div>"
          : '<div class="session-ai-summary" id="ai-summary-' + escA(s.id) + '"></div>';
        sh += '<div class="session-item" onclick="CM.go(\'session\',{p:\'' + escA(pid) + '\',s:\'' + escA(s.id) + '\'})">' +
          '<div class="session-title">' + esc(s.title) + "</div>" +
          '<div class="session-meta">' + s.total_msgs + " 条消息  " + F(s.total_tokens) + " tokens  " + esc(s.model) + (s.created_at ? "  " + s.created_at : "") +
          '  <button class="btn-xs btn-sum" onclick="event.stopPropagation();CM.sumSess(\'' + escA(pid) + '\',\'' + escA(s.id) + '\',this)">AI 总结</button>' +
          '  <button class="btn-xs btn-del" onclick="event.stopPropagation();CM.delSess(\'' + escA(pid) + '\',\'' + escA(s.id) + '\',\'' + escA(s.title) + '\',this)">删除</button>' +
          "</div>" +
          '<div class="session-summary">' + esc(s.chinese_summary || "") + "</div>" +
          aiDiv + "</div>";
      }
      var dbtn = '<button class="btn-sm btn-del" onclick="CM.del(\'' + escA(pid) + '\',\'' + escA(p.name) + '\',this)">删除此项目</button>';
      el.innerHTML = '<button class="back-btn" onclick="CM.go(\'projects\')">← 返回项目列表</button>' +
        '<div class="page-header"><h1>' + esc(p.name) + "</h1><p>" + p.session_count + " 个会话  " + F(p.total_tokens) + " tokens  " + F(p.total_msgs) + " 条消息</p></div>" +
        ai + '<div style="margin:12px 0;display:flex;gap:8px;">' +
        '<button class="btn btn-primary" onclick="CM.descOne(\'' + escA(pid) + '\',this)">AI 生成简介</button>' + (obtn || "") + dbtn + "</div>" +
        (cwd ? '<div class="project-cwd" style="margin-bottom:12px;">工作目录: ' + esc(cwd) + "</div>" : "") +
        '<h2 style="margin:16px 0 12px;">会话记录</h2>' + sh;
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">加载失败: ' + esc(String(e.message || e)) + "</p></div>"; });
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
        if (typeof rc === "string") t.push(rc.length > maxLen ? rc.substring(0, maxLen) + "…" : rc);
        else if (Array.isArray(rc)) {
          for (var j = 0; j < rc.length; j++) {
            if (rc[j].type === "text" && rc[j].text) {
              var txt = rc[j].text;
              t.push(txt.length > maxLen ? txt.substring(0, maxLen) + "…" : txt);
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
    if (!pid || !sid) { el.innerHTML = "<p>无效会话</p>"; return; }
    el.innerHTML = LOADING;
    api("/api/session/" + pid + "/" + sid).then(function (data) {
      var meta = data.metadata, summary = data.chinese_summary || "", cwd = meta.cwd || "", ch = "";
      var msgs = data.conversation || [];
      var i = 0;
      while (i < msgs.length) {
        var msg = msgs[i];
        var role = msg.role === "user" ? "user" : "assistant";

        if (role === "assistant" && !_vt(msg.content)) {
          // Merge tool-only assistant + tool_result user pairs into one collapsible group
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
              detailRows += '<div class="tool-detail-row"><span class="tool-detail-label">工具调用</span> ' + esc(names || "(无名称)") +
                ' <span class="tool-tokens">入 ' + F(u.input_tokens || 0) + ' / 出 ' + F(u.output_tokens || 0) + '</span></div>';
              j++;
              // Consume following tool_result user message
              if (j < msgs.length && msgs[j].role === "user" && _isToolResult(msgs[j].content)) {
                var preview = _resultPreview(msgs[j].content);
                if (preview) detailRows += '<div class="tool-detail-row tool-result"><span class="tool-detail-label">结果</span> <pre class="tool-result-pre">' + esc(preview) + '</pre></div>';
                j++;
              }
            } else if (mj.role === "user" && _isToolResult(mj.content)) {
              // stray tool_result without preceding assistant — just include it
              var preview2 = _resultPreview(mj.content);
              if (preview2) detailRows += '<div class="tool-detail-row tool-result"><span class="tool-detail-label">结果</span> <pre class="tool-result-pre">' + esc(preview2) + '</pre></div>';
              j++;
            } else {
              break;
            }
          }
          var gid = "tg" + (Math.random() + "").slice(2, 10);
          ch += '<div class="message tool-group">' +
            '<input type="checkbox" id="' + gid + '" class="tool-toggle-check">' +
            '<div class="message-header"><label class="tool-toggle" for="' + gid + '">Agent 工作中 — ' + toolCount + ' 次工具调用 · 输入 ' + F(mergedInput) + ' · 输出 ' + F(mergedOutput) + ' tokens  <span class="tool-toggle-arrow">▼</span></label></div>' +
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
            (role === "user" ? "用户" : "Claude") + " " +
            (msg.model ? '<span class="tag tag-model">' + esc(msg.model) + "</span>" : "") +
            ((msg.usage && (msg.usage.input_tokens || msg.usage.output_tokens)) ?
              '<span class="usage-badge">输入:' + (msg.usage.input_tokens || 0) + " 输出:" + (msg.usage.output_tokens || 0) + "</span>" : "") +
            "</div><div class=\"message-content\">" + ct + "</div></div>";
          i++;
        }
      }
      var aiSum = data.ai_summary || "";
      var autoBox = '<div class="summary-box" style="background:#f5f5f5;color:#555;"><div class="summary-label">会话概览</div>' + esc(summary) + "</div>";
      var aiBox = aiSum
        ? '<div class="summary-box"><div class="summary-label">AI 详细总结</div>' + esc(aiSum) +
          (cwd ? '<div style="margin-top:8px;"><button class="btn-ai-summary" onclick="CM.occ(\'' + escA(cwd) + '\',this)">打开 Claude Code</button></div>' : "") + "</div>"
        : "";

      el.innerHTML = '<button class="back-btn" onclick="CM.go(\'project\',\'' + escA(pid) + '\')">← 返回项目</button>' +
        '<div class="page-header"><h1>' + esc(meta.title) + "</h1><p>" + meta.total_msgs + " 条消息  " + F(meta.total_tokens) + " tokens  " + esc(meta.model) +
        (meta.created_at ? "  " + meta.created_at : "") + (meta.git_branch ? "  " + esc(meta.git_branch) : "") + "</p></div>" +
        autoBox + aiBox +
        '<div class="conversation">' + ch + "</div>";
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">加载失败: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Settings ----
  function setts(el) {
    el.innerHTML = LOADING;
    Promise.all([api("/api/config"), api("/api/claude-status")]).then(function (r) {
      var cfg = r[0], cc = r[1], models = cfg.summary_models || {}, cur = cfg.api_model || "";
      var mopts = "";
      for (var k in models) { if (models.hasOwnProperty(k)) mopts += '<option value="' + escA(k) + '"' + (k === cur ? " selected" : "") + ">" + esc(models[k]) + "</option>"; }
      var provOpts = '<option value="deepseek"' + (cfg.provider === "deepseek" ? " selected" : "") + ">DeepSeek (OpenAI 兼容)</option>" +
        '<option value="anthropic"' + (cfg.provider === "anthropic" ? " selected" : "") + ">Anthropic</option>";

      el.innerHTML =
        '<div class="page-header"><h1>设置</h1></div>' +
        '<div class="settings-section"><h3>Claude Code</h3><p>' + (cc.available ? "已安装: " + esc(cc.path) : "未找到 claude 命令") + "</p></div>" +
        '<div class="settings-section"><h3>AI 接口配置</h3>' +
        '<p style="font-size:13px;color:#888;margin-bottom:8px;">配置 DeepSeek 或 Anthropic 的 API 密钥、端点和模型。</p>' +
        '<label>接口类型</label><select id="cfg-provider" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' + provOpts + "</select>" +
        '<label>API 端点</label><input id="cfg-endpoint" value="' + escA(cfg.api_endpoint || "") + '" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' +
        '<label>API 密钥</label><input type="password" id="cfg-key" placeholder="sk-..." style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' +
        '<label>模型</label><select id="cfg-model" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;margin-bottom:8px;">' + mopts + "</select>" +
        '<button class="btn btn-primary" onclick="CM.saveCfg()">保存配置</button>' +
        '<span id="cfg-status" style="margin-left:10px;font-size:13px;">' + (cfg.api_key_available ? "API 已配置" : "API 未配置") + "</span>" +
        "</div>" +
        '<div class="settings-section"><h3>API 配置文件</h3>' +
        '<p style="font-size:13px;color:#888;">配置文件位于 <code>data/api-config.json</code>，格式如下。可手动编辑后重启生效：</p>' +
        '<pre style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:8px;font-size:12px;overflow-x:auto;">{\n  "provider": "deepseek",\n  "api_key": "sk-your-key-here",\n  "api_endpoint": "https://api.deepseek.com/v1/chat/completions",\n  "api_model": "deepseek-chat"\n}</pre>' +
        '<p style="font-size:12px;color:#888;margin-top:4px;">provider 可选: <code>deepseek</code> / <code>anthropic</code><br>切换 provider 后模型列表会自动更新。</p></div>' +
        '<div class="settings-section"><h3>settings.json</h3>' +
        '<pre style="background:#f5f5f5;padding:12px;border-radius:8px;font-size:13px;overflow-x:auto;">' + esc(JSON.stringify(cfg.settings || {}, null, 2)) + "</pre></div>";
    }).catch(function (e) { el.innerHTML = '<div class="empty-state"><p style="color:red;">加载失败: ' + esc(String(e.message || e)) + "</p></div>"; });
  }

  // ---- Public API ----
  function delSession(pid, sid, title, btn) {
    var msg = "确定要删除会话\n\n" + title + "\n\n吗？此操作不可恢复。";
    if (!confirm(msg)) return;
    if (btn) { btn.disabled = true; btn.textContent = "删除中..."; }
    api("/api/delete-session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: pid, session_id: sid }) })
      .then(function (r) {
        if (r.ok) { toast("会话已删除", "success"); go("project", pid); }
        else toast(r.message || "删除失败", "error");
      }).catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "删除"; } });
  }

  function summarizeSession(pid, sid, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "AI 生成中..."; }
    api("/api/summarize?project=" + encodeURIComponent(pid) + "&session=" + encodeURIComponent(sid))
      .then(function (r) {
        if (r.summary) {
          var el = document.getElementById("ai-summary-" + sid);
          if (el) el.innerHTML = esc(r.summary);
          toast("会话总结已生成", "success");
        } else {
          toast(r.error || r.message || "生成失败", "error");
        }
      }).catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "AI 总结"; } });
  }

  function delProject(id, name, btn) {
    var msg = "确定要删除项目\n\n" + name + "\n\n及其所有 " + "会话记录吗？此操作不可恢复。";
    if (!confirm(msg)) return;
    if (btn) { btn.disabled = true; btn.textContent = "删除中..."; }
    api("/api/delete-project", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: id }) })
      .then(function (r) {
        if (r.ok) { toast("已删除", "success"); go("projects"); }
        else toast(r.message || "删除失败", "error");
      }).catch(function (e) { toast(e.message, "error"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = "删除"; } });
  }

  window.CM = {
    go: go, occ: openCC, descOne: descOne, descAll: descAll, del: delProject, delSess: delSession, sumSess: summarizeSession,
    saveCfg: function () {
      var p = document.getElementById("cfg-provider").value;
      var ep = document.getElementById("cfg-endpoint").value.trim();
      var key = document.getElementById("cfg-key").value.trim();
      var model = document.getElementById("cfg-model").value;
      var body = {};
      if (p) body.provider = p;
      if (ep) body.api_endpoint = ep;
      if (key) body.api_key = key;
      if (model) body.api_model = model;
      api("/api/set-api-config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (r) {
          if (r.ok) { document.getElementById("cfg-status").textContent = "配置已保存"; toast("配置已保存", "success"); }
          else toast(r.message || "失败", "error");
        }).catch(function (e) { toast(e.message, "error"); });
    },
  };

  // ---- Sidebar ----
  document.addEventListener("DOMContentLoaded", function () {
    var items = document.querySelectorAll(".nav-list li[data-page]");
    for (var i = 0; i < items.length; i++) {
      items[i].addEventListener("click", function () {
        var pg = this.getAttribute("data-page");
        if (pg) go(pg);
      });
    }
    go("dashboard");
  });
})();
