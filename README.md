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

The CI workflows pin matching sandbox and private server source commits. Configure a dedicated read-only deploy key on the private server repository and store its private key in the Judger `SDUOJ_SERVER_SOURCE_KEY` Actions secret for the pinned checkout; fork workflows without that credential cannot build the private dependency and fail explicitly. Publish the pinned source commits before dispatching the dependent image build. Never silently fall back to mutable SNAPSHOT interfaces.

Local build uses `./gradlew -PsduojServerSource=/absolute/path/to/matching-server build`. The final image is verified on its native architecture using `test/runtime-smoke.sh`, including actual Java8/17/21 compilation/execution and trusted helper isolation. New image IDs require their own runtime acceptance; an old image's receipt does not qualify a rebuilt image.

See `ide-worker/README.md` for the independent IDE runtime and candidate/qualified manifest distinction.
