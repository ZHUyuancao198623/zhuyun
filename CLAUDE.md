# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库概述

个人工具脚本集合，包含 Python 爬虫和 HTML 小工具。

## Git 忽略规则（重要）

`.gitignore` 使用**白名单模式**：默认忽略所有文件 (`*`)，仅放行明确列出的文件。**添加任何新文件时，必须同步更新 `.gitignore`**，否则文件不会被 Git 追踪。

## 项目文件

| 文件 | 说明 |
|------|------|
| `yituyu_scraper.py` | 艺图语 (yituyu.com) 图片爬虫，支持单作品/每日更新/标签/首页模式 |
| `netease_music_scraper.py` | 网易云音乐爬虫，支持搜索/歌单/歌词/评论/下载 |
| `claude_code/八卦钟.html` | 八卦钟可视化页面（太极图 + 后天八卦 + 时间显示） |
| `plugins.json` | Claude Code 插件清单（已安装 claude-hud） |
| `.mcp.json` | MCP 服务器配置（filesystem + github） |

## Python 脚本依赖

两个爬虫脚本的依赖在各自的文档字符串中已说明，核心依赖：
- `requests` — HTTP 请求
- `beautifulsoup4` — HTML 解析（仅 yituyu_scraper.py）

安装方式：`pip install requests beautifulsoup4`

所有脚本为独立 CLI 工具，无需项目级安装，直接 `python <script>.py --help` 查看用法。
