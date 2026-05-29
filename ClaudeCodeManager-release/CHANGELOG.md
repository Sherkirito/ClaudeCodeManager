# Changelog

## v1.3 — 2026-05-29

### 新增功能

- **侧边栏快速启动** — 左侧导航栏 Settings 下方新增 Claude Code 一键启动区域（绿色按钮 + 路径选择 + 权限选择），无需进入设置页即可启动
- **4 种权限模式** — 仅阅读 / 文件编辑 / 标准权限 / 完全控制，下拉即可切换（后端实际生效：`--allowedTools` / `--permission-mode bypassPermissions`）
- **原生文件夹选择器** — 自定义路径改为后端 VBScript 调起 Windows `Shell.BrowseForFolder` 原生对话框，不再是浏览器上传框
- **延迟弹窗逻辑** — 选"选择文件夹..."不立即弹窗，点击"打开 Claude Code"时才弹出文件夹选择器
- **配置持久化** — 工作路径和权限选择自动保存至 `api-config.json`，重启后保持
- **会话一键恢复** — 会话详情页的"打开 Claude Code"执行 `claude --resume {会话UUID}`，直接进入该会话，不再弹出选择界面
- **会话标题搜索** — 搜索支持按 Claude 原生会话标题匹配

### 修正

- **侧边栏导航失效** — index.html 导航项缺失 onclick 导致 Dashboard/Projects/Settings 点击无响应
- **CSS 缓存** — `style.css` 追加版本号 `?v=20260529c`，避免浏览器缓存旧样式
- **版本标识混乱** — 侧边栏底部、控制台输出同步更新为 v1.3
- **数据文件丢失** — 打包部署脚本遗漏 `session-summaries.json`、`project-descriptions.json`，导致 AI 总结数据不显示
- **权限空转** — 4 种权限模式之前只保存不传给 `launch_claude`，现已补全 `--allowedTools` 和 `--permission-mode bypassPermissions` 参数
- **EXE 打包清理** — 移除旧版 `--onefile` EXE（9.4 MB），只保留 `--onedir` 版本（2 MB），解决 DLL 找不到问题
- **多实例抢占** — 旧 EXE 未完全杀死导致端口被占，新代码一直无法启动

### 安全加固 (v1.3)

- **XSS** — `escA` 将 `&#39;` 改为 JS 原生转义 `\x27`，防止通过 `onclick` 内联属性注入任意脚本
- **路径穿越** — `_handle_session/delete_project/delete_session/summarize` 添加 `_VALID_ID` 正则校验，拒绝含 `.. / \` 的 ID
- **API 密钥泄露** — `_handle_set_api_config` 响应中移除 `api_key` 字段，不再返回到前端
- **请求体限制** — `do_POST` 强制 `Content-Length` ≤ 64 KB，拒绝超大请求
- **`allow_reuse_address`** — 移到 `HTTPServer` 构造**之前**设置，确保端口复用生效

---

## v1.2 — 2026-05-29

### 新增功能

- **全局搜索** — 侧边栏搜索框，支持按 AI 总结内容、项目路径、会话标题搜索
- **回到顶部按钮** — 浏览会话时右下角浮动按钮，一键回到顶部
- **侧边栏返回按钮** — 在项目/会话详情页显示"← 返回"，支持导航栈
- **搜索增强** — 同时搜索 AI 项目描述、AI 会话总结、会话标题和项目路径

### 修正

- **模型名对齐官网** — `deepseek-chat` → `deepseek-v4-flash`，`deepseek-reasoner` → `deepseek-v4-pro`
- **模型名持久化** — 旧配置启动时自动迁移，同时更新磁盘文件避免下次依赖内存迁移
- **浏览器缓存问题** — 静态文件加 `Cache-Control: no-store`，JS 加版本号 `?v=20260529`，API 请求加 `_t=时间戳`
- **乱码修复** — 对 GBK 终端输出导致的 Latin-1 mojibake 做字节级还原

### 打包

- **EXE 构建修复** — 从 `--onefile` 改为 `--onedir`，解决 python313.dll 找不到的问题
- **`--noconsole`** — 双击不再弹出终端黑框
- **路径分离** — `static/` 打包进 `_internal`（只读），`data/` 放在 EXE 同目录（可写持久化）

---

## v1.1 — 2026-05-29

### 新增功能

- **AI agent 工具调用合并** — 连续 tool_use + tool_result 自动折叠为"Agent 工作中"可展开卡片
- **编码兼容性** — JSONL 读取使用 UTF-8 → GBK → GB18030 回退链

### 修正

- 中文目录名解析修复
- 时间戳类型异常处理

---

## v1.0 — 2026-05-29

初始版本：Claude Code 会话管理工具。

- 项目/会话仪表盘
- 完整对话回放，代码块渲染
- AI 项目简介 + 会话总结（DeepSeek / Anthropic）
- 一键打开 Claude Code
- 项目/会话删除管理
