<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="StarFish Logo" width="260" />
</p>

<h1 align="center">
<p align="center">科研智能检索引擎</p>
StarFish
</h1>


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

## 🧾本次对话修改清单（文件级）

以下为本轮对话落地到本地仓库的全部改动文件与内容摘要：

### Backend

- `backend/main.py`
  - 注册领域研究路由 `landscape_router`，开放 `/api/landscape/*` 接口族。

- `backend/models/schemas.py`
  - 新增领域研究数据模型：`LandscapeGenerateRequest`、`LandscapeCorePaper`、`LandscapeSubDirection`、`LandscapeResponse`。
  - 新增任务态模型：`LandscapeStepLog`、`LandscapeTaskDetailResponse` 与 `LandscapeStepKey`、状态字面量约束。

- `backend/api/landscape.py`（新增）
  - 新增领域研究 API：任务创建、任务轮询、任务结果获取、按 `landscape_id` 查询。

- `backend/core/domain_explorer.py`（新增）
  - 实现领域骨架生成（LLM + fallback）。
  - 子方向扩展固定为 10 个，并行论文检索（OpenAlex 优先，Semantic Scholar 回退）。
  - 增加关键词拓展补检索，尽可能保障每个方向具备 15+ 核心论文。
  - 计算 `correlation_score`、`recent_ratio`、`avg_citations`，并按热度排序。
  - 趋势总结生成（目标 1000+ 字，失败回退模板）。

- `backend/repositories/landscape_repository.py`（新增）
  - 新增领域研究结果仓储抽象与内存实现（save/get/has）。

- `backend/services/landscape_graph_adapter.py`（新增）
  - 将领域结果转换为统一图谱结构（seed/domain/paper 节点 + center/related 边）。
  - 支持 `correlation_score` 驱动子方向相关度，并限制每方向论文节点数量（默认 15）。

- `backend/services/landscape_service.py`（新增）
  - 新增异步任务编排：`research -> retrieve -> summarize -> graph` 四阶段。
  - 提供实时 `step_logs`、`preview_graph`、`preview_stats`，支持前端轮询实时渲染。
  - 任务完成后持久化并支持按 task/result 查询。

- `backend/repositories/neo4j_repository.py`
  - 新增 `store_domain_landscape` 与 `_write_domain_landscape`，支持领域结果写入 Neo4j：
    - `LandscapeRun` / `Domain` / `SubDomain` / `Method` / `Paper` 及关系写入。

### Frontend

- `frontend/src/views/InputView.vue`
  - 输入类型新增“研究领域（domain）”。
  - 按输入类型动态切换 placeholder 与 hint（论文 ID/DOI/PDF/领域）。

- `frontend/src/App.vue`
  - 工作流入口分流：论文工作流与领域工作流。
  - header 步骤总数动态适配（论文 2 步、领域 4 步）。

- `frontend/src/api/index.js`
  - 新增领域任务 API：`startLandscapeGeneration`、`getLandscapeTask`、`getLandscapeResult`。
  - 新增 `generateLandscape(query, onProgress)` 轮询封装。

- `frontend/src/views/LandscapeView.vue`（新增）
  - 新增领域工作流主视图与四阶段状态管理。
  - 实时消费后端 `step_logs + preview_graph`，完成后自动收敛步骤状态。
  - 修复步骤日志状态：运行中显示 `Doing`，完成后自动转 `Done`，避免常驻 `Doing`。

- `frontend/src/components/landscape/LandscapeWorkflowPanel.vue`（新增）
  - 新增领域工作流右侧流程卡片与日志列表。
  - 步骤状态徽章支持 `Pending / Doing / Done / Error`。

- `frontend/src/components/landscape/LandscapeWorkspace.vue`（新增）
  - 新增领域左侧工作区：`知识图谱 / 趋势洞察` 双 Tab。
  - 图谱刷新按钮与 Tab 控件固定在图谱右上角。
  - 移除右上角“实时生成中已完成 x/x”标签（按需求删除）。

- `frontend/src/components/landscape/landscapeGraphAdapter.js`（新增）
  - 前端 fallback 图谱构建器。
  - 每方向支持扩展到 15 篇论文子节点，支持 `correlation_score` 关联度。

- `frontend/src/components/graph/KnowledgeGraphCanvas.vue`
  - 图谱交互增强：
    - 领域节点悬浮卡片补充状态、近2年占比、均引用、数据源、核心论文、代表方法。
    - 缩放范围限制 `0.35 ~ 2.2`，防止过度缩放。
    - 修复“放大后自动缩小”：更新/resize 时保存并恢复 viewport，不自动回缩。
  - 视觉增强：
    - 中心节点尺寸提升并加粗描边、加大标签，显著突出。
    - 方向间配色区分度提升；同方向子节点继承方向色。
    - 子方向热度越高，节点颜色越深。

- `frontend/src/components/graph/knowledgeNodeDetail.js`
  - 领域节点详情数据结构扩展（状态文案、比例、均引用、方法、核心论文列表）。

- `frontend/src/styles/app.css`
  - 输入区提示样式、流程卡头部与状态样式增强。
  - 运行态步骤卡片改浅蓝风格（符合 Doing 语义）。

- `frontend/src/styles/components.css`
  - 新增领域节点卡片中“核心论文/代表方法”区块样式与移动端适配。

- `frontend/index.html`
  - 浏览器标签页 favicon 切换为 `/assets/brand/starfish-logo.png`。

- `frontend/public/assets/brand/starfish-logo.png`（新增）
  - 新增并启用浏览器标签页 logo 资源。

### 文档

- `README.md`
  - 更新并追加本节“文件级修改清单”，用于回顾本轮对话全部改动内容。
