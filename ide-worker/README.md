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
