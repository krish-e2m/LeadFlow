import asyncio
import statistics
import sys
import time
from collections import Counter
from typing import Any

import httpx

# Ensure unbuffered standard output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

API_URL = "http://127.0.0.1:8000/healthz"


async def worker(sem: asyncio.Semaphore, client: httpx.AsyncClient, target_url: str, request_count: int, latencies: list[float], errors: list[str]):
    async with sem:
        for _ in range(request_count):
            t0 = time.perf_counter()
            try:
                resp = await client.get(target_url, timeout=5.0)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if resp.status_code == 200:
                    latencies.append(elapsed_ms)
                else:
                    errors.append(f"HTTP_{resp.status_code}")
            except (httpx.HTTPError, TimeoutError, ConnectionError, OSError) as e:
                errors.append(type(e).__name__)


async def run_concurrency_stage(concurrent_users: int, reqs_per_user: int = 3, target_url: str = API_URL) -> dict[str, Any]:
    print(f"\n--- Testing Concurrency Stage: {concurrent_users} Virtual Users ---", flush=True)
    latencies: list[float] = []
    errors: list[str] = []

    sem = asyncio.Semaphore(concurrent_users)
    limits = httpx.Limits(max_keepalive_connections=min(concurrent_users, 200), max_connections=concurrent_users + 50)
    transport = httpx.AsyncHTTPTransport(limits=limits, retries=0)

    start_time = time.perf_counter()
    async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
        tasks = [
            asyncio.create_task(worker(sem, client, target_url, reqs_per_user, latencies, errors))
            for _ in range(concurrent_users)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
    total_time = time.perf_counter() - start_time

    total_requests = len(latencies) + len(errors)
    rps = total_requests / total_time if total_time > 0 else 0

    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else (max(latencies) if latencies else 0.0)

    result = {
        "virtual_users": concurrent_users,
        "total_requests": total_requests,
        "successful_requests": len(latencies),
        "failed_requests": len(errors),
        "error_rate_pct": (len(errors) / total_requests * 100.0) if total_requests else 0.0,
        "duration_sec": round(total_time, 2),
        "requests_per_sec": round(rps, 1),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
    }

    print(f"  Requests Completed: {result['successful_requests']}/{result['total_requests']}", flush=True)
    print(f"  Throughput:         {result['requests_per_sec']} req/sec (Duration: {result['duration_sec']}s)", flush=True)
    print(f"  Latencies (ms):     p50={result['latency_p50_ms']}ms | p95={result['latency_p95_ms']}ms | p99={result['latency_p99_ms']}ms", flush=True)
    print(f"  Error Rate:         {result['error_rate_pct']:.2f}% ({len(errors)} errors)", flush=True)
    if errors:
        error_sample = Counter(errors).most_common(3)
        print(f"  Top Errors:         {error_sample}", flush=True)

    return result


async def main():
    stages = [10, 50, 100, 250, 500, 1000, 1500]
    results = []

    print("=================================================================", flush=True)
    print("LeadFlow Zero-Cost Scalability & Concurrency Stress Test", flush=True)
    print("Testing local FastAPI performance with gradual VU escalation", flush=True)
    print("=================================================================", flush=True)

    for vus in stages:
        res = await run_concurrency_stage(concurrent_users=vus, reqs_per_user=3, target_url=API_URL)
        results.append(res)
        if res["error_rate_pct"] > 50.0:
            print(f"\n[WARNING] Error rate exceeded 50% at {vus} VUs. Halting escalation to protect local system resources.", flush=True)
            break
        await asyncio.sleep(0.5)

    print("\n======================= Summary Table =======================", flush=True)
    print(f"{'VUs':<6} | {'Reqs':<7} | {'Success':<8} | {'Error %':<8} | {'RPS':<8} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)'}", flush=True)
    print("-" * 75, flush=True)
    for r in results:
        print(f"{r['virtual_users']:<6} | {r['total_requests']:<7} | {r['successful_requests']:<8} | {r['error_rate_pct']:<7.1f}% | {r['requests_per_sec']:<8} | {r['latency_p50_ms']:<9} | {r['latency_p95_ms']:<9} | {r['latency_p99_ms']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
