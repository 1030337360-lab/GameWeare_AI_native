# GameWeare workspace guidance

After a task that builds or runs Docker images, inspect `docker system df` and clean up unused build cache and images before reporting completion. Stop and remove temporary test containers that are no longer needed. Use `docker builder prune --all --force` and `docker image prune --all --force` only after the final build and verification. Check that the GameWeare services are still running afterward.

Preserve running containers, named volumes, MySQL/Redis/RabbitMQ/MinIO data, generated games, and user-created workspaces. Never use `docker system prune --volumes` or `docker volume prune` as routine cleanup. Report the reclaimed space and any cache rebuild cost when relevant.

Keep project documentation in `README.md` and the five topic files under `docs/` (`architecture.md`, `backend.md`, `frontend-api.md`, `agent.md`, `iteration-roadmap.md`). Update the relevant topic file when implementation changes instead of adding temporary delivery notes or dated plans. Preserve `archive/python-api` as source history.
