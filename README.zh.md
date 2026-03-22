<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="Starfish Logo" width="280" />
</p>

<p align="center"><strong>Starfish</strong> · <a href="./README.zh.md"><strong>中文</strong></a>｜<a href="./README.md">English</a></p>
<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&size=17&speed=45&pause=80&deleteSpeed=120&color=111111&center=true&vCenter=true&repeat=true&width=980&lines=%E9%9D%A2%E5%90%91%E7%A7%91%E7%A0%94%E6%8E%A2%E7%B4%A2%E7%9A%84+Multi-Agent+%E7%9F%A5%E8%AF%86%E5%9B%BE%E8%B0%B1%E5%B7%A5%E4%BD%9C%E5%8F%B0;%20" alt="Typing Subtitle" />
</p>

## ⚡ 项目简介

**Starfish** 旨在把“科研探索”从一次性工具升级为可持续演进的研究系统：通过可自治的**多智能体协作**，系统能够主动检索、生成洞察，并在每轮执行后持续迭代策略。它开箱即用，但不是静态流水线，而是会随着 Agent 能力、工具集与记忆库演化不断成长。相较传统 human-in-the-loop，Starfish 更接近 human-on-the-loop：研究者把控方向与判断边界，AI 作为长期协作的研究伙伴共同进化。

## ✨ Features

- **Multi-Agent**：由编排器统一调度多个专长 Agent，分工完成复杂科研任务。
- **Subagent**：支持异构子 Agent 竞争与协商，按质量、成本、时延动态选择执行者。
- **工作流**：把检索、确认、建图、血缘等阶段串成可观测、可回放的流程。
- **知识图谱**：自动抽取论文、概念与关系，构建结构化科研知识网络。
- **血缘树**：围绕关键论文展开祖先与后代脉络，追踪研究演化路径。

## 🖼️ 系统预览

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/landpage.png" alt="首页" width="100%" />
      <br />
      <sub>首页支持中英文切换与研究主题输入。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/thesis_info.png" alt="工作流面板" width="100%" />
      <br />
      <sub>工作流面板展示检索过程与阶段进度。</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/knowledge_graph.png" alt="知识图谱" width="100%" />
      <br />
      <sub>知识图谱画布展示论文实体与关系连接。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/blood_tree.png" alt="血缘树" width="100%" />
      <br />
      <sub>血缘树视图展示祖先与后代演化脉络。</sub>
    </td>
  </tr>
</table>

## 📦 Installation

### Quick Start（Docker）

```bash
docker compose up -d --build
```

启动后访问：

- Frontend: `http://localhost:17327`
- Backend: `http://localhost:14032`

## 🔑 Configuration

主要配置放在 `backend/.env`，前端配置放在 `frontend/.env.local`（可选）。

```env
# LLM
API_KEY=your_api_key
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-v3

# Data Layer
POSTGRES_DSN=postgresql://starfish:starfish@localhost:5432/starfish
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=starfish
REDIS_URL=redis://localhost:6379/0

# Auth
GOOGLE_CLIENT_ID=
SESSION_SECRET=change-this-session-secret

# Service
CORS_ORIGINS=http://localhost:17327,http://127.0.0.1:17327
```

```env
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:14032
VITE_GOOGLE_CLIENT_ID=
```

可选检索增强配置（按需启用）：`SEMANTIC_SCHOLAR_API_KEY`、`OPENALEX_MAILTO`、`SCITE_API_KEY`、`GITHUB_TOKEN`。
