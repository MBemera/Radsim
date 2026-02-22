# Production Readiness Protocol v1.0.0

**Purpose:** Eliminate "Works on My Machine" syndrome and prevent deployment failures when moving from local development to production.

**When to apply:** Before ANY code is deployed, hosted, or handed off for production use. This includes Python scripts on a VPS, containerized services, web apps, scheduled automations, and API backends.

---

## How to Use This Skill

When writing or reviewing code destined for production, work through each category below as a checklist. Not every check applies to every project — use judgment based on scale and complexity.

**Minimum required sections:**
- Environment & Configuration
- Deployment & Operations
- External Service Resilience

**For small scripts** (single-file automations, cron jobs): Focus on env var isolation, dependency locking, structured logging, health checks, and secret management.

**For full services** (APIs, dashboards, multi-container apps): Apply the complete protocol.

---

## 1. Environment & Configuration Consistency

**Objective:** Eliminate configuration drift between dev and prod.

### Containerization
- [ ] All services defined via Dockerfile / docker-compose.yml
- [ ] OS, libraries, and runtime versions identical across dev, staging, and prod
- [ ] If not containerized: document exact Python/Node version and OS dependencies in README or setup script

### Strict Environment Variable Isolation
- [ ] **Zero config values hardcoded in source code**
- [ ] Use `.env` files locally (`.env` in `.gitignore`)
- [ ] Use Secrets Managers for production (AWS Secrets Manager, Vault, or systemd environment files)
- [ ] **Application must fail fast on startup if required env vars are missing** — never silently fall back to defaults for critical config like API keys or DB URLs

### Dependency Locking
- [ ] Commit lock files: `requirements.txt` with pinned versions (or `poetry.lock`), `package-lock.json`, `go.sum`
- [ ] Never use unpinned dependencies (`>=`, `*`) in production manifests
- [ ] Run `pip freeze` or equivalent to capture exact versions before deployment

---

## 2. Data Integrity & Performance

**Objective:** Prevent failures from messy data, volume spikes, and unoptimized queries.

### Data Parity Testing
- [ ] Dev environment uses sanitized/anonymized subset of production-scale data
- [ ] Never rely solely on clean "happy path" seed data
- [ ] Test with edge cases: empty fields, Unicode, massive records, duplicates

### Query Optimization
- [ ] Run `EXPLAIN ANALYZE` on all new queries against production-sized datasets
- [ ] Implement caching (Redis or equivalent) for high-read, low-write data
- [ ] Index frequently queried columns

### Concurrency Testing
- [ ] For services handling multiple users: load test with tools like `k6`, `JMeter`, or `locust`
- [ ] Identify deadlocks, race conditions, and connection pool exhaustion
- [ ] For single-user automations: test with realistic data volumes and timing

---

## 3. Infrastructure & Security

**Objective:** Address network restrictions, resource limits, and protocol mismatches.

### Infrastructure as Code
- [ ] Define VPCs, firewalls, security groups via Terraform/CloudFormation where applicable
- [ ] For VPS deployments: document firewall rules (`ufw`, `iptables`) and SSH hardening in a setup script
- [ ] Local dev should mimic production network restrictions where possible

### Protocol Parity (SSL/HTTPS)
- [ ] Use local SSL during development (`mkcert`, Traefik) to catch mixed-content and secure cookie issues
- [ ] Verify certificate chain is valid before go-live
- [ ] For API services: enforce HTTPS-only in production

### Resource Limits
- [ ] Define CPU and memory limits in container orchestration manifests (Kubernetes, ECS, Docker Compose)
- [ ] For VPS: set up swap, monitor memory usage, configure OOM killer behavior
- [ ] Prevent unbounded memory growth in long-running processes

---

## 4. Deployment & Operations

**Objective:** Prevent migration failures and ensure system observability.

### Automated Migration Strategy
- [ ] Database migrations must be non-destructive and backward compatible
- [ ] Test both `up` and `down` migrations in staging before production
- [ ] Never run untested migrations directly against prod

### Centralized Observability
- [ ] **Structured logging in JSON format** with correlation IDs
- [ ] Ship logs to a central aggregator (even if it's just a log file with `logrotate` on a VPS)
- [ ] **Never rely solely on `print()` statements** or local console output in production
- [ ] Set up alerts for error rate spikes and resource exhaustion

### Health Checks
- [ ] Implement liveness and readiness probes
- [ ] Application must not accept traffic until dependent services (DB, cache, external APIs) are confirmed reachable
- [ ] For cron/scheduled tasks: log success/failure status after each run

---

## 5. External Service Resilience

**Objective:** Handle API failures, rate limits, and credential management gracefully.

### Fault Tolerance Patterns
- [ ] **Exponential backoff** on all external API calls
- [ ] **Circuit breakers** to prevent cascading failures when a dependency is down
- [ ] **Timeout configuration** on every outbound HTTP request — never use default infinite timeouts
- [ ] **Graceful degradation**: define what happens when an external service is unavailable

### Secret Rotation Policy
- [ ] Automated checks for token/certificate expiration
- [ ] **Secrets injected at runtime**, never baked into build artifacts or Docker images
- [ ] Rotate API keys on a schedule; alert when expiration is approaching
- [ ] Store secrets in environment variables or dedicated secret stores, **never in source code or config files committed to git**

---

## Quick Reference Checklist

Use this for a fast pre-deployment scan:

```
[ ] No hardcoded config — all env vars, failing fast if missing
[ ] Dependencies pinned with lock file committed
[ ] Structured logging (not just print statements)
[ ] Error handling with retries and backoff on external calls
[ ] Secrets not in code, not in Docker image, injected at runtime
[ ] Health check endpoint or startup validation
[ ] Resource limits defined (memory, CPU, timeouts)
[ ] Tested with realistic data volume
[ ] SSL/HTTPS configured for production
[ ] Monitoring/alerting in place for errors and resource usage
```

---

## Scaling the Protocol

| Project Scale | Apply These Sections |
|---------------|----------------------|
| Single script / cron job | Env vars, dependency lock, logging, secret management, error handling |
| API / web service | All of the above + health checks, containerization, SSL, load testing |
| Multi-service system | Full protocol including IaC, migration strategy, centralized observability |
