# Claude Code 管理器 v2.1.0 重设计（冻结稿）

状态：已获用户批准（2026-08-13）。实施与评审以本文档为唯一契约。
若与代码现状冲突，以本文档为准，由 lead 裁决；本文档中引用的旧字段/端点名以代码现状为准。

## 0.0 已裁定扩展（2026-08-13，lead 裁定，与正文同效力）

- E1：§4.1 items 增加 `descendant_count`（int）——不变式 #7（级联确认）要求前端每行可读该值；加法扩展，不违反不变式 #3。
- E2：orphan 移除端点定名 `POST /api/v2/orphan-history-sessions/remove`，body `{"session_id": ...}`，响应 `{"ok": true, "removed": <int>, "message": "记录已移除"}`（对应 §4.4"移除记录"）。
- E3：items 保留 `ai_summary` 字段（沿用 attach_session_summaries 既有行为；工作台最近/详情摘要依赖）。
- E4：trash-session 响应的 `message` 在级联时改为"会话及 N 个下属会话已移到回收站"（§4.5 落地细节）。
- E5（过渡期残留，阶段 4 清除）：不变式 #3 本发布内严格适用于 list_sessions 与 session_detail 响应；search/team_detail/dashboard 的存量会话形状仍含 record_project_id 等旧字段（前端不再展示，仅内部回退使用），阶段 4 一并清除。

## 0. 核心需求（用户确认，优先级最高）

- **C1 找到所有会话**：所有被索引的会话必须能在"会话"页被找到——不论类型、项目、团队、是否嵌套。任何会话都不允许"只在某个面板里"。
- **C2 围绕主会话管理**：主会话是管理锚点。非主会话的每一行都带"所属主会话"链接；回收任何存在下属的会话时默认级联其全部下属会话。
- **C3 不放弃失联会话**：history 出现过但转录找不到的记录永不被自动清除；转录一旦被索引找回即自动归位；仅用户显式"移除记录"才消失。
- **C4 简单逻辑感**：执行 P1–P5 五原则，回归"一棵树 + 一个花名册"。

## 1. 设计原则

| 原则 | 内容 |
|---|---|
| P1 一物一概念 | 任何概念只回答一个问题、只占一个字段；禁止 session_kind 与 task_kind 这种叠床架屋 |
| P2 树 + 花名册 | 管理器结构不超纲：Claude Code 本体是"嵌套树 + teams 花名册"，我们只做它的忠实索引 |
| P3 查询皆视图 | 筛选、统计、搜索都是同一张会话表上的视图，不建任何平行体系 |
| P4 物理细节内部化 | record 目录名、绝对路径只存在于 IO 层，永不出现在 API 响应和 UI 状态里 |
| P5 一页一问、一行一画 | 每个页面只回答一个问题；任何页面上的会话行只有一种渲染路径 |

## 2. 本体地图（Claude Code 真实结构）

| 数据本体 | 位置 | 本质 |
|---|---|---|
| 会话转录 | `projects/<编码cwd>/<uuid>.jsonl` | 一个会话 = 一个文件，唯一原子单位 |
| 子代理转录 | `<父会话uuid>/subagents/agent-*.jsonl`（+ `.meta.json`） | 被 spawn 的会话，物理嵌套在父会话目录下 |
| 后台任务登记 | `jobs/<short8>/state.json` | 只回答"这个顶层会话是不是后台 Job" |
| 团队配置 | `teams/session-<8hex>/config.json`（+ inboxes） | 只回答"谁和谁是队友、谁是 lead" |
| 命令历史 | `history.jsonl` | 只回答"哪些 sessionId 出现过" |
| 进程登记 | `sessions/<pid>.json` | 运行时 pid↔session 映射 |

一句话：Claude Code 本体 = **嵌套树**（会话 → 其 spawn 的子会话）+ **花名册**（teams config 圈出团队）+ 三个标签（jobs registry / entrypoint / history）。

## 3. 数据模型（schema v6）

### 3.1 kind 判定树（唯一来源，顺序即优先级）

```
转录文件位置
├─ projects/<record>/<uuid>.jsonl（顶层）
│   ├─ jobs/state.json 登记该 uuid        → kind=job
│   ├─ 首条 user 记录 entrypoint=sdk-cli  → kind=sdk
│   └─ 其余                               → kind=primary
└─ projects/<record>/<lead>/subagents/<name>.jsonl（嵌套）
    ├─ 同目录 .meta.json：taskKind=="in_process_teammate" 且 teamName 非空
    │                                     → kind=teammate, link_source=meta
    ├─ meta 不符，但 teams config 成员表对 agentId/文件名前缀唯一命中
    │                                     → kind=teammate, link_source=config
    └─ 其余                               → kind=subagent
```

附带规则：

- teammate 的 team_id：meta.teamName 或 config 成员归属，唯一性检查；团队 config 已删除 → team_id=NULL，UI 显示"团队已解散"。
- lead 会话不改 kind；lead 关系只落在 teams/team_members（role='lead'）+ sessions.team_id 链接。
- parent_session_id：嵌套文件 → 所在 `<lead-uuid>`（link_source=exact）；顶层推断沿用现状（link_source=inferred）。
- kind 回填：SCHEMA_VERSION 5→6 触发全量重扫，kind 由判定树在扫描时直接写出（无手工 UPDATE）；task_kind=='in_process_teammate' 的旧数据自然收敛为 teammate。

### 3.2 sessions 列变更

| 操作 | 列 | 说明 |
|---|---|---|
| 新增 | `kind` | 5 值：primary/job/sdk/subagent/teammate；判定树唯一来源 |
| 新增 | `meta_json` | 折叠 agent 元数据 JSON（agent_type/name/description/color 等）。**不得包含成员 cwd 或任何路径** |
| 新增 | `link_source` | exact/inferred/meta/config/name_only（parent 链接仅 exact/inferred；team 链接仅 meta/config/name_only） |
| 新增 | `jsonl_rel_path` | 相对 DATA_DIR 的转录路径，仅供 IO 层（回收/详情按需读取）；**API 永不外泄** |
| 过渡保留 | session_kind / task_kind / team_confidence / relation_confidence / agent_* | 本发布继续回填保证兼容；阶段 4 删除 |
| 删除 | 无（本发布全为增量） | |

### 3.3 teams / team_members

- team_members 新增 `role`（lead/member）；`match_confidence` 不再新写（沿用列名，值域改 link_source）。
- teams.cwd 维持 ''；展示时从 lead 会话派生（现状保留）。
- 团队聚合统计改由 facet 助手派生，不另存计数。

### 3.4 统计：facet 助手

`_facet_kinds(conn, where, params) -> {primary, job, sdk, subagent, teammate}`。
工作台、项目卡、团队页、浏览器 chips 计数全部派生于此。任何响应不再携带手工拼装的计数字段（§4.2 兼容别名除外）。

## 4. API 契约

### 4.1 GET /api/v2/sessions（规范入口）

参数：

- `kind`：all(默认) | primary | job | sdk | subagent | teammate | automatic（预设 = job+sdk+subagent+teammate）
- `scope`：缺省=全部 | `project:<logical_id>` | `team:<team_id>` | `parent:<session_id>`
- `q` / `limit` / `offset` 不变

响应：

```
{ items: [...], total, by_kind: {primary, job, sdk, subagent, teammate}, limit, offset }
```

- by_kind 基于 scope 过滤后、kind 未过滤前的集合（facet chips 计数用）。
- item 字段：id, kind, project_id(逻辑), project_name, title, cwd, first_ts, last_ts, total_msgs, total_tokens, parent_session_id, parent_title, team_id, team_name, agent{type,name,description,color}(meta_json 解出), link_source, jsonl_available。
- **不得出现**：record_project_id / jsonl_rel_path / 绝对路径。
- 排序：last_ts desc 全局（不分类型分组；C2 由行内"所属主会话"链接体现）。

### 4.2 等价入口与兼容别名（过渡期，阶段 4 删除）

- `GET /api/v2/project/<id>/sessions?kind=` 保留，等价 scope=project:<id>；前端切换至规范入口。
- 响应兼容别名：`session_kind`=kind；`primary_total`=by_kind.primary；`automatic_total`=job+sdk+subagent+teammate 之和；`automatic_all_total`=同 automatic_total；`related_total`=嵌套会话数；`teammate_total`=by_kind.teammate。

### 4.3 session_detail 瘦身

响应移除下属/相关会话数组（children/related_*，以代码现状为准）；新增 `descendant_count`；保留 lineage/parent/团队卡片。前端经 `#sessions?parent=<id>` 查看下属。

### 4.4 失联会话（orphans）

端点与表沿用现状。要求（C3）：索引收录转录时自动移除对应失联记录；仅"移除记录"显式操作可删；无任何自动清理。

### 4.5 回收级联

`POST /api/v2/trash-session {project_id, session_id, cascade=true}`：

- cascade=true：连同 parent 链下的全部嵌套会话（子代理+队友，含 .meta.json）一并回收；
- 响应新增 `trashed`:[ids]；
- 子代理/队友行发起回收不级联；
- hard-delete：前端移除入口；端点保留至阶段 4。

## 5. UI 契约

### 5.1 导航

工作台 / 项目 / 会话 / 团队 / 搜索 / 设置（"跨项目会话"更名"会话"，route 不变）。

### 5.2 sessionRow()（唯一会话行渲染器）

一处实现，四处复用：浏览器、工作台最近、搜索结果、团队详情会话区。
行内容：类型标签(主会话/后台任务/SDK/子代理/队友)、标题、项目名、**所属主会话链接（C2）**、团队链接、时间、消息/Token、回收按钮（存在下属时弹级联确认）。

### 5.3 会话浏览器

- 路由：`#sessions`（全部）与 `#sessions?parent=<id>`（下属视图）。
- facet 条：chips [全部 | 主会话 | 后台任务 | SDK | 子代理 | 队友 | 自动会话(预设)]（带 by_kind 计数）+ 团队下拉 + 关键词框 + "失联 (N)" chip（打开面板）。
- **默认 facet=全部**（C1：首屏可见所有会话）。
- 项目详情页 = 项目统计条 + 本组件（scope=project）。

### 5.4 会话详情页

移除下属/相关区块；新增按钮"查看下属会话 (N)"（descendant_count）→ 浏览器 parent 视图；保留 lineage、团队卡片、消息区。

### 5.5 失联面板

归入会话页（chip 触发），内容与操作沿用现状：列表 + "移除记录"。文案注明"转录找回后自动归位"。

### 5.6 设置页"数据维护"

收纳：路径映射、JSONL 迁移、索引重建（全量/增量）、失联记录管理、AI 批量任务入口。项目详情页原"位置/迁移/AI/危险"页签全部移除。

### 5.7 工作台

统计卡 + by_kind 迷你分布 + 最近会话（sessionRow）。

## 6. 管理语义（C2 落地）

- 回收站是 UI 上的唯一删除路径。
- 级联规则：**任何会话，若 descendant_count>0，回收时弹出级联确认框（"连同 N 个下属会话一起回收"，默认勾选）**；子代理/队友行回收不级联。
- 失联记录：仅"移除记录"一种消失途径（C3）。

## 7. 不变式（评审逐条验收）

1. 一个会话恰好一个 kind，判定树是唯一来源
2. 任何统计数字 = 对应 facet 之和
3. API 响应不含 record_project_id / jsonl_rel_path / 绝对路径
4. 前端任何会话行渲染自 sessionRow()
5. 团队筛选 = scope=team，不存在第二条团队列表逻辑
6. 失联记录仅两种消失途径：转录找回 / 用户显式移除
7. descendant_count>0 的会话回收时必弹级联确认（默认勾选）
8. meta_json 不含 cwd 与路径

## 8. 实施阶段与分工

阶段 1（indexer）/ 阶段 2（api）/ 阶段 3（frontend）并行；阶段 4 在 v2.1.0 发布并稳定后单独执行（本推送不含）。阶段 4 清单补充：P2-1（list 热路径 jsonl_available 逐行 stat → 改走 path_exists 列或扫描缓存）。

| 队友 | 文件 | 职责 |
|---|---|---|
| indexer | v2_index.py；tests/test_v2_index.py*、tests/test_v2_teams.py*；tests/test_v2_redesign.py(新) | schema v6、判定树、meta_json、link_source、jsonl_rel_path、facet 助手、list_sessions 新契约+别名、detail 瘦身、orphan 恢复保证 |
| api | app.py；tests/test_app_*.py*；tests/test_app_redesign.py(新) | 路由参数透传、trash cascade、APP_VERSION/APP_UI_VERSION=v2.1.0、别名兼容 |
| frontend | static/index.html、static/app.js、static/style.css | §5.1–5.7 全部 UI（含侧栏 v2.1.0 与缓存参数 ?v=20260813-redesign） |
| reviewer | tmp/*（e2e 与评审脚本） | 先按契约编写 e2e/评审脚本；接 lead 通知后执行全量评审 |

\*：仅当旧断言与本文档冲突时更新。

权限：队友为普通权限会话——禁止 git 提交/推送、禁止构建 exe、禁止发布；审批类操作一律留给 lead 主会话。

## 9. 测试目标

- 存量 64 个测试保持通过（别名兼容兜底；与本文档冲突者按新契约更新）
- 新增 tests/test_v2_redesign.py ≥15：判定树 6 分支、回填、meta_json 无路径、link_source、facet、scope 过滤、automatic 预设、别名一致、orphan 恢复、jsonl_rel_path 相对性
- 新增 tests/test_app_redesign.py ≥10：参数透传、别名、级联回收/不级联/meta 连带、详情无 children、descendant_count、orphan 端点
- e2e：tmp/ 脚本走 HTTP 全链路（浏览器过滤、详情、级联回收、失联面板数据）
- node --check static/app.js、python -m py_compile v2_index.py app.py

## 10. 隐私红线（全部队友）

夹具只用 tempfile 合成数据，绝不读真实数据；代码/测试/提交不出现真实会话内容、成员 cwd、本机路径、密钥；meta_json 不存 cwd；团队内容不进日志/异常；发布物 diff 复查。

## 11. 发布（lead 执行）

版本 v2.1.0（app.py 双版本常量、index.html 侧栏、CHANGELOG 新条目）；PyInstaller 打包；更新仓库根 ClaudeCodeManager/（保留 data/）与 package-build zip；GitHub dev/main 推送 + Release v2.1.0；发布前隐私复检。
