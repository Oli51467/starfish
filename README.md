<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="StarFish Logo" width="260" />
</p>

<h1 align="center">StarFish</h1>

<p align="center">面向科研检索与 GraphRAG 构建的前后端项目（Vue + FastAPI + Neo4j）。</p>

## 项目简介

StarFish 当前聚焦以下主线：

- 论文检索与元数据抓取（Semantic Scholar）
- 实体关系抽取与知识图谱构建
- Neo4j 落库与回读
- 前端工作流可视化（G6 + d3-force）

## 技术栈

- 前端：`Vue 3` + `Vite` + `@antv/g6`
- 后端：`FastAPI` + `Uvicorn`（Python 3.11+）
- 基础设施：`PostgreSQL` + `Neo4j` + `Redis`（Docker Compose）

## 目录结构

```text
.
├── frontend/                 # 前端工程
│   ├── public/assets/brand/  # 品牌资源（logo）
│   └── src/
├── backend/                  # FastAPI 后端
├── docker-compose.yml
├── start-dev.sh              # 一键启动前后端（本地开发模式）
├── PRD.md
└── STYLE.md
```

## 快速开始

### 1) 安装依赖

```bash
# 前端
npm --prefix frontend install

# 后端
python3 -m pip install -r backend/requirements.txt
```

### 2) 环境变量

```bash
cp backend/.env.example backend/.env
```

可按需填写：

- `API_KEY`（OpenAI-compatible）
- `OPENAI_BASE_URL`（可选）
- `OPENAI_MODEL`（可选）
- `SEMANTIC_SCHOLAR_API_KEY`（可选但推荐）

### 3) 启动方式

#### A. 本地开发模式（前后端本机运行）

```bash
npm run dev:all
```

服务地址：

- Frontend: `http://localhost:17327`
- Backend: `http://localhost:14032`
- Health: `http://localhost:14032/health`
- Docs: `http://localhost:14032/docs`

注意：`dev:all` 不会自动启动 Neo4j / Postgres / Redis 容器。若要使用 GraphRAG 落库，请先启动 Neo4j：

```bash
docker compose up -d neo4j
```

#### B. Docker 一体化模式（推荐）

```bash
docker compose up -d --build
```

端口映射：

- Frontend: `17327`
- Backend: `14032`
- Postgres: `15432`
- Neo4j HTTP: `7474`
- Neo4j Bolt: `7687`
- Redis: `16379`

停止服务：

```bash
docker compose down
```

## Neo4j 检查与排障

若工作流提示 `Neo4j 不可用，已跳过落库`：

```bash
# 1) 启动 neo4j
docker compose up -d neo4j

# 2) 检查后端状态
curl http://localhost:14032/api/graphrag/neo4j/status
```

期望返回：

```json
{"available": true}
```

Neo4j Browser：`http://localhost:7474`（默认：`neo4j / starfish`）

## 当前核心接口

- `GET /api/papers/metadata`：论文元数据抓取（Semantic Scholar）
- `POST /api/graphrag/build`：检索 + 抽取 + 图构建 + Neo4j 落库
- `GET /api/graphrag/{graph_id}`：图谱回读
- `GET /api/graphrag/neo4j/status`：Neo4j 可用性
- `POST /api/map/generate`
- `GET /api/tasks/{task_id}`
- `GET /api/map/{map_id}`
- `GET /api/reading-list/{map_id}`
- `GET /api/gaps/{map_id}`
- `GET /api/lineage/{paper_id}`

## 常用命令

```bash
# 本地模式重启
# Ctrl + C 后重新执行
npm run dev:all

# Docker 重启前后端
docker compose restart frontend backend

# Docker 重建并启动
docker compose up -d --build
```

## 品牌与样式

- Logo：`frontend/public/assets/brand/logo-light.png`
- 视觉规范：`STYLE.md`
