# SDUOJ IDE execution worker

Python execution core, owned by the Judger repository. Gateway owns the HTTP
API, authenticated logical sessions and source revisions. This process exposes
only an internal readiness/metrics HTTP endpoint and never starts AutoLab,
SQLAlchemy or AI workers.

The default `python -m sduoj_ide_worker --role all` reads `ide-worker.yml`
from the existing Nacos namespace and starts four bounded LSP components and
one Debug runtime. It registers one `ide-worker` service instance only after
all five components acquire their Redis leases. Config changes require a
controlled restart; debugger memory is never migrated or replayed. See
`sduoj-deploy/docs/IDE_UNIFIED_WORKER_RELEASE.md` for the independent dev lab,
eight-replica ARM candidate, cgroup-v1 accounting, and release gates.

`python -m sduoj_ide_worker --role lsp --language cpp` consumes the language
entry queue and its own hot-session queue. `--role debug` consumes its own
reliable command queue and independent priority control queue.

The extracted analyzer/debugger core retains its original package names for
sandbox runner compatibility. Its provenance is in `extraction.json`; worker
specific source changes are reviewed in this repository. Legacy AutoLab files
remain only for rollback during migration and are not imported by this worker.

The Redis protocol is versioned JSON. Source and input are never logged.
Docker resource limits, language process counts and debug admission quotas are
explicit. Historical toolchain tests do not qualify this new transport.

Debug CPU accounting uses two separate cgroups. The jail contains the compiler,
namespace supervisor, debugger adapters and user target; its reported CPU seconds
are their aggregate lifetime usage. The jail is capped at one CPU core, its
memory and PID limits remain enforced, and every running generation has the
existing authoritative `runLimitSeconds` wall deadline. Hard session lifetime,
idle expiry, heartbeat loss and verified whole-tree cleanup remain independent.
Compilation also keeps its existing native compiler CPU/wall limits. Aggregate
jail CPU is a resource statistic, not an independent target-only CPU measurement
and not the guardian's control budget.

The profile's `cpu_seconds` bounds only the trusted external guardian's cumulative
CPU in its own reserved cgroup. Exceeding it emits a typed infrastructure event
and terminates with `DEBUG_GUARDIAN_CPU_LIMIT`, followed by the same verified jail
cleanup. A target loop cannot consume this control budget or replace the reason
with a subsequent EOF. No browser field controls this value. This fixes the
fixed 30-second aggregate cutoff that preempted Python/Java run wall deadlines.

`Dockerfile.r8-control` copies only the three external control files onto an exact
R7 base. It leaves `/opt/judge-rootfs`, native compiler/sandbox, templates, adapters
and artifact inventory unchanged. A new image ID requires fresh candidate
qualification and two complete four-language rounds, permission/native isolation
and capacity checks. Historical R7 receipts are provenance, not R8 acceptance.
