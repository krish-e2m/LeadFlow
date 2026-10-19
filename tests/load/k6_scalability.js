import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// Custom metrics for LeadFlow performance tracking
const errorRate = new Rate('leadflow_errors');
const healthLatency = new Trend('leadflow_health_latency');
const frontendLatency = new Trend('leadflow_frontend_latency');
const successfulRequests = new Counter('leadflow_successful_reqs');

// Gradual ramp-up stages targeting up to 1,500 virtual users (VUs)
export const options = {
  stages: [
    { duration: '10s', target: 10 },    // Stage 1: Baseline smoke test (10 VUs)
    { duration: '20s', target: 50 },    // Stage 2: Light load (50 VUs)
    { duration: '30s', target: 250 },   // Stage 3: Moderate concurrency (250 VUs)
    { duration: '30s', target: 500 },   // Stage 4: High concurrency (500 VUs)
    { duration: '30s', target: 1000 },  // Stage 5: Extreme local stress (1,000 VUs)
    { duration: '30s', target: 1500 },  // Stage 6: Maximum POC target (1,500 VUs)
    { duration: '15s', target: 0 },     // Stage 7: Graceful ramp-down
  ],
  thresholds: {
    // Quality gates: 95% of requests under 500ms, error rate under 5%
    http_req_duration: ['p(95)<500', 'p(99)<1500'],
    leadflow_errors: ['rate<0.05'],
  },
};

const API_BASE = __ENV.API_BASE_URL || 'http://127.0.0.1:8000';
const WEB_BASE = __ENV.WEB_BASE_URL || 'http://localhost:3000';

export default function () {
  // 1. Backend FastAPI Liveness Check
  const healthRes = http.get(`${API_BASE}/healthz`, {
    tags: { name: 'HealthCheck' },
  });
  const healthOk = check(healthRes, {
    'healthz status is 200': (r) => r.status === 200,
    'healthz has correct version': (r) => r.body && r.body.includes('0.1.0'),
  });
  healthLatency.add(healthRes.timings.duration);
  errorRate.add(!healthOk);
  if (healthOk) successfulRequests.add(1);

  // 2. Backend FastAPI Root Endpoint
  const rootRes = http.get(`${API_BASE}/`, {
    tags: { name: 'RootEndpoint' },
  });
  const rootOk = check(rootRes, {
    'root status is 200': (r) => r.status === 200,
  });
  errorRate.add(!rootOk);
  if (rootOk) successfulRequests.add(1);

  // 3. Frontend Next.js Dashboard Page (Simulating user navigation)
  const webRes = http.get(`${WEB_BASE}/`, {
    tags: { name: 'WebHome' },
  });
  const webOk = check(webRes, {
    'web status is 200': (r) => r.status === 200,
  });
  frontendLatency.add(webRes.timings.duration);
  errorRate.add(!webOk);
  if (webOk) successfulRequests.add(1);

  // Random think-time between 0.5s and 1.5s to simulate natural traffic
  sleep(Math.random() * 1.0 + 0.5);
}
