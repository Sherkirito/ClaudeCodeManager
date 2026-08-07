# Claude Code Manager

本地运行的 Claude Code 桌面会话管理工具 — 在独立窗口中查看、搜索、AI 总结所有历史对话，支持一键打开 Claude Code。界面由系统 WebView2 承载，后端使用 Python 标准库，SQLite/FTS5 本地索引负责大数据量下的列表、搜索和会话浏览性能。

![](https://img.shields.io/badge/python-3.10+-blue) ![](https://img.shields.io/badge/license-MIT-green) ![](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## 快速开始

### 方式一：直接运行（推荐）

```bash
python -m pip install -r requirements.txt
python app.py
```

默认打开独立桌面窗口。若需要保留原浏览器调试方式，可执行 `python app.py --browser`。内部服务仅监听 `127.0.0.1`；如果 5141 不可用，程序会自动选择后续端口。

### 方式二：双击启动

- **Windows** — 双击 `start.bat`（或 `start.vbs` 静默启动）
- **macOS / Linux** — 终端执行 `python app.py`

### 方式三：打包为独立 exe

```bash
python -m pip install -r requirements.txt
python -m PyInstaller ClaudeCodeManager.spec
```

生成 `ClaudeCodeManager/` 目录（内含 `_internal/` 运行时），无需 Python 环境即可运行。`ClaudeCodeManager.spec` 已配置 pywebview/WebView2、静默窗口、`static/` 打包和应用图标。

Windows 打包配置只保留 WebView2/WinForms 所需组件，排除了其他平台渲染器和未使用的 NumPy/Pillow 等可选依赖；当前不含用户数据的运行时约 35 MB。

---

## 功能

| 模块 | 说明 |
|------|------|
| 总览仪表盘 | 项目数、会话数、消息数、Token 总量统计卡片 |
| 日期统计 | Dashboard 按日期展示最近会话活动柱状图 |
| 项目管理 | 自动识别工作目录，AI 生成 2-3 句中文项目简介 |
| 目录快速定位 | 项目列表可按真实路径逐层进入目录，并支持路径关键词过滤 |
| 项目筛选排序 | 项目列表支持按盘符分类，并按活跃时间、名称、会话数、Token 排序 |
| 会话查看 | 完整对话回放，代码块高亮，Agent 工具调用折叠显示 |
| AI 总结 | 项目级简介 + 会话级详细总结，支持 DeepSeek / Anthropic |
| 侧边栏快速启动 | 路径 + 4 种权限模式，随时一键打开 Claude Code |
| 权限选择 | 侧边栏、项目页、会话页均可选择打开权限 |
| 会话恢复 | 会话详情页点击"打开 Claude Code"直接 `--resume {UUID}` 进入，并优先使用该会话 JSONL 的起始/项目工作目录，避免 cwd 变化后找不到 UUID |
| 路径映射 | 项目被移动后，可把旧项目路径映射到新路径，打开项目时自动进入新位置 |
| 文件资源管理器 | 项目详情页可直接在系统文件资源管理器中打开项目目录，并自动使用重定向后的新路径 |
| 会话迁移 | 将旧路径编码目录下的 Claude JSONL 迁移到新路径编码目录，并重写 cwd 前缀，支持在新位置继续 `--resume` |
| 删除管理 | 支持项目、会话级别删除，也支持项目和会话批量删除 |
| 桌面窗口 | pywebview + WebView2 独立窗口，保留现有网页 UI 效果 |
| 进程管理 | 关闭窗口会同步停止后台服务；重复启动 EXE 会唤醒已有窗口 |
| v2 索引 | 增量扫描 JSONL 到 SQLite，项目、会话、消息分页读取，全文搜索走 FTS5 |
| v2 前端 | 新增 Sessions 一级入口，项目/会话分页、消息分页、搜索优先的管理界面 |
| 会话谱系 | 自动识别 Subagent、后台 Job 和 SDK 会话，明确的下属记录折叠归入母会话，未关联自动会话独立收纳 |
| 目录快速定位 | v2 项目页支持按真实路径逐级进入目录，并按当前目录范围分页展示 |
| 会话列表操作 | 会话列表外侧直接显示 AI 简介，并提供权限选择和打开 Claude Code 按钮 |
| 软删除 | v2 页面将项目/会话移到 `data/trash/`，避免直接物理删除 |
| 批量管理 | v2 项目页支持项目多选批量移到回收站，项目详情页支持会话多选批量移到回收站 |

---

## 打开 Claude Code 与权限

所有"打开 Claude Code"按钮都会调用本机 `claude` 命令。项目级按钮只进入对应工作目录；会话级按钮会追加 `--resume {会话UUID}`，直接恢复具体会话。会话列表仍显示最新 cwd，但恢复时后端会重新读取 JSONL，并优先在会话最初的项目目录下执行，以匹配 Claude Code 的项目存储目录。

如果你整理文件夹，把项目从旧路径移动到新路径：

- 先在项目页点击“映射新位置”，选择新的项目目录。之后“打开项目”会直接打开新目录。
- 如果还需要在新目录继续恢复旧会话，再点击“迁移会话”。管理器会把旧 Claude JSONL 迁移到新路径对应的 `~/.claude/projects/` 目录，并把 JSONL 顶层 `cwd` 的旧路径前缀改成新路径前缀。
- 如果只做了映射就点击“恢复会话”，管理器会提示先迁移会话，而不会再打开一个必然报错的终端。
- 迁移前的旧 JSONL 会备份到当前运行方式对应的 `data/migrations/`。

权限下拉对应的真实命令参数如下：

| 选项 | 实际参数 | 含义 |
|------|----------|------|
| 仅阅读 | `--allowedTools Read` | 只允许读取工具 |
| 文件编辑 | `--allowedTools Read,Write` | 允许读取和写入工具 |
| 标准权限 | 不追加权限参数 | 使用 Claude Code 默认权限规则，是否询问由 Claude Code 自身决定 |
| 完全控制 | `--permission-mode bypassPermissions` | 跳过权限询问，适合只在可信目录使用 |

侧边栏快速启动默认目录为当前用户主目录，可选择自定义目录。自定义目录通过 Windows 原生文件夹选择窗口获取，不使用浏览器上传控件。

---

## 项目结构

```
ClaudeCodeManager/
├── app.py                 # 后端服务器（纯 stdlib）
├── start.bat              # Windows 启动脚本
├── start.vbs              # Windows 静默启动（无终端窗口）
├── .gitignore
├── README.md
├── v2_index.py            # SQLite/FTS5 增量索引和 v2 查询 API 支撑
├── assets/
│   ├── app-icon.ico       # EXE 图标
│   ├── app-icon.png       # 图标预览
│   └── app-icon.svg       # 图标源稿
├── data/
│   ├── api-config.json           # AI 接口配置
│   ├── api-config.example.json   # 配置模板
│   ├── project-descriptions.json # AI 项目简介缓存
│   └── session-summaries.json    # AI 会话总结缓存
├── ClaudeCodeManager/            # 打包输出 (--onedir)
│   ├── ClaudeCodeManager.exe
│   ├── _internal/                # 运行时库
│   └── data/                     # 可写持久化数据
└── static/
    ├── index.html          # SPA 页面
    ├── app.js              # 前端逻辑
    └── style.css           # 样式
```

---

## AI 接口配置

首次使用需在设置页面填写 API 密钥，或手动创建 `data/api-config.json`：

```json
{
  "provider": "deepseek",
  "api_key": "sk-your-api-key-here",
  "api_endpoint": "https://api.deepseek.com/v1/chat/completions",
  "api_model": "deepseek-v4-flash"
}
```

也可复制 `data/api-config.example.json` 并重命名为 `api-config.json`，填入密钥即可。

### 支持的接口

| 接口 | 可用模型 |
|------|----------|
| DeepSeek | `deepseek-v4-flash`（推荐）, `deepseek-v4-pro` |
| **Anthropic** | `claude-haiku-4-5-20251001`, `claude-sonnet-4-6-20250514`, `claude-opus-4-7-20250514` |

> 切换接口类型后模型列表会自动更新。修改配置无需重启服务。

---

## 数据说明

所有数据从 `~/.claude/projects/` 本地读取，**不会上传至任何外部服务**。AI 总结功能仅在用户主动点击按钮时调用配置的 API。

配置、AI 摘要、回收站等持久化文件保存在运行方式对应的 `data/` 目录：

- 直接运行 `python app.py`：使用源码目录下的 `data/`。
- 双击打包后的 `ClaudeCodeManager.exe`：使用 `ClaudeCodeManager/data/`。

这两个配置目录是分开的。桌面版首次发现自己的 API Key 为空时，会自动从相邻源码目录的 `data/api-config.json` 接管旧版 AI 配置；设置页只显示密钥尾号，留空保存会继续保留原密钥。

SQLite 索引不再跟随运行目录保存。源码版和打包版统一使用 `%LOCALAPPDATA%\ClaudeCodeManager\manager-index.sqlite3`；非 Windows 环境使用 `~/.claude-code-manager/manager-index.sqlite3`，避免两份索引缓存产生不同统计结果。旧 `data/manager-index.sqlite3` 仅作为遗留缓存保留，不再读取。

| 文件 | 说明 |
|------|------|
| `api-config.json` | AI 接口配置（需自行创建，已加入 .gitignore） |
| `project-descriptions.json` | AI 生成的项目简介缓存 |
| `session-summaries.json` | AI 生成的会话总结缓存 |
| `path-mappings.json` | 项目旧路径到新路径的映射 |
| `%LOCALAPPDATA%\ClaudeCodeManager\manager-index.sqlite3` | 源码版与打包版共用的 v2 SQLite/FTS5 索引缓存，可删除后自动重建 |
| `webview/` | 独立窗口的 WebView2 本地存储和浏览数据 |

v2 索引只缓存从本地 JSONL 解析出的项目、会话、消息文本和统计信息。删除该数据库不会删除 Claude Code 原始记录。日常“刷新索引”只解析新增或变化的 JSONL；设置页的“完整重建”才会重新解析全部记录。

性能方面，后端使用多线程 loopback HTTP 服务，耗时的索引或 AI 请求不会再阻塞其他页面请求；静态资源使用内存缓存和 ETag；增量扫描会一次性预取文件签名，未发生会话变化时跳过项目关系和统计的全量重算。

项目归类以会话的起始 `cwd` 为准，不再直接信任 Claude 的路径编码文件夹名。中文路径发生编码碰撞时，管理器会拆成独立逻辑项目并显示“编码碰撞·已拆分”；原目录不存在时只显示“目录疑似已移动”，重定向目标必须由用户手动确认。

v2 页面中的“移到回收站”会把 Claude Code 原始 JSONL 或项目目录移动到当前运行方式对应的 `data/trash/`，并写入 `.meta.json` 记录原始路径。旧版硬删除 API 仍保留用于兼容，但新界面默认不调用。

“迁移会话”会把旧 JSONL 备份到当前运行方式对应的 `data/migrations/`，再把迁移后的 JSONL 写入新路径编码目录。

---

## 自检

修改源码或重新打包后，可以运行：

```bash
python tools/self_check.py
```

它会检查版本号、权限映射、打包静态文件和数据目录是否明显错位。

---

## 常见问题

**Q: 端口被占用？**  
A: 自动尝试 5141 → 5142 → ... 直到找到可用端口。遇到 Windows 端口保留导致的 `WinError 10013` 也按同样逻辑处理。

**Q: 独立窗口打不开？**
A: Windows 桌面版使用 Microsoft Edge WebView2 Runtime。Windows 10/11 通常已内置；缺失时安装 WebView2 Runtime，或先使用 `python app.py --browser` 回退到浏览器模式。

**Q: AI 总结不工作？**  
A: 确认 `data/api-config.json` 中已填入有效 API 密钥。支持 DeepSeek 和 Anthropic。

**Q: "打开 Claude Code"按钮无效？**  
A: 确保 `claude` 命令在 PATH 中。终端输入 `claude --version` 验证。

**Q: 数据会被上传吗？**  
A: 不会。所有数据存放在本地，AI 调用只发送会话文本摘要。

---

## 参考

本项目设计上参考了以下开源项目：

- [claude-home](https://www.npmjs.com/package/claude-home) — Claude Code Web 仪表盘
- [claude-devtools](https://github.com/matt1398/claude-devtools) — 桌面级 DevTools
- [claude-code-viewer](https://github.com/esc5221/claude-code-viewer) — Electron 会话浏览
- [claude-monitor](https://github.com/szaher/claude-monitor) — Go 实时监控

---

## 许可

MIT License
