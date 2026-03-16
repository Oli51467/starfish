# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Starfish is a science research engine that helps researchers explore academic fields through automated paper retrieval, knowledge graph construction, and visual analysis. It transforms scattered research information into structured, navigable knowledge maps.

### Architecture

**Frontend (Vue 3 + Vite)**
- Vue 3 with Composition API
- Vue Router for navigation
- Pinia stores for state management (auth, papers, maps, research history)
- AntV G6 for knowledge graph visualization
- Component structure: views, components (common, graph, cards, layout, landscape, lineage)

**Backend (FastAPI + Python)**
- FastAPI with async/await patterns
- Modular API structure: `/api` routers for different domains
- Service layer: business logic in `/services`
- Repository layer: data access in `/repositories` 
- Core utilities: `/core` (LLM client, graph builder, task manager, etc.)
- Pydantic models for request/response schemas

**Data Layer**
- PostgreSQL: primary database for research history and metadata
- Neo4j: knowledge graph storage for paper relationships
- Redis: caching and session management
- Semantic Scholar API: paper data retrieval

### Key Workflows

1. **Paper Analysis**: Input (arXiv ID/DOI/research field) → paper retrieval → relationship extraction → knowledge graph construction
2. **Research History**: Persistent storage of user research sessions with Google Auth
3. **Knowledge Graph**: Interactive visualization of paper relationships and research lineages
4. **Gap Detection**: Automated identification of research gaps and opportunities

## Development Commands

### Full Stack Development
```bash
# Start both frontend and backend with auto-reload
./start-dev.sh

# Or start individually:
npm --prefix frontend run dev        # Frontend on :17327
cd backend && python3 -m uvicorn main:app --reload --port 14032  # Backend on :14032
```

### Frontend Only
```bash
cd frontend
npm install
npm run dev     # Development server
npm run build   # Production build
npm run preview # Preview production build
```

### Backend Only
```bash
cd backend
pip install -r requirements.txt
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 14032
```

### Docker Deployment
```bash
# Full stack with dependencies
docker compose up -d

# Backend only with dependencies
docker compose up -d --build backend
```

## Database Setup

The application requires PostgreSQL, Neo4j, and Redis. Use Docker Compose for local development:

```bash
docker compose up -d postgres neo4j redis
```

**Connection Details:**
- PostgreSQL: localhost:15432 (starfish/starfish/starfish)
- Neo4j: localhost:7474 (neo4j/starfish) 
- Redis: localhost:16379

## Environment Configuration

Backend requires `.env` file in `/backend` directory. See `backend/.env.example` for required variables including:
- Database connections
- OpenAI API key for LLM services
- Google OAuth credentials
- External API keys (Semantic Scholar, etc.)

## Code Patterns

### Frontend
- Use Composition API with `<script setup>`
- Store management with Pinia (reactive state, actions, getters)
- API calls through centralized `/src/api/index.js`
- Component props validation and TypeScript-style JSDoc comments
- Error boundaries and loading states for async operations

### Backend
- Async/await for all I/O operations
- Dependency injection pattern for services and repositories
- Pydantic models for all API contracts
- Repository pattern for data access abstraction
- Service layer for business logic separation
- FastAPI dependency system for auth and database connections

### Database
- Neo4j for graph relationships (papers, citations, research lineages)
- PostgreSQL for structured data (user sessions, research history)
- Repository pattern abstracts database specifics from business logic

## Key Files

- `frontend/src/stores/`: Pinia state management
- `backend/api/`: FastAPI route handlers
- `backend/services/`: Business logic layer
- `backend/core/`: Core utilities (LLM, graph building, task management)
- `backend/models/schemas.py`: Pydantic models for API contracts
- `start-dev.sh`: Development environment startup script