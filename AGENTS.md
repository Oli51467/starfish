# Repository Guidelines

## Project Structure & Module Organization
- `backend/` contains the FastAPI service. Key folders: `api/` (route handlers), `services/` (business logic), `repositories/` (data access), `core/` (settings, shared utilities), `models/` (schemas), `external/` (third-party clients), and `workers/` (async/background workflow docs).
- `frontend/` is a Vue 3 + Vite app. Main code is in `src/` with `views/`, `components/`, `stores/`, `composables/`, `router/`, and `styles/`. Static assets are in `frontend/public/assets/`.
- Root-level orchestration and docs live in `docker-compose.yml`, `start-dev.sh`, `README.md`, and `STYLE.md`.

## Build, Test, and Development Commands
- `npm run dev:all` (repo root): starts backend and frontend together via `start-dev.sh`.
- `docker compose up -d --build backend`: builds and runs backend with Postgres, Neo4j, and Redis.
- `npm --prefix frontend install && npm --prefix frontend run dev`: installs and runs frontend only.
- `python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 14032` (from `backend/`): runs backend only.
- `npm run build` / `npm run preview` (repo root): build and preview frontend production bundle.

## Coding Style & Naming Conventions
- Python: follow PEP 8, 4-space indentation, explicit type hints, and clear service/repository boundaries.
- Naming: Python modules/functions use `snake_case`; classes use `PascalCase`.
- Vue/JS: component files use `PascalCase.vue`; stores/composables use `camelCase` filenames (for example, `authStore.js`, `usePaperWorkflow.js`).
- Frontend styling must follow `STYLE.md`: use CSS variables/tokens and keep the minimal white-console visual style.

## Project-Specific Modification Rules
- Implement only the user’s explicit request first. Do not expand scope with unrelated cleanup, refactors, or feature changes unless the user asks for them.
- Keep code changes high-cohesion and low-coupling. Separate view rendering, state management, API access, workflow orchestration, and graph/lineage rendering logic.
- Do not pile unrelated logic into one file. If a change naturally belongs in a composable, store, adapter, or component, keep it there.
- Treat `STYLE.md` as a hard constraint. Reuse global CSS tokens first; do not introduce hardcoded colors, shadows, or radii unless there is no existing token and a new token is added deliberately.
- User-facing copy must describe product value and execution progress, not implementation details. Avoid exposing API names, provider names, database names, query parameters, fallback internals, or similar technical details in the UI by default.
- Workflow cards and progress panels must reflect real execution stages. It is acceptable to rewrite copy into user-facing language, but the displayed steps should still correspond to actual runtime behavior.
- Keep equivalent interactions consistent across workflow, research history, knowledge graph, and lineage views. Refresh, fullscreen, tab switching, centering, zooming, and detail panels should behave consistently where the feature is conceptually the same.
- Research history should preserve fidelity with live results. Persisted knowledge graphs and lineage trees should stay as close as possible to the corresponding live views in structure, interaction, and information density.
- Prefer small, verifiable, low-risk edits. Avoid broad rewrites unless the current structure blocks the requested change.
- Protect core interactions first. Click, drag, zoom, refresh, recenter, fullscreen, and detail inspection behaviors are higher priority than visual polish.
- Validate every change at a minimum with the relevant local check. For frontend work, default to `npm --prefix frontend run build`; for backend changes, run the smallest meaningful verification available.

## Scope Boundaries
- Do not change unrelated routes, APIs, database logic, or page structure when fulfilling a scoped request.
- Do not rename established concepts, alter existing interaction models, or replace the project’s visual language without an explicit request.
- Do not use “while I’m here” optimizations to justify unrelated modifications.
- Do not rewrite shared logic silently. If a shared abstraction must change, keep compatibility and make the reason clear.
- Do not trade maintainability for speed with duplicated logic, oversized files, or hardcoded styling shortcuts.

## Testing Guidelines
- No automated test suite is currently configured in this repository.
- Minimum pre-PR smoke checks:
  - `curl http://localhost:14032/health`
  - Validate main UI workflow from `InputView` to `WorkflowView`/`LandscapeView`.
- If adding tests, use `backend/tests/test_*.py` for backend and `frontend/src/**/__tests__/` for frontend.

## Commit & Pull Request Guidelines
- Follow Conventional Commit prefixes used in history: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Keep commit subjects short, imperative, and scoped to one logical change.
- PRs should include: summary, affected paths, verification steps, and linked issue/task.
- Include screenshots (or short recordings) for UI changes and note any `.env` or API contract updates.

## Security & Configuration Tips
- Keep credentials in `backend/.env`; never commit secrets.
- Default local ports: frontend `17327`, backend `14032`, Postgres `15432`, Redis `16379`, Neo4j `7474/7687`.
- When updating `backend/external/` integrations, document required keys and fallback behavior in the PR.
