import asyncio
import time
import statistics
import uuid
import httpx
from sqlalchemy import text, select
from app.db.session import AsyncSessionLocal, tenant_session
from app.models.lead import Lead
from app.models.user import User
from app.security.jwt import create_access_token
from app.security.session_store import get_redis_client

async def run_redis_benchmarks():
    print("--- 1. Redis Performance Baseline ---")
    r = get_redis_client()
    latencies = []
    for _ in range(100):
        t0 = time.perf_counter()
        await r.ping()
        latencies.append((time.perf_counter() - t0) * 1000)
    
    print(f"Redis PING (N=100): Median={statistics.median(latencies):.2f}ms, P95={sorted(latencies)[int(0.95 * len(latencies))]:.2f}ms, Min={min(latencies):.2f}ms, Max={max(latencies):.2f}ms")

    # Counter benchmark (INCR/DECR)
    test_key = f"perf:test:{uuid.uuid4()}"
    ctr_latencies = []
    for _ in range(100):
        t0 = time.perf_counter()
        await r.incr(test_key)
        ctr_latencies.append((time.perf_counter() - t0) * 1000)
    await r.delete(test_key)
    print(f"Redis INCR (N=100): Median={statistics.median(ctr_latencies):.2f}ms, P95={sorted(ctr_latencies)[int(0.95 * len(ctr_latencies))]:.2f}ms")


async def run_db_benchmarks():
    print("\n--- 2. PostgreSQL Query Performance Baseline ---")
    
    # Simple ping
    latencies = []
    async with AsyncSessionLocal() as session:
        for _ in range(50):
            t0 = time.perf_counter()
            await session.execute(text("SELECT 1"))
            latencies.append((time.perf_counter() - t0) * 1000)
    print(f"PostgreSQL SELECT 1 (N=50): Median={statistics.median(latencies):.2f}ms, P95={sorted(latencies)[int(0.95 * len(latencies))]:.2f}ms")

    # Fetch a real org and lead
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT org_id FROM leads WHERE org_id IS NOT NULL LIMIT 1"))
        org_id = res.scalar()

    if org_id:
        # Tenant-scoped lead list
        list_latencies = []
        async with tenant_session(org_id) as session:
            for _ in range(50):
                t0 = time.perf_counter()
                await session.execute(text("SELECT id, domain, company_name, pipeline_status, score_band, approval_status, created_at FROM leads WHERE org_id = :org_id ORDER BY created_at DESC LIMIT 50"), {"org_id": org_id})
                list_latencies.append((time.perf_counter() - t0) * 1000)
        print(f"Tenant Leads List Query (N=50): Median={statistics.median(list_latencies):.2f}ms, P95={sorted(list_latencies)[int(0.95 * len(list_latencies))]:.2f}ms")

        # EXPLAIN ANALYZE on Lead query
        async with tenant_session(org_id) as session:
            explain_res = await session.execute(text("EXPLAIN (ANALYZE, BUFFERS) SELECT id, domain, company_name, pipeline_status, score_band, approval_status, created_at FROM leads WHERE org_id = :org_id ORDER BY created_at DESC LIMIT 50"), {"org_id": org_id})
            print("\nEXPLAIN ANALYZE leads query:")
            for line in explain_res.fetchall():
                print(f"  {line[0]}")


async def run_http_benchmarks():
    print("\n--- 3. HTTP Endpoints Baseline ---")
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Unauthenticated health check
        health_lats = []
        for _ in range(50):
            t0 = time.perf_counter()
            res = await client.get("/healthz")
            assert res.status_code == 200
            health_lats.append((time.perf_counter() - t0) * 1000)
        print(f"GET /healthz (N=50): Median={statistics.median(health_lats):.2f}ms, P95={sorted(health_lats)[int(0.95 * len(health_lats))]:.2f}ms")

        # Authenticated endpoint
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT set_config('leadflow.is_super_admin', 'true', true)"))
            user = (await session.execute(select(User).limit(1))).scalars().first()
            if user:
                token = create_access_token(
                    subject=str(user.id),
                    org_id=str(user.org_id) if user.org_id else None,
                    role=user.role.value,
                    email=user.email,
                )
                headers = {"Authorization": f"Bearer {token}"}
                me_lats = []
                for _ in range(50):
                    t0 = time.perf_counter()
                    res = await client.get("/api/v1/auth/me", headers=headers)
                    assert res.status_code == 200
                    me_lats.append((time.perf_counter() - t0) * 1000)
                print(f"GET /api/v1/auth/me (N=50): Median={statistics.median(me_lats):.2f}ms, P95={sorted(me_lats)[int(0.95 * len(me_lats))]:.2f}ms")

                leads_lats = []
                for _ in range(50):
                    t0 = time.perf_counter()
                    res = await client.get("/api/v1/leads?limit=50", headers=headers)
                    assert res.status_code == 200
                    leads_lats.append((time.perf_counter() - t0) * 1000)
                print(f"GET /api/v1/leads (N=50): Median={statistics.median(leads_lats):.2f}ms, P95={sorted(leads_lats)[int(0.95 * len(leads_lats))]:.2f}ms")

async def main():
    await run_redis_benchmarks()
    await run_db_benchmarks()
    await run_http_benchmarks()

if __name__ == "__main__":
    asyncio.run(main())
