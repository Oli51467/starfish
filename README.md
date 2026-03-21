<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="Starfish Logo" width="280" />
</p>

<h1 align="center">Starfish</h1>
<p align="center">Multi-Agent Science Research Engine · 协商驱动的论文检索、知识图谱与血缘分析工作流。</p>

## 项目简介

**Starfish** 是一个面向科研调研的 **Multi-Agent 工作流系统**。  
它不再依赖单一 Agent 全流程“包办”，而是通过编排器协调多个异构 Agent 竞标、执行、互评和重投标，把论文检索到图谱/血缘分析串成可视化闭环。

目标很直接：把“散乱检索结果”变成“结构化、可追踪、可回放”的研究路径。

## 本版本重点（Multi-Agent 强化）

- 多 Agent 协商循环已落地：`round -> bid -> award -> critic -> rebid`
- 支持异构 Agent 竞争（置信度、成本、耗时综合评估）
- critic 否决后自动重投标，避免低质量结果直接落盘
- 预算约束强化：预算更新可视化，执行成本结算防超限展示
- 前端左侧工作流面板新增协商态势板（候选、赢家、否决、重试、预算）
- 任务恢复能力：浏览器关闭后可在首页提示并恢复到进行中任务
- 单用户单活跃任务限制：避免并发会话互相污染
- 失败任务回滚：总体失败时不写入研究历史

## Multi-Agent 架构

### 1) 编排层（Orchestrator / Coordinator）

- 负责任务分解、优先级、协商轮次推进与状态汇总
- 按任务阶段调度候选 Agent 参与竞标
- 管理预算消耗、critic 结果与重投标策略

### 2) Agent 层（Heterogeneous Agents）

- 每类任务可注册多个策略 Agent（如 `fast / balanced / budget / lineage`）
- 运行时基于动态置信度、估算成本、估算耗时进行竞标
- 执行结果进入 critic 复核，不达标可否决并触发重投标

### 3) 基础设施层

- 工作记忆：会话状态、事件流、执行上下文
- Tool/Service：检索、建图、血缘分析、历史存储
- 可视化：协商事件和工作流状态并行展示

## 协商闭环（Negotiation Lifecycle）

核心事件：

- `negotiation_round_started`
- `negotiation_bid_received`
- `negotiation_contract_awarded`
- `negotiation_budget_update`
- `negotiation_critic_veto`
- `negotiation_rebid_scheduled`

前端将这些事件聚合到步骤级态势板，展示：

- 当前轮次、任务类型、状态
- 全量候选 Agent 及其置信度/成本/耗时
- 中标结果、否决原因、重投标原因
- 实时预算进度

## 工作流阶段（默认顺序）

1. `planner`
2. `router`
3. `search`
4. `checkpoint_1`（自动确认）
5. `graph_build`
6. `checkpoint_2`
7. `parallel`（血缘/并行分析）

说明：

- 需求确认阶段默认自动推进，不需要用户手工“确认需求并继续”。
- 终止入口统一在工作流顶部进度区右侧图标按钮。

## 任务可靠性与会话约束

- 单用户同一时刻最多 1 个活跃任务
- 首页可探测活跃任务并弹出恢复入口
- 关闭页面不影响后端继续执行
- 重新进入可附着原会话继续查看进度与结果
- 总体失败时自动回滚，不保留失败记录到研究历史

## 你可以用它做什么

- 从 `arXiv ID`、`DOI` 或 `领域研究` 发起分析
- 自动检索论文并构建知识图谱
- 在统一流程中生成血缘树与研究空白提示
- 在每一步看到真实执行进度和协商细节

## 快速启动

### 1) 一键启动前后端（推荐）

```bash
npm run dev:all
```

### 2) 仅启动后端（Docker）

```bash
docker compose up -d --build backend
```

### 3) 仅启动前端

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

### 4) 访问地址

- 前端：`http://localhost:17327`
- 后端：`http://localhost:14032`

## 常用开发命令

```bash
# 后端本地开发
cd backend
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 14032

# 前端构建检查
npm --prefix frontend run build

# 健康检查
curl http://localhost:14032/health
```

## 关键 API（Research Runtime）

- `POST /api/research/start`：启动研究会话
- `GET /api/research/active`：查询当前用户活跃会话
- `GET /api/research/session/{session_id}`：拉取会话快照
- `POST /api/research/resume/{session_id}`：继续 checkpoint
- `POST /api/research/stop/{session_id}`：终止会话
- `WS /api/research/ws/{session_id}`：订阅实时事件

## 项目结构

```text
backend/
  api/           # FastAPI 路由
  services/      # 运行时编排与业务逻辑
  agents/        # 各节点 Agent 实现
  repositories/  # 数据访问
  core/          # 配置与基础能力
frontend/
  src/views/         # 页面
  src/components/    # UI 组件
  src/composables/   # 工作流状态与运行时聚合
  src/stores/        # 状态管理
```

## 适用人群

- 需要快速建立领域认知的学生/研究者
- 需要可回放研究流程的实验室团队
- 关注技术脉络与演进路线的产业研究人员

## 说明

- Starfish 用于辅助科研调研，不替代人工学术判断。
- 结果质量依赖公开数据源可用性与网络状态。
