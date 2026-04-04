---
name: docker
description: Practices for writing Docker and Docker Compose configs — port management, resource sizing, networking, security, and service hygiene.
---

# Docker & Docker Compose Practices

## Use this when
- Adding or modifying `docker-compose.yml` / `compose.yml`
- Writing a new `Dockerfile`
- Debugging container startup failures, port conflicts, or resource issues
- Reviewing Docker-related changes before merging

---

## Port management

### Parameterize every host port — never hardcode
```yaml
# BAD
ports:
  - "8000:8000"

# GOOD
ports:
  - "${PROBE_ENGINE_PORT:-8000}:8000"
```
The `:-default` syntax keeps the file usable without an `.env` file.

### Expose vs publish
- `expose:` — container-to-container only; invisible on the host.
- `ports:` — punches through to `localhost`; use only for services the developer needs to `curl` directly.
If a service only needs to be reached by other containers, use `expose:` and leave out `ports:`.

### Port registry comment
Every host-bound port must appear in a comment block at the top of `compose.yml`:
```yaml
# PORT REGISTRY (host ports this project binds)
# 8000  — api server        (override: API_PORT)
# 9090  — metrics endpoint  (override: METRICS_PORT)
```
Update this comment whenever a port is added, changed, or removed.

### Avoid ports below 1024
Ports <1024 require root on the host and conflict with system services. Start app ports at 8000+, observability at 9000+.

---

## Resource limits

Always set both `limits` and `reservations`. Without limits a runaway container can starve the host; without reservations there are no scheduling guarantees.

```yaml
deploy:
  resources:
    limits:
      cpus: "1.0"     # hard ceiling — CPU throttles at this value
      memory: 256M    # hard ceiling — OOM-kill if exceeded
    reservations:
      cpus: "0.25"    # guaranteed minimum
      memory: 64M
```

Profile with `docker stats` under load; set the limit at ~2× observed peak.

---

## Health checks

Define a health check on every service that other services depend on. Without it, `condition: service_healthy` cannot work.

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 15s   # grace period — don't count failures during startup
```

`start_period` is critical for services that run migrations or take time to initialize.

The `/health` endpoint must:
- Respond in <50ms (no expensive I/O).
- Return HTTP 200 only when truly ready to serve traffic; 503 otherwise.

---

## Startup ordering

Use the long form of `depends_on` — the short form only waits for the container to start, not for the app inside to be ready:

```yaml
service_b:
  depends_on:
    service_a:
      condition: service_healthy
      restart: true   # restart service_b if service_a restarts
```

---

## Restart policies

| Policy | Use for |
|---|---|
| `unless-stopped` | Long-running API servers — survive host reboots |
| `on-failure` | Services that should retry a crash but not be force-restarted |
| `no` | One-shot tasks: migrations, seed scripts |

---

## Networks

Create named networks instead of relying on the single default bridge:

```yaml
networks:
  frontend:
  backend:
    internal: true   # no outbound internet from this network

services:
  proxy:
    networks: [frontend]
  api:
    networks: [frontend, backend]
  db:
    networks: [backend]   # not reachable from the host network
```

Service names are DNS hostnames on shared networks. Inside a container, `localhost` is the container itself — use the service name.

---

## Environment variables

Precedence (highest wins):
1. Shell environment at `docker compose up` time
2. `.env` file in project root
3. `environment:` key in `compose.yml`
4. `ENV` in the Dockerfile

### Tiered `.env` pattern
```
.env.example    # committed — documents every variable with safe placeholders
.env            # gitignored — developer's local overrides
```

Never commit `.env`. Never put secrets in environment variables — they appear in `docker inspect` and CI logs. Mount them as files via Docker Secrets instead.

---

## Dockerfile rules

### Layer order: stable → volatile
```dockerfile
# WRONG — code change busts the dependency cache
COPY . /app
RUN pip install -r requirements.txt

# CORRECT — dependencies cached independently of code changes
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
```

### Always use exec-form CMD
```dockerfile
# GOOD — signals reach the process; clean shutdown
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# BAD — SIGTERM goes to /bin/sh, not the app; 10s kill wait
CMD uvicorn main:app --host 0.0.0.0 --port 8000
```

### apt-get in a single layer, clean up in the same RUN
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
```

### Pin base image tags
```dockerfile
FROM python:3.11-slim   # explicit minor version, not "latest"
```

### Run as non-root
```dockerfile
RUN groupadd --system --gid 1001 appgroup \
    && useradd --system --uid 1001 --gid appgroup --no-create-home appuser
COPY --chown=appuser:appgroup . /app
USER appuser
```

---

## Logging

Set rotation on every service or disk fills silently:

```yaml
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  api:
    logging: *default-logging
```

---

## Dev vs production: override files

```
compose.yml              # base — image names, service definitions, networks
compose.override.yml     # dev — auto-merged; bind mounts, host port exposure, reload
compose.prod.yml         # prod — explicit; resource limits, restart, log rotation
```

`docker compose up` auto-merges `compose.yml` + `compose.override.yml`.  
`docker compose -f compose.yml -f compose.prod.yml up` for production.

---

## Checklist — new service

- [ ] Host port parameterized via `.env`; added to port registry comment
- [ ] `expose:` for internal ports; `ports:` only where host access is needed
- [ ] `deploy.resources.limits` set (CPU + memory)
- [ ] `healthcheck` defined with `start_period`
- [ ] `depends_on` uses `condition: service_healthy` where applicable
- [ ] Runs as non-root user
- [ ] `CMD` in exec form (JSON array)
- [ ] Log rotation configured
- [ ] No secrets in env vars or baked into image
- [ ] Dockerfile layer order: system packages → dependencies → app code
