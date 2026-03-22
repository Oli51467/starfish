<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="Starfish Logo" width="280" />
</p>

<h1 align="center">Starfish</h1>
<p align="center">Science Research Engine · 面向科研探索的 Multi-Agent 知识图谱工作台</p>

## ⚡ 项目简介

**Starfish** 想解决一个很常见的问题：  
当你拿到一个论文主题时，信息太散、入口太多、关系不清楚，很难快速建立完整认知。

它把论文检索、关系抽取、知识图谱与血缘分析串成一个可视化流程，帮助你从“一个点”走到“一个研究全景”。

## 🤖 Multi-Agent 总览

Starfish 采用 **Multi-Agent 协作**，而不是单模型一次性完成全部任务：

- **Orchestrator（编排器）** 负责分解任务、调度阶段、汇总结果。
- **Specialized Agents（专长 Agent）** 分别处理检索、建图、血缘等子任务。
- 通过事件流把执行过程映射到工作流面板，进度和结果可追踪、可回放。

默认执行链路覆盖：规划、检索、确认、建图、血缘分析。

## 🔍 你可以用它做什么

- 从 `arXiv ID`、`DOI` 或 `领域研究` 发起分析
- 自动检索相关论文并构建知识图谱
- 生成血缘树并查看研究演进关系
- 在工作流中查看每一步执行进度

## 🧭 支持的检索入口

- `arXiv ID`：从单篇论文出发，扩展上下游研究脉络
- `DOI`：从正式出版论文出发，建立关联网络
- `领域研究`：从一个研究方向出发，自动展开子方向与核心论文

## 🔄 典型使用流程

1. 选择研究入口（arXiv ID / DOI / 领域研究）
2. 输入查询内容
3. 选择论文范围（如近 1 年、近 10 年）
4. 点击“开始分析”，等待工作流逐步完成
5. 在知识图谱与血缘树中查看结果

## 🚀 快速体验

### 1) 启动后端（Docker）

```bash
docker compose up -d --build backend
```

### 2) 启动前端（npm）

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

### 3) 打开页面

- 前端默认地址：`http://localhost:17327`
- 后端默认地址：`http://localhost:14032`

## 👥 适合谁

- 希望快速入门新方向的学生和研究者
- 需要做文献综述与开题调研的实验室团队
- 关注技术演化路线的产业研究人员

## 📌 说明

- Starfish 用于辅助科研调研，不替代人工阅读与学术判断。
- 结果质量会受到公开数据源可用性与网络状态影响。
