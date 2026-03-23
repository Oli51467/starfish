# Repository Guidelines

## Project Structure & Module Organization
- `backend/` hosts the FastAPI app: `api/` (routes), `services/` (business logic), `repositories/` (data access), `core/` (settings/utilities), `models/` (schemas), `external/` (third-party clients).
- `frontend/` is a Vue 3 + Vite client. Main app code is in `frontend/src/` (`views/`, `components/`, `stores/`, `composables/`, `router/`, `styles/`).
- Shared orchestration/docs are at repo root: `docker-compose.yml`, `README.md`, `STYLE.md`, and scripts like `start-dev.sh`.

## Build, Test, and Development Commands
- `npm run dev:all` (root): start frontend + backend in local dev mode.
- `docker compose up -d --build backend`: run backend with Postgres, Redis, and Neo4j dependencies.
- `python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 14032` (from `backend/`): run backend only.
- `npm --prefix frontend install && npm --prefix frontend run dev`: run frontend only.
- `npm --prefix frontend run build`: required frontend verification check before PRs.

## Coding Style & Naming Conventions
- Python: PEP 8, 4-space indentation, explicit type hints, and clean service/repository separation.
- Python naming: `snake_case` for modules/functions, `PascalCase` for classes.
- Vue naming: components use `PascalCase.vue`; stores/composables use `camelCase` (for example, `authStore.js`, `usePaperWorkflow.js`).
- Styling: follow `STYLE.md` strictly; prefer existing CSS tokens/variables over hardcoded colors, shadows, or radii.

## Testing Guidelines
- No formal automated suite is configured yet.
- Minimum smoke checks before submitting:
  - `curl http://localhost:14032/health`
  - Validate main UI flow from `InputView` to `WorkflowView`/`LandscapeView`.
- If tests are added, place backend tests in `backend/tests/test_*.py` and frontend tests in `frontend/src/**/__tests__/`.

## Commit & Pull Request Guidelines
- Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).
- Keep each commit focused and imperative (single logical change).
- PRs should include: concise summary, affected paths, verification steps, linked issue/task, and UI screenshots/video when relevant.

## Security & Scope Guardrails
- Keep secrets only in `backend/.env`; never commit credentials.
- Default ports: frontend `17327`, backend `14032`, Postgres `15432`, Redis `16379`, Neo4j `7474/7687`.
- Implement only requested scope; avoid unrelated refactors or behavior changes.
- Preserve core interactions (click/drag/zoom/refresh/fullscreen/detail panels) and keep user-facing copy focused on product value, not backend internals.
