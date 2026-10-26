import importlib.util
from pathlib import Path


def test_native_supervisor_change_invalidates_debug_artifact_identity():
    spec = importlib.util.spec_from_file_location('prepare_image',
        Path(__file__).resolve().parents[1] / 'scripts/prepare_image.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = module.artifact_digest('sha256:judge', {'adapter.py': 'same'}, 'old-native')
    after = module.artifact_digest('sha256:judge', {'adapter.py': 'same'}, 'fixed-native')
    assert before != after
