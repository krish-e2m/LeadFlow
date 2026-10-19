# Deployment Roadmap

> Companion to `docs/poc.md`. That handbook names Railway as the target platform
> (§2.5, §15, §18, §19.4–19.5) — but Railway no longer has a real free tier, which
> cuts against this project's zero-cost mindset. This doc gives a genuinely $0
> path and documents Railway as the spec-literal paid alternative.
>
> **Decided: the no-credit-card $0 path (§1).** The original plan here was a
> single Oracle Cloud "Always Free" VM, but Oracle requires a credit card on file
> even for its free tier — ruled out once that turned out not to be available.
> The current path (Vercel + Render + Neon + Upstash + GitHub Actions) needs no
> card anywhere. Every file it needs exists and is tested, not just planned:
> - `render.yaml` — Render Blueprint for the API service.
> - `infra/scripts/neon-init.sql` — creates the restricted `leadflow_app` role
>   Neon doesn't give you by default. Ran against a throwaway local Postgres;
>   every statement succeeded and the role genuinely exists afterward.
> - `.github/workflows/worker-burst.yml` — runs the ARQ worker in `--burst`
>   mode on a 5-minute cron instead of needing an always-on host. Verified live,
>   with the normal always-on dev worker stopped so nothing else could claim the
>   job: approved a real lead, ran `arq ... --burst` locally, watched it find the
>   queued job, generate a real draft via OpenRouter (5.89s), log "Auto draft
>   ... written", and exit cleanly.
> - `.github/workflows/ci.yml` — pytest + frontend typecheck/lint/build on every
>   PR and push to main, closing the "no CI" gap from the earlier poc.md audit.
> - `infra/docker/docker-compose.prod.yml` + `Caddyfile.prod` + `init-db.prod.sh`
>   + `apps/web/Dockerfile.prod` — kept as the Oracle-VM path (§1.1), tested
>   (the web Dockerfile was built and ran locally, served real pages with a
>   real HTTP 200), documented in case a card becomes available later; not the
>   current plan. Vercel builds the web app natively on the no-card path — no
>   Dockerfile involved there.
>
> **⚠️ Rotate every API key before using any of this.** Across this session, two
> separate commands accidentally printed real secrets from `.env` into chat —
> Apollo, Firecrawl, Google OAuth client secret, HubSpot access token, Hunter,
> JWT secret key, OpenRouter, PageSpeed, Resend, SerpApi. Treat all of them as
> compromised and regenerate before anything here touches a real deployment.

## 1. Platform recommendation

**Primary recommendation: Vercel (web) + Render (API) + Neon (Postgres) +
Upstash (Redis) + a GitHub Actions scheduled workflow (worker). No credit card
anywhere in this path.**

### Why this combination

- **Genuinely no card required, anywhere.** Each piece was specifically chosen
  because its free tier doesn't ask for payment details at signup — unlike
  Oracle, Fly.io, or AWS/GCP's free tiers, which all do.
- **The worker risk is resolved, not guessed at.** Render's free tier has no
  background-worker service type (web services only), and a naive web-service
  worker would sleep after 15 minutes idle. Instead, the worker runs via ARQ's
  own documented `--burst` mode ("exit once no jobs are found in any queue") on
  a GitHub Actions cron — verified working live this session (see above), with
  no always-on host needed at all.
- **The Redis compatibility question was checked, not assumed.** Serverless
  Redis providers like Upstash don't support every Redis feature (notably Lua
  scripting). Rather than guess, I read ARQ's actual source in this project's
  `.venv`: it uses only `GET`/`SET`/`SETEX`, `ZADD`/`ZSCORE`/`ZRANGEBYSCORE`/
  `ZREM`, and pipelines — no `EVAL`, no Lua, no blocking ops. Fully compatible.
- **Postgres is genuinely persistent**, not a 30-day-then-delete trial (which is
  what Render's own free Postgres is) — Neon's free tier scales to zero when
  idle but never expires your data.

### The one real trade-off, stated plainly

The auto-draft demo earlier in this session completed in ~6 seconds because an
always-on worker was watching Redis continuously. On this architecture, the
worker only runs when the GitHub Actions cron fires — minimum interval is 5
minutes, and free-tier scheduled runs aren't guaranteed to land exactly on time.
**So "approve a lead → draft appears" becomes "within roughly 5–10 minutes,"
not seconds.** Nothing else changes; this only affects that one background
delay. You can trigger a run immediately via the Actions tab's "Run workflow"
button if you don't want to wait for the next scheduled tick.

Also worth knowing: `/readyz`'s `worker: up/down` field reflects a heartbeat
from a persistent worker process. This architecture doesn't have one by
design — `worker: down` in production here is the **expected, permanent**
state, not a sign anything is broken.

### 1.1 If you later get a card: the Oracle VM path

Everything for this still exists and is still tested — `infra/docker/docker-compose.prod.yml`,
`Caddyfile.prod`, `init-db.prod.sh`, the VM walkthrough in §4-Alt.0 below. It's a
simpler architecture (one host, no 5-minute worker delay, auto-draft stays
~6 seconds) and worth revisiting if a card becomes available, but it's not the
current plan.

Why this over everything else (when a card is available):

- **Zero architecture change.** The whole stack is already containerized and
  already proven working in `infra/docker/docker-compose.yml` (postgres, redis,
  api, worker, web) — this entire session's live testing ran on exactly that
  file. Deploying is "copy the repo to the VM, `docker compose up -d`," not a
  redesign.
- **No worker-reliability risk, and no 5-minute delay.** Unlike the GitHub
  Actions burst-mode worker on the primary path (§1), an always-on worker in
  the same stack means the auto-draft flow stays at the ~6 seconds verified
  live this session, not "within several minutes."
- **One host, not five providers.** Simpler to operate day to day, at the cost
  of the manual VM/TLS setup in §4-Alt.0.

**Honest trade-offs of this choice**, stated plainly:

- More hands-on than a PaaS: you provision the VM, point a domain at it, and run
  a reverse proxy for TLS yourself (step-by-step below — it's one config file, not
  deep sysadmin work).
- Oracle's free ARM allocation was reportedly cut in 2026 from 4 OCPU/24GB to 2
  OCPU/12GB on new accounts (sources disagree on exact enforcement) — still far
  more than this stack needs, but worth knowing going in. Sign-up requires a
  credit card on file even though the tier itself never charges it. Popular
  regions sometimes show "out of capacity" for new free instances; if that
  happens, try a different region.
- Oracle can reclaim a VM it judges idle (very low CPU over an extended period)
  with a warning first — a live demo app with any regular traffic is in no danger
  of this, but a VM left completely untouched for weeks could be flagged.
- Single VM = single point of failure. Fine for a POC/demo; not what you'd want
  for a paying-customer production system (see §6 for what changes then).

### 1.2 Another alternative: follow poc.md literally (Railway)

If you'd rather match the handbook exactly and accept a small monthly cost:
Railway's Hobby plan runs ~$5/month (that's a usage credit, not a flat fee — a
constantly-running worker plus API plus Postgres plus Redis will likely exceed it
some months). In exchange you get: Railway understands this repo's multi-service
shape almost natively, managed Postgres/Redis with automatic snapshots (what
poc.md §19.4 assumes), a web dashboard instead of SSH, and noticeably less setup
time. If €5-ish/month is acceptable, this is the lower-effort path and the one
poc.md itself was written around. The provider keys and secrets in §3 still
apply unchanged (same accounts, same values); the platform-specific setup in §4
(no-card path) and §4-Alt (Oracle VM) wouldn't — Railway replaces both with its
own "connect the repo, add Postgres/Redis plugins, set env vars" flow and
handles TLS/reverse-proxying for you.

### 1.3 For later, once this is a real product, not a POC

Worth knowing now even though it's not today's decision: Vercel (web) + a
request-scaling host for the API (Cloud Run / Railway) + managed Postgres (Neon
or Railway) is the natural next step once you have real paying usage and want
auto-scaling and zero sysadmin. Revisit then — building for that scale now would
be solving a problem you don't have yet.

## 2. Pre-flight checklist (do this before touching any platform)

1. **Rotate every API key** — Apollo, Firecrawl, Google OAuth client secret,
   HubSpot access token, Hunter, JWT secret key, OpenRouter, PageSpeed, Resend,
   SerpApi. All of them were printed in plaintext in this chat session (my error,
   twice — see the warning at the top of this file) — treat all as compromised
   and regenerate before any of them touch a real deployment.
2. **Generate a real `JWT_SECRET_KEY`.** Must be ≥32 chars and not the default —
   the app already refuses to boot in production otherwise
   (`app/core/config.py:63-67`). Generate with:
   ```bash
   openssl rand -base64 48
   ```
3. **Decide on a domain** (or subdomain) for Resend sender verification — see the
   Resend conversation earlier in this session for the exact DNS steps. Without
   it, password-reset/notification emails only deliver to your own Resend account
   address, which will confuse real users.
4. **Update the Google OAuth client's authorized redirect URI** in Google Cloud
   Console to the production URL (`https://api.yourdomain.com/api/v1/auth/google/callback`)
   — it's currently registered for `localhost:8000` only, confirmed working in
   this session's live test.
5. **Write down every env var you're about to need** (see §3) so you're not
   hunting for one mid-deploy. Everything currently in your local `.env` is the
   starting list; swap every `localhost` value for the real one.
6. **Clean up test data**: run `seed_design_org.py --cleanup` (scratchpad) so the
   throwaway "Design Review Co" org doesn't ship.

## 3. Production environment variables

Same keys as your working `.env`, with these production-specific changes. The
"Where it's set" column matters more on this path than a single-VM path, since
values live in four different dashboards instead of one `.env` file.

| Variable | Local value | Production value | Where it's set |
|---|---|---|---|
| `ENVIRONMENT` | `development` | `production` | Render (already in `render.yaml`) |
| `JWT_SECRET_KEY` | dev default | generated secret, §2 step 2 | Render + GitHub Actions secret `WORKER_JWT_SECRET_KEY` — **must be the same value in both** |
| `POSTGRES_ADMIN_URL` | local container | Neon's default role connection string | Render + GitHub secret `WORKER_POSTGRES_ADMIN_URL` |
| `DATABASE_URL` / `DATABASE_APP_URL` | local container | `leadflow_app` role connection string (after running `neon-init.sql`) | Render + GitHub secret `WORKER_DATABASE_URL` |
| `REDIS_URL` | local container | Upstash's TCP `rediss://` connection string (not the REST URL/token) | Render + GitHub secret `WORKER_REDIS_URL` |
| `BACKEND_CORS_ORIGINS` | `["http://localhost:3000"]` | `["https://yourapp.vercel.app"]` | Render only |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | `https://leadflow-api.onrender.com/api/v1` | Vercel (build-time env var) |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/...` | `https://leadflow-api.onrender.com/api/v1/auth/google/callback` | Render; also update in Google Cloud Console |
| `GOOGLE_FRONTEND_REDIRECT_URL` | `http://localhost:3000/dashboard` | `https://yourapp.vercel.app/dashboard` | Render |
| `RESEND_FROM_EMAIL` | `onboarding@resend.dev` | an address on your verified domain | Render + GitHub secret `WORKER_RESEND_FROM_EMAIL` |
| `COOKIE_SAMESITE` / cookie secure flag | lenient (local HTTP) | strict, `Secure` (the app already derives this from `ENVIRONMENT`) | automatic |

All other API keys (Hunter, OpenRouter, Firecrawl, SerpApi, PageSpeed, HubSpot,
Google OAuth client) carry over unchanged from your working `.env` — same
free-tier accounts, just entered into Render's dashboard and GitHub's secrets
(as `WORKER_*`) instead of a local file. `render.yaml` lists every key Render
needs; `worker-burst.yml` lists every `WORKER_*` secret GitHub needs — same
values, different places.

## 4. Step-by-step: the no-card $0 path (Vercel + Render + Neon + Upstash + GitHub Actions)

### 4.1 Neon (Postgres)

1. Sign up at [neon.tech](https://neon.tech) — no card required. Create a project.
2. Copy the connection string Neon shows you (the default role, e.g. `neondb_owner`)
   — this becomes `POSTGRES_ADMIN_URL`.
3. Open Neon's **SQL Editor** (or `psql "<connection string>" -f infra/scripts/neon-init.sql`
   from your own machine), first editing `infra/scripts/neon-init.sql` to replace
   `REPLACE_WITH_REAL_PASSWORD` with a real generated password
   (`openssl rand -hex 24`), then run it. This creates the `leadflow_app` role.
4. Build `DATABASE_URL` / `DATABASE_APP_URL` from Neon's host + that new role:
   `postgresql+asyncpg://leadflow_app:<password>@<neon-host>/<db>?ssl=require`.

### 4.2 Upstash (Redis)

1. Sign up at [upstash.com](https://upstash.com) — no card required. Create a
   Redis database (any free-tier region).
2. On the database's details page, copy the **TCP connection string**
   (`rediss://...`) — not the REST URL/token, which ARQ can't use. This becomes
   `REDIS_URL`.

### 4.3 Render (API)

1. Sign up at [render.com](https://render.com) — no card required for the free
   tier (Render may ask for payment verification in some cases per their own
   docs; if prompted, that's Render's flow, not something this guide can avoid).
2. Push this repo to GitHub if you haven't already.
3. Render dashboard → **New → Blueprint** → connect the repo. Render reads
   `render.yaml` at the repo root and proposes the `leadflow-api` service.
4. Before the first deploy completes, fill in every env var marked `sync: false`
   in `render.yaml` — the values from §3 above (your Neon/Upstash connection
   strings, `JWT_SECRET_KEY`, and all the provider API keys from your `.env`).
5. Once deployed, open the service's **Shell** tab (in the Render dashboard) and
   run migrations once:
   ```bash
   cd /app && PYTHONPATH=/app alembic upgrade head
   ```
6. Note the service's URL (`https://leadflow-api.onrender.com` or similar) —
   you need it for Vercel's `NEXT_PUBLIC_API_URL` next.

### 4.4 Vercel (web)

1. Sign up at [vercel.com](https://vercel.com) — no card required for Hobby.
2. **New Project** → import the same GitHub repo.
3. Set **Root Directory** to `apps/web` (this is a monorepo — Vercel needs to
   know which subfolder to build).
4. Add environment variables: `NEXT_PUBLIC_API_URL` (the Render URL from 4.3
   step 6, with `/api/v1` appended) and `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
5. Deploy. Vercel auto-detects Next.js — no other config needed.
6. Go back to Render and set `BACKEND_CORS_ORIGINS` to `["https://<your-vercel-url>"]`,
   and update `GOOGLE_FRONTEND_REDIRECT_URL` to `https://<your-vercel-url>/dashboard`.

### 4.5 GitHub Actions (worker)

1. In the GitHub repo: **Settings → Secrets and variables → Actions → New
   repository secret.** Add one secret per `WORKER_*` name referenced in
   `.github/workflows/worker-burst.yml` — same values as the corresponding
   Render env vars from §3.
2. That's it — the workflow is already committed and will start firing on its
   5-minute schedule. To test it immediately rather than waiting: **Actions tab
   → Worker (burst, scheduled) → Run workflow.**

### 4.6 Google OAuth redirect URI

Update the authorized redirect URI in Google Cloud Console to your real Render
URL: `https://leadflow-api.onrender.com/api/v1/auth/google/callback` — it's
currently registered for `localhost:8000` only, confirmed working in this
session's live test.

## 4-Alt. Oracle Cloud VM — alternate path if you get a card later

The next two subsections cover this path in full, kept intact and tested,
exactly where you'd want them if you revisit §1.1 later. This is a complete
alternative to §4 above, not a continuation of it — the no-card path (§4) is
still the one to follow unless you've decided to switch.

### 4-Alt.0 Walkthrough: creating the VM (only you can do this part)

1. **Sign up at** [cloud.oracle.com](https://cloud.oracle.com) if you don't
   already have an account. Oracle requires a credit card on file for identity
   verification even for the Always Free tier — it's a real card check, not a
   trial that auto-charges; the Always Free resources themselves never bill it.
   Pick a home region close to you; you can't easily change this later.
2. Once logged into the OCI Console: **hamburger menu → Compute → Instances →
   Create Instance.**
3. **Name** it anything (e.g. `leadflow-prod`).
4. Under **Image and shape**, click **Edit**:
   - Image: **Ubuntu** (24.04, or the newest LTS offered).
   - Shape: click **Change shape** → **Ampere** → **VM.Standard.A1.Flex**. This
     is the Always-Free-eligible ARM shape. Set OCPUs/memory to whatever your
     account's current free allocation allows (the console shows the limit;
     reportedly 2 OCPU / 12 GB as of mid-2026, was 4/24 earlier — use whatever
     it offers you, don't request more).
5. Under **Networking**, the defaults (new VCN, new subnet, public IP: yes) are
   fine — leave them unless you already have a VCN you prefer.
6. Under **Add SSH keys**: either let Oracle **generate a key pair for you**
   (download the private key immediately — it's shown once) or **upload your
   own public key** if you already have one you'd rather use.
7. Click **Create**. Provisioning takes a minute or two.
8. If you get an **"Out of host capacity"** error: this is a known Oracle
   Always-Free friction point, not something wrong with your setup. Try a
   different **Availability Domain** in the same region (there's usually a
   dropdown for this), or try again in a few minutes/hours — capacity fluctuates.
9. Once it's **Running**, copy the **Public IP** from the instance details page
   — you'll need it for DNS (§4-Alt.1, step 2 below) and for SSH.
10. **Open the firewall at the OCI level** (separate from the VM's own `ufw`):
    instance details → the subnet's **Security List** → **Add Ingress Rules** →
    add rules for TCP port 80 and TCP port 443 from source `0.0.0.0/0`. Without
    this, Caddy's traffic never reaches the VM even if the VM's own firewall is
    open — OCI blocks at the network level first.
11. **Test SSH access** before moving on:
    ```bash
    ssh -i /path/to/your-private-key.key ubuntu@<the-public-ip>
    ```
    (Default username is `ubuntu` for the Ubuntu image.) If this works, you're
    ready for step 2 below.

### 4-Alt.1 From here on, this is what we already prepared

1. **(Done above.)** VM created, IP in hand, SSH confirmed working.
2. **Point DNS at it.** At your domain registrar, add an A record for
   `yourdomain.com` and `api.yourdomain.com` pointing at the VM's public IP.
3. **Install Docker** on the VM:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```
4. **Copy the repo to the VM** (git clone or `scp`), create the production
   `.env` at the repo root from §3 — must include the new required production
   variables: `POSTGRES_PASSWORD`, `POSTGRES_APP_PASSWORD` (real, strong values —
   not the dev defaults), `DOMAIN`, `NEXT_PUBLIC_API_URL`. Never commit this file.
5. **Run the bootstrap script** — does everything from here (installs Docker if
   missing, builds and starts the stack, waits for Postgres, runs migrations):
   ```bash
   ./infra/scripts/bootstrap-vm.sh
   ```
   (If Docker wasn't already installed, it installs it, tells you to re-login for
   group permissions, and exits — just run the script again after that.)
6. If the VM has its own firewall active (`sudo ufw status`), allow 80/443
   there too — the OCI Security List rule from §4-Alt.0 step 10 is necessary but the
   VM's own `ufw`, if enabled, is a second gate in front of it:
   ```bash
   sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
   ```
   Nothing else needs to be public — Postgres, Redis, api and web only listen on
   the Docker-internal network (`docker-compose.prod.yml` uses `expose:`, not
   `ports:`, for everything except `caddy`).
7. **Smoke test** (see §5.2) before telling anyone the URL.

> **Do not reuse `docker-compose.yml` for production** (it's the dev file — live
> source bind-mounts, `--reload`, ports published straight to the host, the
> dev-password `init-db.sql`). `docker-compose.prod.yml` is a separate,
> self-contained file for exactly this reason.

## 5. Smoke test (run this after every deploy, not just the first)

### 5.1 No-card path (primary)

1. `curl https://<your-service>.onrender.com/readyz` (your real Render URL) —
   expect `{"status":"ready",...}` with `database: connected`,
   `redis: connected`. **`worker: down` is expected here, every time** — this
   field reflects a persistent-worker heartbeat, and on this path the worker
   only exists for a few seconds every 5 minutes (the GitHub Actions burst run).
   A permanent `worker: down` is not a failure signal on this architecture; only
   `database`/`redis` disconnected would be.
2. Load your Vercel URL (`https://<your-app>.vercel.app`) — confirm the landing
   page renders, no console errors.
3. Sign up / log in with a real account — confirms CORS, cookies, and JWT are
   correctly wired between the separate Vercel and Render origins (this is a
   cross-origin setup, unlike the single-domain Oracle path below, so it's worth
   checking explicitly).
4. Run one lead through the full gated chain: approve a lead → confirm it
   queues a job → either wait up to ~5-10 minutes for the next scheduled
   GitHub Actions run, or trigger it immediately (repo's **Actions** tab →
   **Worker (burst, scheduled)** → **Run workflow**) → confirm the run
   succeeded → confirm a draft was written → confirm it synced to HubSpot. This
   proves Render, Vercel, Neon, Upstash, GitHub Actions, OpenRouter, and HubSpot
   are all correctly wired together — the real end-to-end test for this
   architecture. The few-minutes delay here (vs. the ~6s seen in local dev) is
   the one trade-off of this path — see §1.
5. Trigger a password-reset (or welcome) email and confirm it actually lands —
   check Resend's own dashboard **Logs**, not just the API's "success" response.
   If you haven't verified a custom sending domain yet, remember the sandbox
   sender (`onboarding@resend.dev`) can only deliver to the Resend account's own
   verified address.

### 5.2 Oracle VM path (if you revisit it later)

1. `curl https://api.yourdomain.com/readyz` — expect `{"status":"ready",...}`
   with `database: connected`, `redis: connected`, `worker: up` (this path's
   worker is a normal always-on process, so `worker: up` is the expected healthy
   state here — unlike §5.1).
2. Load `https://yourdomain.com` — confirm the landing page renders (gradient,
   mockup, no console errors).
3. Sign up for a real account (or log in with an existing one) — confirms CORS,
   cookies, and JWT are correctly wired for the real domain.
4. Run one lead through the full gated chain end to end, same as verified
   locally this session: approve a lead → confirm auto-draft queues → confirm the
   worker writes a draft → sync to HubSpot → confirm it appears in your HubSpot
   portal. This is the single test that proves API, worker, Redis, Postgres,
   OpenRouter, and HubSpot are all correctly wired together in production.
5. Trigger a password-reset email and confirm it actually lands (same method
   used earlier this session: Resend's own dashboard, not just the API's
   "success" response).

## 6. Monitoring, backups — the parts poc.md asks for that still don't exist

Per the earlier full poc.md audit, these are real gaps regardless of which
platform you pick. CI (poc.md §18) is now done — `.github/workflows/ci.yml`
runs the backend pytest suite plus frontend typecheck/lint/build on every PR
and push to main, catching exactly the kind of regression this session found
and fixed by hand (the Sidebar `logout` bug, the invalid Tailwind classes).
What's still open:

- **Backups** (poc.md §19.4): on the no-card path, Neon's free tier keeps
  **~24 hours of point-in-time recovery** automatically (their history retention
  window scales with plan; free is the shortest) — better than the VM path's
  "nothing unless you set up `pg_dump` yourself," but still short. If the data
  ever matters beyond a demo, either upgrade Neon's plan for longer retention or
  add a scheduled `pg_dump` (e.g. another GitHub Actions cron, same burst-worker
  pattern) writing to a free object-storage bucket. On the VM path, this means a
  cron job running `pg_dump` to a separate location on a schedule — Railway's
  managed Postgres does this automatically, which is the main operational
  convenience you give up by choosing the VM path over Railway.
- **RUNBOOK.md** (poc.md §19.1): doesn't exist yet. Worth writing once you know
  your actual platform, since the runbook should reference real commands for
  your real infrastructure, not generic advice.
- **Alerting** (poc.md §19.2): nothing currently pages you on a 5xx spike, a
  stuck run, or a dead worker heartbeat. For a solo-operator POC, a free uptime
  monitor (e.g., hitting `/readyz` every few minutes and emailing on failure) is
  a reasonable $0 substitute for a real alerting stack.

## 7. Open decision for you

The platform is settled: the no-card path (§1, Vercel + Render + Neon +
Upstash + GitHub Actions). The Oracle VM and Railway paths stay documented as
alternatives but aren't the plan. One thing is genuinely still open:

- **Custom domain — optional, and no longer blocking.** Unlike the Oracle path,
  nothing here *requires* a domain: Render and Vercel both give you a working
  HTTPS URL for free (`*.onrender.com`, `*.vercel.app`), and the app runs fully
  on those. A domain only matters for one thing — Resend sender verification,
  so outbound email can send from `you@yourdomain.com` instead of being capped
  to the sandbox sender (`onboarding@resend.dev`, which can only deliver to
  your own Resend account email until a domain is verified — see §1's
  trade-offs and your earlier questions this session on Resend verification).
  Decide whenever you want: start on the sandbox sender now, add a domain
  later with zero changes to the architecture, or buy one upfront if you'd
  rather not revisit it. Either way, nothing else in this roadmap is blocked
  on it.

Everything else — provider signups, `render.yaml`, `neon-init.sql`,
`worker-burst.yml`, the GitHub Actions secrets — is ready to execute now.
