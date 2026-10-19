# Start Commands

> **Important**: Choose **Option 1** (Docker only) OR **Option 2** (Local Dev with 3 terminals). Do not run both at the same time.

## Option 1: Run Full Stack with Docker (All-in-one)

```powershell
# 1. Start all services in background
docker compose -f infra/docker/docker-compose.yml up -d

# 2. Run database migrations
docker compose -f infra/docker/docker-compose.yml exec api alembic upgrade head
```

---

## Option 2: Local Development (Recommended)

### Step 1: Start Database & Redis (Run once)
docker compose -f infra/docker/docker-compose.yml up -d 

### Terminal 1: Backend API

cd apps\api
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000


### Terminal 2: Background Worker (Leave running)


# Start worker (do not close this terminal, leave it running):
cd apps\api
.\.venv\Scripts\python.exe -m arq app.jobs.worker.WorkerSettings


### Terminal 3: Frontend Web

cd apps\web
npm run dev



## Stop Services

# Stop all containers without deleting data
docker compose -f infra/docker/docker-compose.yml down

