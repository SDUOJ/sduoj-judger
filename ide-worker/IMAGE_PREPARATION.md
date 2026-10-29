# Unified image preparation

The main Dockerfile adds upstream SDK payloads to the original Judger runtime.
It preserves the default Java17 command and entrypoint. The SDK images are
build inputs; there is one final Judger image.

This scaffold is not a runnable or qualified IDE release. The nested rootfs
still needs a reviewed loader/system-file whitelist. Trusted bootstrap,
identity helpers, policy and candidate profile installation remain pending.
Official sandbox compilation requires the reviewed separate compile phase and
an actual user-namespace/cgroup capability probe. Failure must remain closed;
do not add outer SYS_ADMIN or restore a historical sandbox binary.

Producer digests, native ABI, nonroot identity/caps, four-language behavior and
full runtime qualification must be verified before deployment. Static checks
are `python3 -m unittest discover -s test -p 'test_unified_image_contract.py'`.
