# StarFish

StarFish 是一个面向学术调研工作流的前后端项目骨架，当前版本聚焦首页工作流引导与基础 API 契约，便于后续逐步接入真实检索、图谱构建与推理能力。

## 技术栈

- Frontend: `Vue 3 + Vite`
- Backend: `FastAPI + Uvicorn`（Python 3.11+）
- Infra: `PostgreSQL + Neo4j + Redis`（Docker Compose）

## 目录结构

```text
.
├── frontend/                 # 前端工程
│   ├── public/
│   │   └── assets/brand/
│   │       └── logo-light.png
│   └── src/
├── backend/                  # FastAPI 后端
├── docker-compose.yml
├── start-dev.sh              # 一键本地启动前后端
├── STYLE.md                  # 前端风格规范
└── PRD.md
```

## 本地开发

### 1) 安装依赖

```bash
# 前端
npm --prefix frontend install

# 后端
python3 -m pip install -r backend/requirements.txt
```

### 2) 配置环境变量

```bash
cp backend/.env.example backend/.env
```

如需接入兼容 OpenAI 格式模型，在 `backend/.env` 中填写：

- `API_KEY`
- （可选）`OPENAI_BASE_URL`
- （可选）`OPENAI_MODEL`

### 3) 一键启动

```bash
npm run dev:all
```

- 前端: `http://localhost:17327`
- 后端: `http://localhost:14032`
- 健康检查: `http://localhost:14032/health`
- API 文档: `http://localhost:14032/docs`

## Docker 启动

```bash
docker compose up -d --build
```

服务端口：

- Frontend: `17327`
- Backend: `14032`
- Postgres: `15432`
- Neo4j: `7474` / `7687`
- Redis: `16379`

停止：

```bash
docker compose down
```

## 常用重启方式

- 本地开发重启：`Ctrl + C` 后再次执行 `npm run dev:all`
- Docker 重启（不重建镜像）：`docker compose restart frontend backend`
- Docker 重建（代码有更新）：`docker compose up -d --build`

## 当前后端接口（骨架）

- `POST /api/map/generate`
- `GET /api/tasks/{task_id}`
- `GET /api/map/{map_id}`
- `GET /api/reading-list/{map_id}`
- `GET /api/gaps/{map_id}`
- `GET /api/lineage/{paper_id}`

## 视觉与品牌资源

- Logo 统一放置在：`frontend/public/assets/brand/logo-light.png`
- 前端页面风格遵循：`STYLE.md`
