# LeadFlow Setup & Developer Guide

This document details the configuration, local development workflows, container management, and verification procedures for LeadFlow.

---

## 1. System Prerequisites & Installation

### Required Tooling
| Component | Minimum Version | Status on Current Host | Notes / Official Links |
| :--- | :--- | :--- | :--- |
| **Python** | 3.12.x (64-bit) | ✅ Installed (`Python 3.12.6`) | Standard Windows Python runtime |
| **Node.js** | 20.9+ (Next.js 16 requirement) | ✅ Installed (`v24.21.0`) | Compatible with React 19 & Turbopack |
| **npm** | 10.x+ | ✅ Installed (`11.19.0`) | Package manager for `apps/web` |
| **Docker Desktop** | 24+ & Docker Compose v2+ | ❌ Not Detected | Required for local container stack |
| **Git** | 2.x+ | ❌ Not Detected | Required for version control |

### Manual Installation Instructions for Missing Tools

#### 1. Docker Desktop for Windows
1. Download Docker Desktop from [Docker's official site](https://www.docker.com/products/docker-desktop/).
2. Run `Docker Desktop Installer.exe`. Ensure the **Use WSL 2 instead of Hyper-V** option is selected during setup.
3. If WSL 2 is not yet installed on Windows, open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
4. Restart Windows when prompted.
5. Launch Docker Desktop and wait until the whale icon in the Windows notification area displays **Docker Desktop is running**.
6. Verify in PowerShell:
   ```powershell
   docker --version
   docker compose version
   ```

#### 2. Git for Windows
1. Download the 64-bit installer from [git-scm.com](https://git-scm.com/download/win).
2. Run the installer and keep default options (ensuring Git is added to `PATH`).
3. Verify in PowerShell:
   ```powershell
   git --version
   ```

---

## 2. Environment Configuration

The repository uses a dual-mode configuration allowing services to run directly on Windows or inside Docker Compose.

1. Ensure the root `.env` file exists:
   ```powershell
   # Copy template if .env does not already exist
   Copy-Item .env.example .env
   ```

2. Generate a secure random JWT secret key:
   ```powershell
   # In PowerShell with Python:
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Set this value to `JWT_SECRET_KEY` in `.env`.

3. Connection differences between host and containerized environments:

| Service | Local Process on Windows | Docker Compose Container |
| :--- | :--- | :--- |
| **PostgreSQL Host** | `localhost:5432` | `postgres:5432` |
| **PostgreSQL Database URL** | `postgresql+asyncpg://leadflow_admin:leadflow_admin_password@localhost:5432/leadflow` | `postgresql+asyncpg://leadflow_admin:leadflow_admin_password@postgres:5432/leadflow` |
| **Redis Host** | `localhost:6379` | `redis:6379` |
| **Redis URL** | `redis://localhost:6379/0` | `redis://redis:6379/0` |
| **Next.js Web URL** | `http://localhost:3000` | Port `3000:3000` mapped to host |
| **FastAPI Backend URL**| `http://localhost:8000` | Port `8000:8000` mapped to host |

> [!NOTE]
> Inside Docker containers, `localhost` refers to that container's loopback interface, not other services. The `infra/docker/docker-compose.yml` file explicitly sets `DATABASE_URL` pointing to `postgres:5432` and `REDIS_URL` pointing to `redis:6379/0` for the containerized `api` and `worker` services.

---

## 3. Docker Compose Services & Architecture

The stack is defined in `infra/docker/docker-compose.yml` using the bridge network `leadflow_net`:

| Compose Service Name | Container Name | Image / Build Context | Exposed Port | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `postgres` | `leadflow_postgres` | `postgres:16-alpine` | `5432:5432` | Primary PostgreSQL database with RLS policies & UUID extensions |
| `redis` | `leadflow_redis` | `redis:7-alpine` | `6379:6379` | In-memory cache and ARQ task queue broker with AOF persistence |
| `api` | `leadflow_api` | `apps/api/Dockerfile` | `8000:8000` | FastAPI backend with async SQLAlchemy 2.0 and OpenAPI docs |
| `worker` | `leadflow_worker` | `apps/api/Dockerfile` | None (internal) | ARQ background job worker executing search and enrichment tasks |
| `web` | `leadflow_web` | `apps/web/Dockerfile` | `3000:3000` | Next.js 16 frontend with React 19 and Tailwind CSS |

---

## 4. Container Management Commands

All commands below assume you are in the repository root directory (`LeadFlow_v1`).

### A. Validating Compose Configuration
Validate the Compose syntax and environment interpolation without starting any containers:
```powershell
docker compose -f infra/docker/docker-compose.yml config
```

### B. Starting Database & Cache Services (Recommended for Local Dev)
Start only PostgreSQL and Redis in the background:
```powershell
docker compose -f infra/docker/docker-compose.yml up -d postgres redis
```

### C. Starting the Entire Stack
Build and launch all 5 services concurrently:
```powershell
docker compose -f infra/docker/docker-compose.yml up -d
```

### D. Rebuilding Application Images
When backend or frontend dependencies change:
```powershell
docker compose -f infra/docker/docker-compose.yml build
# Or build and launch in one step:
docker compose -f infra/docker/docker-compose.yml up -d --build
```

### E. Checking Service Status and Health
```powershell
docker compose -f infra/docker/docker-compose.yml ps
```
The output displays the service state and health probe status (`healthy`, `starting`, or `unhealthy`).

### F. Viewing Container Logs
```powershell
# Follow logs across all containers:
docker compose -f infra/docker/docker-compose.yml logs -f

# Follow logs for specific services:
docker compose -f infra/docker/docker-compose.yml logs -f postgres redis
docker compose -f infra/docker/docker-compose.yml logs -f api
docker compose -f infra/docker/docker-compose.yml logs -f worker
```

### G. Restarting a Service
```powershell
docker compose -f infra/docker/docker-compose.yml restart postgres
docker compose -f infra/docker/docker-compose.yml restart redis
docker compose -f infra/docker/docker-compose.yml restart api
```

### H. Graceful Shutdown (Preserving Stored Data)
To stop all services **without deleting volumes or data**:
```powershell
docker compose -f infra/docker/docker-compose.yml stop
# Or tear down containers while keeping persistent volumes intact:
docker compose -f infra/docker/docker-compose.yml down
```

> [!CAUTION]
> **DESTRUCTIVE OPERATION WARNING**: Never run `docker compose down -v`. The `-v` flag removes the named persistent volumes (`postgres_data`, `redis_data`), which permanently erases the database and all stored tenant records.

---

## 5. Verifying Database & Redis Connectivity

### In-Container Verification Commands
Once containers are running:
```powershell
# 1. Verify PostgreSQL readiness:
docker compose -f infra/docker/docker-compose.yml exec postgres pg_isready -U leadflow_admin -d leadflow
# Expected output: /var/run/postgresql:5432 - accepting connections

# 2. Verify Redis responsiveness:
docker compose -f infra/docker/docker-compose.yml exec redis redis-cli ping
# Expected output: PONG
```

### Host Python Verification Script
LeadFlow includes an automated verification script `apps/api/test_connectivity.py` that checks both async PostgreSQL and Redis using the active application configuration:
```powershell
cd apps\api
.\.venv\Scripts\python.exe test_connectivity.py
```
Expected output when services are running:
```text
Testing PostgreSQL connection to: postgresql+asyncpg://leadflow_admin:leadflow_admin_password@localhost:5432/leadflow
PostgreSQL connection SUCCESSFUL! Result: 1
Testing Redis connection to: redis://localhost:6379/0
Redis connection SUCCESSFUL!

--- Summary ---
PostgreSQL: OK
Redis:      OK
```

### Application HTTP Readiness Probe
When the FastAPI backend is running:
```powershell
curl http://localhost:8000/readyz
# Expected output: {"status":"ready","database":"connected"}
```

---

## 6. Applying Alembic Migrations

Once PostgreSQL is healthy and accepting connections, apply the schema migrations:

### Running Migrations from Host (Windows)
```powershell
cd apps\api
.\.venv\Scripts\alembic.exe upgrade head
```

### Running Migrations Inside Docker
```powershell
docker compose -f infra/docker/docker-compose.yml exec api alembic upgrade head
```

### Existing Migrations
The repository includes `alembic/versions/001_initial_schema.py`, which provisions all 14 core tables with Row-Level Security (RLS) policies:
- `orgs`
- `users` (RLS enabled)
- `audiences` (RLS enabled)
- `engines` (RLS enabled)
- `engine_params`
- `searches` (RLS enabled)
- `leads` (RLS enabled)
- `enrichments` (RLS enabled)
- `scores` (RLS enabled)
- `contacts` (RLS enabled)
- `drafts` (RLS enabled)
- `crm_syncs` (RLS enabled)
- `runs` (RLS enabled)
- `audit_log`

To inspect the current database migration revision:
```powershell
cd apps\api
.\.venv\Scripts\alembic.exe current
```

---

## 7. Starting Local Development (Host Mode)

Once PostgreSQL and Redis are started (either via Docker or installed locally):

### Terminal 1: FastAPI Backend
```powershell
cd apps\api
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```
- Swagger Documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- Liveness Probe: [http://localhost:8000/healthz](http://localhost:8000/healthz)
- Readiness Probe: [http://localhost:8000/readyz](http://localhost:8000/readyz)

### Terminal 2: ARQ Background Worker
```powershell
cd apps\api
.\.venv\Scripts\python.exe -m arq app.jobs.worker.WorkerSettings
```
The worker initializes and connects to Redis, registering `run_search_pipeline` with tenant RLS isolation.

### Terminal 3: Next.js Frontend
```powershell
cd apps\web
npm run dev
```
- Web Application: [http://localhost:3000](http://localhost:3000)

---

## 8. Operational Observability, Diagnostics & Reliability

### A. Request Correlation Tracing (`X-Request-ID`)
All HTTP requests entering the FastAPI backend receive or preserve a unique `X-Request-ID` header. This ID is echoed in the response headers and attached to `request.state.request_id` to enable full end-to-end trace correlation across frontend requests and backend logs without logging PII or credentials.

### B. Automated Background Job Recovery
The ARQ worker lifecycle implements fault-tolerant stuck-run detection:
- **Worker Startup Hook**: When the ARQ worker process boots, it executes `recover_stuck_runs`, transitioning any abandoned `PENDING` or `RUNNING` jobs older than `ARQ_JOB_TIMEOUT` to `FAILED` with sanitized error details, preventing duplicate execution.
- **Quota Reconciliation**: For each recovered run, the organization's Redis concurrent run counter is automatically reconciled against the database, unblocking subsequent searches.
- **Polling Recovery**: If a frontend client polls `GET /api/v1/runs/{id}` for a job that exceeded the timeout, the endpoint transitions the run to `FAILED` and releases the reservation immediately.

### C. Performance & Latency Benchmarks
LeadFlow includes a non-destructive local performance baseline tool in `apps/api`:
```powershell
cd apps\api
.\.venv\Scripts\python.exe benchmark_baseline.py
```
This measures:
1. Redis atomic operation latency (`PING`, `INCR`).
2. PostgreSQL database query latency and buffer hit efficiency under active RLS.
3. FastAPI endpoint latency (median and p95 for `/healthz`, `/api/v1/auth/me`, `/api/v1/leads`).
