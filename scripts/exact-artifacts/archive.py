"""Read-only Docker-save/OCI archive identity validation; never loads or extracts an image."""
import ctypes
import ctypes.util
import gzip
import hashlib
import json
import pathlib
import tarfile


def require(value, message):
    if not value:
        raise ValueError(message)


def sha_stream(source):
    result = hashlib.sha256()
    size = 0
    for block in iter(lambda: source.read(8 * 1024**2), b''):
        result.update(block)
        size += len(block)
    return 'sha256:' + result.hexdigest(), size


def zstd_library():
    return ctypes.util.find_library('zstd') or next((str(p) for p in (pathlib.Path('/opt/homebrew/opt/zstd/lib/libzstd.dylib'), pathlib.Path('/usr/local/lib/libzstd.dylib')) if p.exists()), None)


def zstd_hash(source):
    library = zstd_library()
    require(library, 'zstd layer requires system libzstd; no identity fallback')
    lib = ctypes.CDLL(library)
    class Buffer(ctypes.Structure):
        _fields_ = [('src', ctypes.c_void_p), ('size', ctypes.c_size_t), ('pos', ctypes.c_size_t)]
    lib.ZSTD_createDStream.restype = ctypes.c_void_p
    lib.ZSTD_initDStream.argtypes = [ctypes.c_void_p]
    lib.ZSTD_initDStream.restype = ctypes.c_size_t
    lib.ZSTD_decompressStream.argtypes = [ctypes.c_void_p, ctypes.POINTER(Buffer), ctypes.POINTER(Buffer)]
    lib.ZSTD_decompressStream.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    lib.ZSTD_freeDStream.argtypes = [ctypes.c_void_p]
    ctx = lib.ZSTD_createDStream()
    require(ctx, 'Cannot allocate zstd decoder')
    digest, size, remaining = hashlib.sha256(), 0, 1
    try:
        require(not lib.ZSTD_isError(lib.ZSTD_initDStream(ctx)), 'Cannot initialize zstd decoder')
        for block in iter(lambda: source.read(1024**2), b''):
            data = ctypes.create_string_buffer(block)
            incoming = Buffer(ctypes.cast(data, ctypes.c_void_p), len(block), 0)
            while incoming.pos < incoming.size:
                output = ctypes.create_string_buffer(1024**2)
                outgoing = Buffer(ctypes.cast(output, ctypes.c_void_p), len(output), 0)
                remaining = lib.ZSTD_decompressStream(ctx, ctypes.byref(outgoing), ctypes.byref(incoming))
                require(not lib.ZSTD_isError(remaining), 'Invalid zstd layer')
                digest.update(output.raw[:outgoing.pos]); size += outgoing.pos
        require(remaining == 0, 'Truncated zstd layer')
    finally:
        lib.ZSTD_freeDStream(ctx)
    return 'sha256:' + digest.hexdigest(), size


def inspect(archive):
    archive = pathlib.Path(archive)
    with archive.open('rb') as source:
        archive_digest, archive_bytes = sha_stream(source)
    with tarfile.open(archive, 'r:') as tar:
        names = {}
        for item in tar.getmembers():
            name = item.name.removeprefix('./')
            require(not name.startswith('/') and '..' not in pathlib.PurePosixPath(name).parts, 'Unsafe archive path')
            require(item.isfile() or item.isdir(), 'Unsafe archive links/devices')
            require(name not in names, 'Duplicate archive path')
            names[name] = item
        def stream(name):
            require(name in names and names[name].isfile(), 'Missing archive member')
            return tar.extractfile(names[name])
        def read(name):
            require(names[name].size < 16 * 1024**2, 'Oversized metadata')
            return stream(name).read()
        def blob(desc):
            require(desc['digest'].startswith('sha256:'), 'Unsupported digest')
            name = 'blobs/sha256/' + desc['digest'][7:]
            digest, size = sha_stream(stream(name))
            require(digest == desc['digest'] and size == desc['size'], 'OCI descriptor bytes mismatch')
            return name
        oci = 'index.json' in names and 'oci-layout' in names
        child_digest = None
        if oci:
            require(json.loads(read('oci-layout'))['imageLayoutVersion'] == '1.0.0', 'OCI layout mismatch')
            index = json.loads(read('index.json'))
            descriptors = index['manifests']
            require(len(descriptors) == 1, 'One platform required')
            desc = descriptors[0]
            while 'index' in desc.get('mediaType', '') or 'manifest.list' in desc.get('mediaType', ''):
                nested = json.loads(read(blob(desc)))
                require(len(nested['manifests']) == 1, 'Multiarch/attestation index not accepted')
                desc = nested['manifests'][0]
            manifest_bytes = read(blob(desc)); manifest = json.loads(manifest_bytes)
            child_digest = desc['digest']
            config_name = blob(manifest['config'])
            layers = [(blob(x), x['mediaType']) for x in manifest['layers']]
            tags = None
            if 'manifest.json' in names:
                compatibility = json.loads(read('manifest.json'))
                require(len(compatibility) == 1, 'Docker compatibility manifest count')
                require(compatibility[0]['Config'] == config_name and compatibility[0]['Layers'] == [x[0] for x in layers], 'Conflicting OCI/Docker identities')
                tags = compatibility[0].get('RepoTags')
        else:
            entries = json.loads(read('manifest.json'))
            require(len(entries) == 1, 'One Docker-save image required')
            entry = entries[0]; config_name = entry['Config']; tags = entry.get('RepoTags')
            layers = [(x, 'application/vnd.oci.image.layer.v1.tar') for x in entry['Layers']]
        config_bytes = read(config_name); config = json.loads(config_bytes)
        diffs = config['rootfs']['diff_ids']
        require(len(layers) == len(diffs), 'Layer count mismatch')
        records = []
        for (name, media), expected in zip(layers, diffs):
            compressed_sha, compressed_size = sha_stream(stream(name))
            if media.endswith('+gzip') or media.endswith('.gzip'):
                with gzip.GzipFile(fileobj=stream(name)) as decoded:
                    diff, unpacked = sha_stream(decoded)
            elif media.endswith('+zstd'):
                diff, unpacked = zstd_hash(stream(name))
            else:
                require(media.endswith('.tar'), 'Unsupported layer compression')
                diff, unpacked = compressed_sha, compressed_size
            require(diff == expected, 'Uncompressed layer diffID mismatch')
            records.append({'mediaType': media, 'blobSha256': compressed_sha, 'blobBytes': compressed_size, 'diffId': diff, 'uncompressedBytes': unpacked})
        return {'archiveSha256': archive_digest[7:], 'archiveBytes': archive_bytes, 'format': 'oci' if oci else 'docker-save', 'manifestDigest': child_digest, 'configSha256': hashlib.sha256(config_bytes).hexdigest(), 'platform': config['os'] + '/' + config['architecture'], 'diffIds': diffs, 'layers': records, 'archiveTags': tags, 'config': config.get('config', {}), 'historySha256': hashlib.sha256(json.dumps(config.get('history', []), sort_keys=True).encode()).hexdigest()}
