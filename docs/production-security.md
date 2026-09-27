# Production credentials and AI network egress

`docker-compose.prod.yml` is a separate production example. It has no default credentials and does not publish MySQL, Redis, RabbitMQ, or MinIO ports. The API and web ports bind to loopback; put a TLS reverse proxy in front of them. Provide required variables through a deployment secret manager or a local env file that is excluded by `.gitignore`.

Required variables: `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `RABBITMQ_PASSWORD`, `REDIS_PASSWORD`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `AI_CONFIG_SECRET`, `WEB_ORIGIN`, `API_PUBLIC_URL`, `MINIO_PUBLIC_BASE_URL`, and `LLM_ALLOWED_HOSTS`. Use independent random secrets. `AI_CONFIG_SECRET` must be at least 32 characters and must be backed up securely: changing it makes previously encrypted user AI keys unreadable until reconfigured.

Example startup, after loading variables in the shell or supplying an ignored env file:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

The `prod` Spring profile checks credentials and refuses known development defaults, a non-HTTPS public origin, an empty AI host allowlist, or `LLM_ALLOW_PRIVATE_ENDPOINTS=true`. Set `LLM_ALLOWED_HOSTS` to comma-separated exact DNS names, for example `api.openai.com`; wildcard domains and URL paths are rejected. User-supplied AI provider URLs must use HTTPS and an allowlisted host. On every outbound request, the HTTP client resolves the host, rejects private, loopback, link-local and special-use addresses, and connects to exactly the checked addresses. Redirects and ambient HTTP proxies are disabled. This closes the previous check-then-re-resolve window in the AI connector and leaves local Mock LLM testing available only through the development compose switch.

These controls apply to the AI connector. A deployment that needs a hard network boundary should also enforce outbound firewall or proxy rules for the API container, restricting TCP 443 to approved provider destinations while allowing only the internal MySQL, Redis, RabbitMQ and MinIO services. Docker Compose alone does not provide a destination-domain firewall. Verify the actual provider IP ranges and provider changes with your infrastructure policy before enabling that boundary.

Back up the MySQL and MinIO volumes together, keep the secret manager separate from backups, and test restore before opening the service to users. Rotate service credentials with a coordinated restart. Do not commit production env files or print a resolved `docker compose config` in CI logs because it contains secret values.
