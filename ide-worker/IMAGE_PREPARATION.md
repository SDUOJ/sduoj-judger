# Unified image preparation

The main Dockerfile adds upstream SDK payloads to the original Judger runtime.
It preserves the default Java17 command and entrypoint. The SDK images are
build inputs; there is one final Judger image.

The SDK producer inputs are explicitly ARM64 on both final-image build
platforms. The amd64 formal/Run build copies but never executes their payloads.
IDE mode must reject amd64 until it has its own SDK and runtime qualification;
copying ARM64 files does not establish amd64 IDE support.

The nested rootfs
copies the original sandbox runtime paths from the stage before application
installation. The bootstrap and identity helpers are built from source or the
original distribution packages. An inventory binds runtime bytes and image
symlinks without treating the inventory SHA as a registry digest. Generated
profiles remain unverified until the exact release artifacts pass acceptance.

IDE Debug requires cgroup v2 and one session grant across compile, handoff and
runtime. The official sandbox compiles in its own nested namespaces and native
cgroup. After that compiler tree exits, the guardian moves the trusted setup
supervisor to the handoff branch. It freezes an allowlisted artifact copy,
reaps the setup namespace, and starts a fresh runtime with a read-only/noexec
artifact bind and a separate executable tmpfs. Pinned launcher identities and
recursive drain checks govern cleanup; an unconfirmed cleanup retains its grant.
The setup and runtime filters have separate hashes. Outer SYS_ADMIN and a
historical sandbox binary are not fallback routes.

Producer digests, native ABI, nonroot identity/caps, four-language behavior and
full API, isolation, recovery and capacity qualification must pass on the final
published image before deployment. Local native component tests do not qualify
another image or environment. Static checks
are `python3 -m unittest discover -s test -p 'test_unified_image_contract.py'`.
