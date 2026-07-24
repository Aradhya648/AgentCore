# Contributing to AgentCore

Thank you for considering a contribution. [`Lawofall/AgentCore`](https://github.com/Lawofall/AgentCore) is the single product repository (see README · Open source). While the repo is still private, development continues here; after it goes Public, Issues and PRs land on the same URL.

## Ways to help

- Bug reports and feature ideas via GitHub Issues (once Public—or with collaborator access today)
- Pull requests for behavior and docs changes; start with focused diffs
- Security reports via [SECURITY.md](./SECURITY.md) — not public Issues

Large cross-cutting changes: please open an Issue first.

## Development setup

Follow [`docs/02-架构/本地开发.md`](./docs/02-架构/本地开发.md).

Minimum for backend work:

```bash
docker compose -f deploy/docker-compose.dev.yml up -d
cd apps/server && uv sync
```

## Pull requests

1. Keep changes focused; prefer small PRs with a clear problem statement.
2. Add or update tests for behavior changes in `apps/server`.
3. Do not commit secrets, local `.env`, `data/`, or scratch `tmp_*` / `_tmp_*` files.
4. Do not commit under `.cursor/` — AI editor rules stay private to the product repo.
5. Match existing code style; run the relevant server tests before submitting.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](./LICENSE).
