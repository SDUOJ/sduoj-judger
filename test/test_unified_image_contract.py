"""Static guards for the single-image scaffold; these do not qualify a runtime."""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UnifiedImageContract(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / 'Dockerfile').read_text()

    def test_original_java_default_is_preserved(self):
        self.assertIn('ENV JAVA_HOME=/opt/java/openjdk17', self.dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/sduoj-worker-entrypoint"]', self.dockerfile)
        self.assertIn('CMD ["/usr/local/bin/sduoj-start-judger"]', self.dockerfile)
        command = 'CMD ' + (ROOT / 'docker/start-judger.sh').read_text().split('\n', 1)[1]
        self.assertEqual(hashlib.sha256(command.encode()).hexdigest(),
                         '7b19a0e48264aa98b2d1736dea1ce00f92ecd841257b4c6e5aaa3578470a80a8')
        self.assertNotIn('ENV PYTHONPATH=', self.dockerfile)

    def test_unknown_mode_stops_before_starting_any_service(self):
        env = dict(os.environ, SDUOJ_WORKER_MODE='unsupported')
        result = subprocess.run(['sh', str(ROOT / 'docker/worker-entrypoint.sh')],
                                env=env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stdout, '')
        self.assertIn('must be judge or ide', result.stderr)

    def test_ide_rejects_an_unconfigured_identity(self):
        if os.getuid() == 10001 and os.getgid() == 10001:
            self.skipTest('Native image acceptance checks the configured identity')
        env = dict(os.environ, SDUOJ_WORKER_MODE='ide')
        result = subprocess.run(['sh', str(ROOT / 'docker/worker-entrypoint.sh')],
                                env=env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stdout, '')
        self.assertIn('requires UID/GID 10001:10001', result.stderr)

    def test_rootfs_cannot_copy_itself_or_the_application(self):
        frozen = self.dockerfile.index('FROM basic AS judge-runtime')
        final = self.dockerfile.index('FROM judge-runtime AS final')
        application = self.dockerfile.index('COPY sduoj-judger-service/build/libs/')
        self.assertLess(frozen, final)
        self.assertLess(final, application)
        self.assertIn('COPY --from=judge-runtime /opt /opt/judge-rootfs/opt', self.dockerfile)
        self.assertNotIn('COPY --from=final', self.dockerfile)
        self.assertNotIn('fixed-sandbox', self.dockerfile)

    def test_all_local_copy_inputs_are_in_this_repository(self):
        for line in self.dockerfile.splitlines():
            if not line.startswith('COPY ') or '--from=' in line:
                continue
            source = shlex.split(line)[1]
            self.assertTrue((ROOT / source).exists(), source)
            self.assertNotIn('sduoj-deploy/', source)

    def test_upstream_payloads_do_not_replace_system_libraries(self):
        for line in self.dockerfile.splitlines():
            if line.startswith(('COPY --from=ide-tools ', 'COPY --from=ide-debug-tools ')):
                self.assertTrue(shlex.split(line)[-1].startswith('/opt/'), line)
        self.assertIn('ARG IDE_TOOLS_IMAGE\n', self.dockerfile)
        self.assertIn('ARG IDE_DEBUG_TOOLS_IMAGE\n', self.dockerfile)

    def test_arm_sdk_is_only_copied_by_other_architecture_builds(self):
        for role, arg in [('ide-tools', 'IDE_TOOLS_IMAGE'),
                          ('ide-debug-tools', 'IDE_DEBUG_TOOLS_IMAGE')]:
            self.assertIn('FROM --platform=linux/arm64 ${' + arg + '} AS ' + role,
                          self.dockerfile)
        # Build-time executable is the target-native pre-existing JDK only.
        self.assertNotIn('/opt/node/bin/node --', self.dockerfile)
        self.assertNotIn('/opt/nsjail-runtime/nsjail --', self.dockerfile)
        self.assertNotIn('/opt/ide-tools/bin/clangd-wrapper --', self.dockerfile)


if __name__ == '__main__':
    unittest.main()
