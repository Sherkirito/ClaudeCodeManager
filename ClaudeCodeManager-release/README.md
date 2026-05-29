# Claude Code Manager

本地运行的 Claude Code 会话管理工具 — 浏览器端查看、搜索、AI 总结所有历史对话，支持一键打开 Claude Code。纯 Python 标准库实现，零外部依赖。

![](https://img.shields.io/badge/python-3.10+-blue) ![](https://img.shields.io/badge/license-MIT-green) ![](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## 快速开始

### 方式一：直接运行（推荐）

```bash
python app.py
```

浏览器打开 **http://127.0.0.1:5141**。

### 方式二：双击启动

- **Windows** — 双击 `start.bat`（或 `start.vbs` 静默启动）
- **macOS / Linux** — 终端执行 `python app.py`

### 方式三：打包为独立 exe

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconsole --onedir --name ClaudeCodeManager --add-data "static;static" app.py
```

生成 `ClaudeCodeManager/` 目录（内含 `_internal/` 运行时），无需 Python 环境即可运行。

---

## 功能

| 模块 | 说明 |
|------|------|
| 总览仪表盘 | 项目数、会话数、消息数、Token 总量统计卡片 |
| 项目管理 | 自动识别工作目录，AI 生成 2-3 句中文项目简介 |
| 会话查看 | 完整对话回放，代码块高亮，Agent 工具调用折叠显示 |
| AI 总结 | 项目级简介 + 会话级详细总结，支持 DeepSeek / Anthropic |
| 侧边栏快速启动 | 路径 + 4 种权限模式，随时一键打开 Claude Code |
| 会话恢复 | 会话详情页点击"打开 Claude Code"直接 `--resume {UUID}` 进入 |
| 删除管理 | 支持项目和会话级别的删除，操作前确认 |

---

## 项目结构

```
ClaudeCodeManager/
├── app.py                 # 后端服务器（纯 stdlib）
├── start.bat              # Windows 启动脚本
├── start.vbs              # Windows 静默启动（无终端窗口）
├── .gitignore
├── README.md
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

持久化文件保存在 `data/` 目录：

| 文件 | 说明 |
|------|------|
| `api-config.json` | AI 接口配置（需自行创建，已加入 .gitignore） |
| `project-descriptions.json` | AI 生成的项目简介缓存 |
| `session-summaries.json` | AI 生成的会话总结缓存 |

---

## 常见问题

**Q: 端口被占用？**  
A: 自动尝试 5141 → 5142 → ... 直到找到可用端口。

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
