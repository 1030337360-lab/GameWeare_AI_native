# Yahaha Java backend rebuild

## Scope

Archive the complete Python API under `archive/python-api`; rebuild the backend in `apps/api-java` with Spring Boot. Keep the existing React frontend and retain its API contracts. Use MySQL as the system of record, MinIO for immutable game and upload objects, RabbitMQ for generation jobs, and Redis for ephemeral sessions, cache, and notifications.

## Architecture and consistency rules

1. MySQL owns users, sessions, games, versions, jobs, token accounts, immutable token ledger, run steps, and an outbox. MinIO is object storage, not the billing database.
2. Creating a job and reserving tokens must commit in one MySQL transaction. A unique idempotency key and unique ledger entries prevent duplicate charges.
3. The outbox publisher sends committed jobs to RabbitMQ. Consumers atomically claim a pending job and tolerate duplicate delivery. A dead letter queue retains exhausted failures.
4. A model result is measured and settled once by the billing ledger. Failure refunds unused reservations. A reconciliation job audits outstanding reservations.
5. Login sessions have a unique token hash in MySQL. Redis caches active sessions, while revocation and expiration remain enforceable after cache misses.
6. Game versions are immutable in MinIO; publishing changes the current version in a MySQL transaction after artifacts are uploaded and verified.
7. The frontend's existing REST and SSE paths remain the compatibility contract. New endpoints for wallet and operational checks may be added.

## Task list

| # | Task | domain | acceptance |
|---|---|---|---|
| 1 | Archive Python API and document migration | backend | All Python source, SQL, tests and scripts present under archive |
| 2 | Spring Boot app, dependency and runtime configuration | backend | Compiles and starts with MySQL/RabbitMQ/Redis/MinIO |
| 3 | MySQL Flyway schema | backend | Migration creates business, outbox and token ledger tables |
| 4 | Authentication and session consistency | backend | Register/login/logout/session with concurrency tests |
| 5 | Token account and idempotent billing | backend | Reserve/settle/refund race tests pass |
| 6 | Game catalog, uploads and play | backend | Existing frontend contracts run against MySQL/MinIO |
| 7 | Create jobs, AI generation, outbox and worker | backend | Job dispatch survives retry, records usage, uploads game package |
| 8 | Maintenance, profiles and advanced agent modes | backend | Legacy endpoints have real implementations or explicit migration coverage |
| 9 | Docker Compose and end-to-end verification | backend | One-command stack and tested create/publish/play path |
| 10 | Frontend compatibility adjustments | frontend | Existing React pages call Java API successfully |

## Working evidence

The archived Python API is the behavior reference; this plan is not a claim that the Java implementation is complete. Track individual acceptance with tests and runtime checks.
