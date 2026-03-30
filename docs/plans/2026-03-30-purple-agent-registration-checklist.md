# Purple Agent Registration Checklist

This checklist is for registering and first-submitting the current purple agent from this repository to AgentBeats.

It is organized around the practical sequence that matches the current repo:

1. make the purple image reproducible,
2. register the purple agent on AgentBeats,
3. run at least one benchmark submission,
4. only then treat the setup as complete.

## 1. Pre-Registration Readiness

Use this section before touching AgentBeats.

- [ ] Confirm the purple runtime you want to register is the current one in [src/purple_car_bench_agent/server.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/server.py).
- [ ] Confirm the container entrypoint is the purple image defined in [src/purple_car_bench_agent/Dockerfile.car-bench-agent](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/Dockerfile.car-bench-agent).
- [ ] Confirm local CAR evaluation still runs from [scenarios/scenario.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/scenarios/scenario.toml) or another chosen scenario file.
- [ ] Prepare a public Amber manifest URL for the purple agent. The current scaffold lives at [amber-manifest.json5](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/amber-manifest.json5).
- [ ] Decide the public image tag you want to publish, for example `ghcr.io/<owner>/<repo>-purple:<tag>`.
- [ ] Decide the display name you want users to see on AgentBeats.
- [ ] Decide the repository URL you want to attach to the agent page.
- [ ] Decide which env vars the public purple image requires at runtime.

Current repo-specific inputs:

- Purple Dockerfile: [src/purple_car_bench_agent/Dockerfile.car-bench-agent](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/Dockerfile.car-bench-agent)
- Amber manifest scaffold: [amber-manifest.json5](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/amber-manifest.json5)
- Published-image smoke scenario: [scenarios/scenario-ghcr.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/scenarios/scenario-ghcr.toml)
- Local Python-mode scenario: [scenarios/scenario.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/scenarios/scenario.toml)

## 2. Build And Publish The Purple Image

Registering on AgentBeats requires a Docker image reference.

- [ ] Build the purple image for `linux/amd64`.
- [ ] Push the image to a public registry the AgentBeats runner can pull from.
- [ ] Record the exact immutable image reference you want to register.
- [ ] Verify the pushed image can be pulled from a clean environment.
- [ ] Replace the placeholder `program.image` in [amber-manifest.json5](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/amber-manifest.json5) with that public image reference.
- [ ] Push the manifest to a public GitHub repository and copy its raw URL.

Project-specific build path:

```bash
docker build --platform linux/amd64 \
  -f src/purple_car_bench_agent/Dockerfile.car-bench-agent \
  -t ghcr.io/<owner>/<image>:<tag> .

docker push ghcr.io/<owner>/<image>:<tag>
```

Recommended local validation after pushing:

- [ ] Put the published image into [scenarios/scenario-ghcr.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/scenarios/scenario-ghcr.toml).
- [ ] Run a small published-image smoke test before registration-grade submissions.

## 3. Register The Purple Agent On AgentBeats

Do this on the AgentBeats web app once the image exists.

- [ ] Log in to `agentbeats.dev`.
- [ ] Click `Register Agent`.
- [ ] Select `purple`.
- [ ] Fill in the display name.
- [ ] Fill in the Docker image reference.
- [ ] Fill in the Amber Manifest URL.
- [ ] Fill in the repository URL.
- [ ] Fill in any other required metadata shown by the form.
- [ ] Submit the registration.
- [ ] Open the newly created purple agent page.
- [ ] Copy and save the purple `agent ID`.

What to save immediately after registration:

- Purple agent page URL
- Purple agent ID
- Registered image reference
- Amber manifest URL
- Public repo URL

## 4. Decide The First Submission Path

After registration, choose how to create the first public score.

### Option A: Quick Submit

Use this if the target green agent page shows `Quick Submit` as available.

- [ ] Open the green agent page you want to submit against.
- [ ] Click `Quick Submit`.
- [ ] Select your purple agent from the dropdown.
- [ ] Add required secrets such as `OPENAI_API_KEY`.
- [ ] Fill in benchmark config JSON if needed.
- [ ] Review the generated assessment config.
- [ ] Submit.
- [ ] Wait for the GitHub Actions run to finish.
- [ ] Track the PR until the green-agent maintainer merges it.
- [ ] Verify the score appears on the leaderboard afterward.

Use Quick Submit when possible because it avoids manual scenario edits and secret plumbing.

### Option B: Manual Submit

Use this if Quick Submit is unavailable, or if you want local debugging first.

- [ ] Fork the target leaderboard repository.
- [ ] Enable GitHub Actions in your fork if needed.
- [ ] Edit that leaderboard repo's `scenario.toml`.
- [ ] Put the target green agent `agentbeats_id` in `[green_agent]`.
- [ ] Put your purple `agentbeats_id` in `[[participants]]`.
- [ ] Add required env vars using GitHub secrets syntax like `${OPENAI_API_KEY}`.
- [ ] Add the required repository secrets in GitHub.
- [ ] Push the branch and run the workflow.
- [ ] Review the produced results.
- [ ] Open the submission PR.
- [ ] Wait for maintainer merge.

## 5. CAR-Bench First Submission Checklist

This is the most natural first public path for this repo.

- [ ] Run one more current full CAR benchmark locally before public submission.
- [ ] Decide whether to submit the current code as the first baseline, or wait for one more iteration.
- [ ] Register the purple agent before touching leaderboard infrastructure.
- [ ] Use the CAR leaderboard flow described in [README.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/README.md).
- [ ] Prefer a full CAR run over only targeted regression runs for the first public score.

Recommended first-public-sequence:

1. Register purple agent.
2. Publish purple image.
3. Run full CAR baseline with current code.
4. Submit that CAR result.
5. Iterate from there.

## 6. OSWorld Readiness Checklist

OSWorld is useful for track-level validation, but it is not the best first public submission path unless you already have the container flow working.

- [ ] Keep [osworld-leaderboard-main/scenario.local.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/scenario.local.toml) as the local smoke entry.
- [ ] Confirm Docker runtime can pull the OSWorld images.
- [ ] Confirm the green side is reachable and produces a results artifact.
- [ ] Replace the default participant image with your published purple image when ready.
- [ ] Treat the first OSWorld run as a smoke test, not the main public baseline.

Current local references:

- OSWorld leaderboard template: [osworld-leaderboard-main/README.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/README.md)
- OSWorld template scenario: [osworld-leaderboard-main/scenario.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/scenario.toml)
- OSWorld local smoke scenario: [osworld-leaderboard-main/scenario.local.toml](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-leaderboard-main/scenario.local.toml)

## 7. Minimum Metadata Pack To Keep In One Place

Before you start submitting, collect these into one note:

- [ ] Purple agent display name
- [ ] Purple agent ID
- [ ] Purple agent page URL
- [ ] Purple image reference
- [ ] Purple repo URL
- [ ] Target green agent page URL
- [ ] Target green agent ID
- [ ] Leaderboard repo URL
- [ ] Required secrets list
- [ ] Default config JSON or `scenario.toml` values

## 8. Completion Criteria

Do not consider registration complete until all of these are true:

- [ ] The purple agent exists on AgentBeats.
- [ ] The agent page shows the intended public image and repo URL.
- [ ] You have copied the purple agent ID.
- [ ] At least one benchmark submission has completed successfully.
- [ ] You can trace the resulting score from GitHub Actions or Quick Submit back to the purple agent page.

## 9. Recommended Next Actions For This Repo

Given the current project state, the most pragmatic next sequence is:

1. Publish the current purple image.
2. Register the purple agent on AgentBeats.
3. Run one fresh full CAR benchmark with the current code.
4. Submit the CAR result first.
5. Use OSWorld as a second validation path, not the first blocker.

## References

- AgentBeats tutorial: https://docs.agentbeats.dev/tutorial/
- AgentX AgentBeats competition: https://rdi.berkeley.edu/agentx-agentbeats
- Repo registration/submission notes: [README.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/README.md)
