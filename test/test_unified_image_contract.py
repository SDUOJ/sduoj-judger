"""Static guards for the single-image scaffold; these do not qualify a runtime."""
import hashlib
from pathlib import Path
import shlex
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UnifiedImageContract(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / 'Dockerfile').read_text()

    def test_original_java_default_is_preserved(self):
        self.assertIn('ENV JAVA_HOME=/opt/java/openjdk17', self.dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/sduoj-judge-entrypoint"]', self.dockerfile)
        command = self.dockerfile[self.dockerfile.index('CMD /wait'):]
        self.assertEqual(hashlib.sha256(command.encode()).hexdigest(),
                         '7b19a0e48264aa98b2d1736dea1ce00f92ecd841257b4c6e5aaa3578470a80a8')
        self.assertNotIn('ENV PYTHONPATH=', self.dockerfile)

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


if __name__ == '__main__':
    unittest.main()
