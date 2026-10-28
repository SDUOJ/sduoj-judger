import ctypes
import ctypes.util
import gzip
import hashlib
import io
import json
import pathlib
import tarfile
import tempfile
import unittest

from archive import inspect, zstd_library
from publish import strict_manifest


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def zstd(data):
    lib = ctypes.CDLL(zstd_library())
    lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]; lib.ZSTD_compressBound.restype = ctypes.c_size_t
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    output = ctypes.create_string_buffer(lib.ZSTD_compressBound(len(data)))
    source = ctypes.create_string_buffer(data)
    size = lib.ZSTD_compress(output, len(output), source, len(data), 1)
    return output.raw[:size]


def fixture(destination, compression='gzip', wrong_diff=False, conflict=False):
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode='w') as tar:
        data = b'public bytes' * 300000
        member = tarfile.TarInfo('app/public'); member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
    raw = layer.getvalue()
    packed = gzip.compress(raw) if compression == 'gzip' else zstd(raw) if compression == 'zstd' else raw
    config = json.dumps({'os': 'linux', 'architecture': 'arm64', 'rootfs': {'diff_ids': [sha(b'wrong') if wrong_diff else sha(raw)]}, 'config': {'User': '10001:10001', 'Entrypoint': ['python3', '/manager.py']}}).encode()
    config_desc = {'digest': sha(config), 'size': len(config), 'mediaType': 'application/vnd.oci.image.config.v1+json'}
    layer_desc = {'digest': sha(packed), 'size': len(packed), 'mediaType': 'application/vnd.oci.image.layer.v1.tar' + ('+' + compression if compression != 'raw' else '')}
    manifest = json.dumps({'schemaVersion': 2, 'config': config_desc, 'layers': [layer_desc]}).encode()
    desc = {'digest': sha(manifest), 'size': len(manifest), 'mediaType': 'application/vnd.oci.image.manifest.v1+json'}
    config_name = 'blobs/sha256/' + sha(config)[7:]; layer_name = 'blobs/sha256/' + sha(packed)[7:]
    entries = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}', 'index.json': json.dumps({'manifests': [desc]}).encode(), 'blobs/sha256/' + sha(manifest)[7:]: manifest, config_name: config, layer_name: packed, 'manifest.json': json.dumps([{'Config': 'wrong' if conflict else config_name, 'Layers': [layer_name], 'RepoTags': None}]).encode()}
    with tarfile.open(destination, 'w') as tar:
        for name, data in entries.items():
            member = tarfile.TarInfo(name); member.size = len(data); tar.addfile(member, io.BytesIO(data))
    return sha(config), sha(manifest), sha(raw), sha(packed)


def candidate(component, status):
    source = 'a' * 40; config = 'b' * 64
    workloads = {'judger': ['native-formal','native-run','worker-runtime-junit'], 'ide-worker': ['ide-api','ide-browser','ide-debug-lsp','ide-isolation','ide-capacity','ide-900s','ide-recovery'], 'execution-vm-manager': ['manager-nonroot','manager-boot-assets','manager-feature']}
    common = ['image-config-layer-verification','image-disclosure-review','image-smoke']
    gates = common + workloads[component] + ['combined-release']
    return {'schemaVersion':1,'repository':'SDUOJ/sduoj-judger','component':component,'productSource':source,'platform':'linux/arm64','registryRepository':'registry.cn-beijing.aliyuncs.com/pre-sduoj/sduoj-judger','immutableTag':('staging-' if status=='candidate-staging-only' else '')+component+'-20261029-'+source[:12]+'-'+config[:12]+'-arm64','archiveTags':None,'manifestDigest':'sha256:'+'c'*64,'layers':[],'configSha256':config,'diffIds':['sha256:'+'d'*64],'archiveSha256':'e'*64,'archiveBytes':1,'releaseId':1,'releaseTag':'draft','parts':[{'ordinal':0,'assetId':1,'name':'image.tar.part-000','bytes':1,'sha256':'e'*64}],'qualification':{'status':status,'receipts':[{'gate':g,'status':'pass' if g in common else 'pending','assetId':i+2,'sha256':'f'*64,'productSource':source,'configSha256':config} for i,g in enumerate(gates)]}}


class ArchiveIdentity(unittest.TestCase):
    def test_compressed_blob_and_uncompressed_diffids(self):
        for compression in ('raw','gzip','zstd'):
            with self.subTest(compression=compression), tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory)/'image.tar'; config, manifest, diff, blob = fixture(path, compression)
                identity = inspect(path)
                self.assertEqual(identity['manifestDigest'], manifest)
                self.assertNotEqual(identity['manifestDigest'], 'sha256:'+identity['configSha256'])
                self.assertEqual('sha256:'+identity['configSha256'], config)
                self.assertEqual(identity['layers'][0]['blobSha256'], blob)
                self.assertEqual(identity['diffIds'], [diff])
    def test_wrong_diff_and_shadow_identity_rejected(self):
        for flag in ('wrong_diff','conflict'):
            with tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory)/'image.tar'; fixture(path, **{flag: True})
                with self.assertRaises(ValueError): inspect(path)
    def test_component_qualification_does_not_invent_workload_passes(self):
        for component in ('judger','ide-worker','execution-vm-manager'):
            document = candidate(component, 'candidate-staging-only'); strict_manifest(document)
            document['qualification']['status'] = 'qualified'; document['immutableTag'] = document['immutableTag'].removeprefix('staging-')
            with self.assertRaises(RuntimeError): strict_manifest(document)
            for receipt in document['qualification']['receipts']: receipt['status'] = 'pass'
            strict_manifest(document)
    def test_staging_cannot_use_production_tag_or_missing_disclosure(self):
        document = candidate('judger','candidate-staging-only'); document['immutableTag'] = document['immutableTag'].removeprefix('staging-')
        with self.assertRaises(RuntimeError): strict_manifest(document)
        document = candidate('judger','candidate-staging-only'); document['qualification']['receipts'][1]['status'] = 'pending'
        with self.assertRaises(RuntimeError): strict_manifest(document)

if __name__ == '__main__': unittest.main()
