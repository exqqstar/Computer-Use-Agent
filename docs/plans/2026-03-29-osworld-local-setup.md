# OSWorld Local Setup Status

## Goal

Get the local [osworld-leaderboard-main](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main) repository into a state where we can run a local OSWorld leaderboard assessment, or clearly identify the remaining blockers.

## What Was Missing

Before setup, the local machine was blocked by:

- no `docker`
- no Docker runtime
- no working `docker compose`
- stale Docker Desktop credential config in `~/.docker/config.json`
- `generate_compose.py` hard-required `tomli-w` and `requests`
- no local `output/` directory in the leaderboard repo

## What Was Configured

### Python-side setup

- Patched [generate_compose.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/generate_compose.py) so:
  - `requests` is only required when `agentbeats_id` resolution is actually used
  - `tomli-w` is no longer required for local scenario generation
- Verified local generation works:
  - [docker-compose.yml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/docker-compose.yml)
  - [a2a-scenario.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/a2a-scenario.toml)

### Runtime setup

- Installed:
  - `docker`
  - `docker-compose`
  - `colima`
  - `qemu`
- Started a local Colima runtime with:
  - VZ backend
  - Rosetta enabled
- Switched Docker context to `colima`
- Replaced stale Docker Desktop config with a minimal Colima-compatible `~/.docker/config.json`
- Verified:
  - `docker --version`
  - `docker compose version`
  - `docker info`

### Repo-local setup

- Created [scenario.local.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/scenario.local.toml) for smaller local smoke tests
- Created [output](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/output)

## Remaining Work

The remaining work is not environment misconfiguration anymore. It is mostly runtime heaviness:

- the required images are large and take time to pull
- the default participant image is still `ghcr.io/rdi-foundation/osworld-purple:latest`, not our own purple agent
- we still need to decide whether the first real check should be:
  - a smoke run with the default OSWorld purple image
  - or a run against our own purple image once that image exists

## Recommended Next Step

1. Finish the initial image pull.
2. Generate compose from [scenario.local.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/scenario.local.toml).
3. Run a small local smoke test first.
4. After that, swap in our own purple agent image and use the same small scenario for iteration.
