# 知己 Engine — 子项目宪法

> **当前状态**：编码中。为 App 提供全部后端 API。
> **本文件管辖范围**：仅 `src/engine/` 内部。

## 核心职责

Engine 只服务 App。

## 技术栈

- FastAPI（Python）
- SQLite（零外部依赖）
- AI API 代理（不暴露 Key）

## 目录结构

```
src/engine/
├── main.py          # FastAPI 入口
├── models.py        # SQLite 表创建
├── database.py      # DB 连接
├── config.py        # AI API 配置
├── routers/         # API 路由
├── agents/          # AI Agent
└── data/            # SQLite DB + uploads
```

## API 规范

详见 `src/app/docs/TECH-DESIGN.md` 的 API 设计章节。

## 禁止事项

- ❌ 直接暴露 AI API Key 给前端
- ❌ 引入外部数据库
