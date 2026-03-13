<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="StarFish Logo" width="260" />
</p>

<h1 align="center">StarFish</h1>

<p align="center">面向科研检索与双知识图谱构建的 GraphRAG 工程化系统（Vue + FastAPI + Neo4j）。</p>

## ⚡️项目概述

StarFish 在本轮迭代中重点增强了“可解释、可观察、可交互”的知识图谱能力：

- 双图谱创新：同一查询下同时构建并展示
  - 论文关联图谱（以输入论文为中心）
  - 领域关联图谱（以种子论文所在领域为中心）
- 关联度可解释计算：采用三维加权融合（0~1）
  - 引用关系得分 `0.5`
  - 语义相似度得分 `0.3`
  - 共同概念得分 `0.2`
- 可视编码统一：关联越高，距离越近、边色越深；低关联使用浅色/虚线，无关联可不连线。
- 交互增强：
  - 点击论文节点显示论文详情卡片
  - 点击领域节点显示领域详情卡片
  - 刷新图谱与切换 Tab 的工具栏化操作
- 视口自适应：图谱画布高度按屏幕可视区固定，避免超出滚动区后影响整体阅读。
- 后端可观测性：第 2 步新增 `build_steps`，直接输出关键执行路径（用于前端步骤日志渲染）。

技术栈：

- 前端：`Vue 3` + `Vite` + `@antv/g6`
- 后端：`FastAPI` + `Uvicorn`
- 数据层：`Neo4j`（图谱落库与回读）
- 检索源：`Semantic Scholar` + `OpenAlex`（失败自动回退）

## 🔁工作流程

当前工作流保留 2 步（第 1 步不变，第 2 步合并建图与抽取）：

1. 论文检索
- 执行网页检索规划、候选抓取、筛选排序。
- 前端展示检索 trace（来源、数量、耗时、链接）。

2. 建图&实体关系抽取
- 后端完成：节点/边构建、实体关系抽取、可选 Neo4j 落库。
- 返回 `build_steps`（仅 2 条关键执行路径）：
  - `build_extract`：建图与实体关系抽取结果
  - `store_graph`：落库状态与回读准备（成功/降级）
- 前端直接消费后端 `build_steps`，在第 2 步日志卡片中展示关键路径。

关键接口：

- `POST /api/graphrag/retrieve`：论文检索与筛选（含 trace）
- `POST /api/graphrag/build`：建图与实体关系抽取（含 `build_steps`）
- `GET /api/graphrag/{graph_id}`：图谱回读
- `GET /api/graphrag/neo4j/status`：Neo4j 可用性

## 🚀快速开始

### 1) 环境准备

```bash
cp backend/.env.example backend/.env
```

可按需配置：

- `SEMANTIC_SCHOLAR_API_KEY`
- `OPENALEX_MAILTO`
- `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`
- （可选）`DASHSCOPE_API_KEY`（用于语义 embedding）

### 2) 启动后端（Docker）

```bash
docker compose up -d --build backend neo4j
```

后端与图数据库：

- Backend: `http://localhost:14032`
- FastAPI Docs: `http://localhost:14032/docs`
- Neo4j Browser: `http://localhost:7474`

### 3) 启动前端（npm）

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

前端地址：

- Frontend: `http://localhost:17327`

### 4) 常用命令

```bash
# 查看 Neo4j 可用性
curl http://localhost:14032/api/graphrag/neo4j/status

# 重启后端容器
docker compose restart backend

# 重建后端 + Neo4j
docker compose up -d --build backend neo4j
```

