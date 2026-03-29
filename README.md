<p align="center">
  <img src="frontend/public/assets/brand/logo-light.png" alt="Starfish Logo" width="280" />
</p>

<p align="center"><strong>Starfish</strong> · <a href="./README.zh.md">中文</a>｜<a href="./README.md"><strong>English</strong></a></p>
<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&size=17&speed=45&pause=80&deleteSpeed=120&color=111111&center=true&vCenter=true&repeat=true&width=980&lines=Science+Research+Engine+%C2%B7+Multi-Agent+Knowledge+Graph+Workbench;%20" alt="Typing Subtitle" />
</p>

## ⚡ Project Overview

**Starfish** is designed to turn research exploration from a one-off tool into a continuously evolving system. Through autonomous **multi-agent collaboration**, it can proactively retrieve evidence, generate insights, and iteratively refine strategies after each execution cycle. It is ready to use out of the box, yet not a static pipeline: it grows with evolving agent skills, toolsets, and memory bases. Compared with traditional human-in-the-loop workflows, Starfish follows a more human-on-the-loop paradigm, where researchers steer direction and judgment boundaries while AI co-evolves as a long-term research partner.

## ✨ Features

- **Multi-Agent**: One orchestrator coordinates specialized agents to solve complex research tasks collaboratively.
- **Subagent**: Heterogeneous subagents can compete and negotiate, with dynamic selection by quality, cost, and latency.
- **Workflow**: Retrieval, checkpointing, graph building, and lineage analysis are connected into an observable and replayable flow.
- **Knowledge Graph**: Automatically extracts papers, concepts, and relations into a structured research graph.
- **Lineage Tree**: Expands from a key paper to ancestors and descendants for tracing scientific evolution.

## 🖼️ System Snapshot

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/landpage.png" alt="Landing Page" width="100%" />
      <br />
      <sub>Homepage with bilingual entry and research input.</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/thesis_info.png" alt="Workflow Panel" width="100%" />
      <br />
      <sub>Workflow panel with paper retrieval and progress logs.</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/knowledge_graph.png" alt="Knowledge Graph" width="100%" />
      <br />
      <sub>Knowledge graph canvas for entities and relations.</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/blood_tree.png" alt="Lineage Tree" width="100%" />
      <br />
      <sub>Lineage tree view for ancestry and descendants.</sub>
    </td>
  </tr>
</table>

## 📦 Installation

### Quick Start

```bash
docker compose up -d --build
```

After startup:

- Frontend: `http://localhost:17327`
- Backend: `http://localhost:14032`

## 🔑 Configuration

Use `backend/.env` for backend settings and `frontend/.env.local` for frontend settings (optional).

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
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITHUB_OAUTH_REDIRECT_URI=http://localhost:17327/auth/github/callback
SESSION_SECRET=change-this-session-secret

# Service
CORS_ORIGINS=http://localhost:17327,http://127.0.0.1:17327
```

```env
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:14032
VITE_GOOGLE_CLIENT_ID=
```

For GitHub OAuth, ensure the callback URL configured in your GitHub OAuth App exactly matches `GITHUB_OAUTH_REDIRECT_URI`.

Optional retrieval enhancers: `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_MAILTO`, `SCITE_API_KEY`, `GITHUB_TOKEN`.
