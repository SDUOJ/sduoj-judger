# sduoj-judger

Fetch, compile and execute submissions in the reviewed sandbox. The integrated release also provides a separate Run consumer and an independently qualified LSP/Debugger Worker.

## Current release contract

The candidate uses ARM64, cgroup-v2 and a Linux kernel with the required Landlock, close_range and pidfd capabilities. A cgroup-v1/old-kernel host cannot gain those features by changing the image or adding Docker privileges. The dev/production shared permission contract and exact acceptance gates are maintained in `sduoj-deploy/docs/COMBINED_RELEASE_20261026.md`.

Formal Judger and Run use private cgroup namespaces, `SYS_ADMIN` and AppArmor unconfined inside non-privileged containers. The image entrypoint is `tini -- sduoj-judge-entrypoint`, which prepares the private cgroup before starting Java. Never bypass that entrypoint. The separate non-root IDE Worker uses a different, narrowly delegated cgroup contract; do not reuse formal Judger capabilities for it.

Use an immutable accepted registry digest. The following is an operator template, not proof that an arbitrary target node is qualified:

```sh
docker run --detach --name sduoj-judger-1 \
  --network "$JUDGE_NETWORK" \
  --cap-add SYS_ADMIN --security-opt apparmor=unconfined --cgroupns=private \
  --cpus=2 --memory=2560m --memory-swap=2560m --pids-limit=1024 \
  --cpuset-cpus="$JUDGE_CPUSET" \
  -e CPU_PER_JUDGER=1 -e NACOS_ADDR="$JUDGE_NACOS_ADDR" -e ACTIVE="$JUDGE_NAMESPACE" \
  "$ACCEPTED_JUDGER_IMAGE"
```

Nacos/RPC secrets, queue endpoints and Snowflake node IDs are environment-specific. Every producer needs a unique node; the Run consumer uses `sduoj.run.worker=true` and a separate queue. Drain existing tasks before replacement. Preserve query/cancel and additive schema during rollback.

## Reproducible builds

Develop directly on the existing `master` branch without additional branches or pull requests. `stable` is the separately maintained OSS line. Agents and subagents follow the same rule.

Locally, first run the server's documented `publishToMavenLocal` tasks with a matching `Versions.sduoj`, then run `./gradlew build --scan` here. In GitHub Actions, publish the server common/interface packages to GitHub Packages before building Judger; record the consumed coordinates and artifact checksums. Use the existing package credentials, without a Deploy key, extra source checkout or composite build. Sandbox comes from the original judging-containers producer and Dockerfile COPY chain.

The final image is verified on its native architecture using `test/runtime-smoke.sh`, including actual Java8/17/21 compilation/execution and trusted helper isolation. New image IDs require their own runtime acceptance; an old image's receipt does not qualify a rebuilt image.

See `ide-worker/README.md` for the independent IDE runtime and candidate/qualified manifest distinction.

Host-network execution VMs must set `SDUOJ_JUDGER_CPU_NODE_INDEX=1` for each Judger/Run container with its own disjoint cpuset. The optional positive index selects a slice inside that container's effective cpuset; unset retains legacy DNS node discovery. Invalid values or slices exceeding the cpuset fail startup. `CPU_PER_JUDGER` still sets the slice width.
