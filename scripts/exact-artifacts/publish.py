"""Download locked private release assets; verify Docker-save content; optionally publish exact config.
No build, public server, default-tag update, or credential extraction. Run in a dedicated CI job.
"""
import argparse, hashlib, json, os, pathlib, re, subprocess, tarfile, tempfile

REGISTRY = 'registry.cn-beijing.aliyuncs.com/pre-sduoj/sduoj-judger'
REPO = 'SDUOJ/sduoj-judger'
HEX = re.compile(r'^[0-9a-f]{64}$')
SHA = re.compile(r'^[0-9a-f]{40}$')

def check(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()

def command(*args, binary=False):
    result = subprocess.run(args, capture_output=True, text=not binary, check=False)
    check(result.returncode == 0, 'Command failed: ' + args[0] + ' ' + args[1] + ': ' + (result.stderr.decode(errors='replace') if binary else result.stderr)[-1500:])
    return result.stdout

def strict_manifest(m):
    expected = {'schemaVersion','repository','component','productSource','platform','registryRepository','immutableTag','archiveTags','manifestDigest','layers','configSha256','diffIds','archiveSha256','archiveBytes','releaseId','releaseTag','parts','qualification'}
    check(set(m) == expected, 'Manifest fields mismatch')
    check(m['schemaVersion'] == 1 and m['repository'] == REPO, 'Repository/schema mismatch')
    check(SHA.fullmatch(m['productSource']) is not None, 'Invalid product source')
    check(m['component'] in ('judger', 'ide-worker', 'execution-vm-manager'), 'Invalid component')
    check(m['platform'] in ('linux/amd64', 'linux/arm64'), 'Unsupported platform')
    check(m['qualification']['status'] in ('candidate-only', 'candidate-staging-only', 'qualified'), 'Invalid qualification')
    check(m['registryRepository'] == REGISTRY, 'Destination must be original Judger repository')
    check(re.fullmatch(r'(staging-)?(judger|ide-worker|execution-vm-manager)-\d{8}-[0-9a-f]{12}-[0-9a-f]{12}-(amd64|arm64)', m['immutableTag']), 'Invalid immutable tag')
    prefix = 'staging-' if m['qualification']['status'] == 'candidate-staging-only' else ''
    check(m['immutableTag'].startswith(prefix + m['component'] + '-'), 'Component/qualification tag mismatch')
    check(m['productSource'][:12] in m['immutableTag'] and m['configSha256'][:12] in m['immutableTag'], 'Tag/source/config binding mismatch')
    check(m['archiveTags'] is None or (isinstance(m['archiveTags'], list) and len(m['archiveTags']) <= 1 and all(':latest' not in x for x in m['archiveTags'])), 'Unexpected archive tags')
    check(m['immutableTag'].endswith('-' + m['platform'].split('/')[1]), 'Tag platform mismatch')
    for name in ('archiveSha256', 'configSha256'):
        check(HEX.fullmatch(m[name]) is not None, 'Invalid ' + name)
    check(m['diffIds'] and all(re.fullmatch(r'sha256:[0-9a-f]{64}', x) for x in m['diffIds']), 'Invalid layer diff IDs')
    check(m['releaseId'] > 0 and 0 < m['archiveBytes'] <= 40 * 1024**3, 'Invalid asset bounds')
    check(m['parts'] and len(m['parts']) <= 64, 'Invalid part count')
    check([x['ordinal'] for x in m['parts']] == list(range(len(m['parts']))), 'Part order')
    check(len(set(x['assetId'] for x in m['parts'])) == len(m['parts']), 'Duplicate assets')
    check(sum(x['bytes'] for x in m['parts']) == m['archiveBytes'], 'Part size sum')
    for x in m['parts']:
        check(x['assetId'] > 0 and 0 < x['bytes'] < 2 * 1024**3 and HEX.fullmatch(x['sha256']), 'Invalid part')
        check(re.fullmatch(r'image\.tar\.part-[0-9]{3}', x['name']), 'Invalid part filename')
    common = {'image-config-layer-verification', 'image-disclosure-review', 'image-smoke'}
    workloads = {
        'judger': {'native-formal', 'native-run', 'worker-runtime-junit'},
        'ide-worker': {'ide-api', 'ide-browser', 'ide-debug-lsp', 'ide-isolation', 'ide-capacity', 'ide-900s', 'ide-recovery'},
        'execution-vm-manager': {'manager-nonroot', 'manager-boot-assets', 'manager-feature'},
    }
    required = common | workloads[m['component']] | {'combined-release'}
    gates = m['qualification']['receipts']
    check({x['gate'] for x in gates} == required and len(gates) == len(required), 'Required gate set mismatch')
    for x in gates:
        check(x['status'] in ('pass', 'pending', 'fail'), 'Invalid gate status')
        check(x['productSource'] == m['productSource'] and x['configSha256'] == m['configSha256'], 'Receipt/source/config binding mismatch')
        check(HEX.fullmatch(x['sha256']) and x['assetId'] > 0, 'Receipt must bind a restricted asset')
    if m['qualification']['status'] == 'candidate-staging-only':
        check(all(x['status'] == 'pass' for x in gates if x['gate'] in common), 'Staging image/disclosure/smoke gates incomplete')
    if m['qualification']['status'] == 'qualified':
        check(all(x['status'] == 'pass' for x in gates), 'Incomplete qualified gate')

def api(path):
    return json.loads(command('gh', 'api', f'repos/{REPO}/{path}'))

def download(asset, destination):
    with destination.open('wb') as output:
        result = subprocess.run(['gh', 'api', f'repos/{REPO}/releases/assets/{asset}', '-H', 'Accept: application/octet-stream'], stdout=output, stderr=subprocess.PIPE)
    check(result.returncode == 0, 'Restricted asset download failed')

def inspect_archive(archive, m):
    from archive import inspect
    identity = inspect(archive)
    for key in ('archiveSha256', 'archiveBytes', 'configSha256', 'platform', 'diffIds', 'manifestDigest', 'layers'):
        check(identity[key] == m[key], 'Archive identity mismatch: ' + key)
    check(identity['archiveTags'] == m['archiveTags'], 'Restored tag set mismatch')
    for value in identity['config'].get('Env', []):
        key, _, content = value.partition('=')
        check(not re.search(r'(PASSWORD|TOKEN|SECRET|CREDENTIAL|PRIVATE_KEY)', key, re.I) or not content or content.startswith('${'), 'Sensitive image Env requires private review')
    return identity


def remote_config(reference):
    raw = command('docker', 'buildx', 'imagetools', 'inspect', '--raw', reference)
    manifest = json.loads(raw)
    check('config' in manifest and 'manifests' not in manifest, 'Single-platform child manifest required')
    config = json.loads(command('docker', 'buildx', 'imagetools', 'inspect', '--format', '{{json .Image}}', reference))
    display = command('docker', 'buildx', 'imagetools', 'inspect', reference)
    match = re.search(r'^Digest:\s+(sha256:[0-9a-f]{64})\s*$', display, re.M)
    check(match is not None, 'Missing registry child digest')
    return manifest['config']['digest'], config, match.group(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    pathlib.Path(args.report).write_text(json.dumps({'published': False, 'productionQualified': False, 'phase': 'validation-started'}) + '\n')
    path = pathlib.Path(args.manifest)
    check(re.fullmatch(r'scripts/exact-artifacts/manifests/[A-Za-z0-9_.-]+\.json', str(path)), 'Manifest must be checked-in reviewed path')
    tracked = command('git', 'ls-files', '--error-unmatch', str(path)).strip()
    check(tracked == str(path), 'Untracked manifest rejected')
    m = json.loads(path.read_text())
    strict_manifest(m)
    workflow_head = command('git', 'rev-parse', 'HEAD').strip()
    check(workflow_head == os.environ['GITHUB_SHA'], 'CI checkout mismatch')
    check(not args.publish or m['qualification']['status'] in ('candidate-staging-only', 'qualified'), 'candidate-only inputs cannot publish')
    release = api(f'releases/{m["releaseId"]}')
    check(release['draft'] and release['tag_name'] == m['releaseTag'], 'Exact restricted draft release required')
    assets = {a['id']: a for a in release['assets']}
    report = {'workflowSource': workflow_head, 'productSource': m['productSource'], 'qualification': m['qualification']['status'], 'manifestSha256': digest(path.read_bytes()), 'published': False, 'productionQualified': False, 'componentWorkloadsQualified': m['qualification']['status'] == 'qualified', 'trafficQualification': 'separate exact-registry-digest gate required; publication never activates traffic'}
    with tempfile.TemporaryDirectory(prefix='judger-exact-') as scratch:
        directory = pathlib.Path(scratch)
        archive = directory / 'image.tar'
        with archive.open('wb') as target:
            for part in m['parts']:
                meta = assets.get(part['assetId'])
                check(meta and meta['name'] == part['name'] and meta['size'] == part['bytes'] and meta['state'] == 'uploaded', 'Asset metadata mismatch')
                dest = directory / part['name']
                download(part['assetId'], dest)
                check(dest.stat().st_size == part['bytes'] and file_digest(dest) == part['sha256'], 'Asset checksum mismatch')
                with dest.open('rb') as source:
                    import shutil
                    shutil.copyfileobj(source, target)
                dest.unlink()
        check(archive.stat().st_size == m['archiveBytes'] and file_digest(archive) == m['archiveSha256'], 'Archive checksum mismatch')
        for receipt in m['qualification']['receipts']:
            check(receipt['assetId'] in assets and assets[receipt['assetId']]['size'] <= 16 * 1024**2, 'Receipt must be same restricted release and bounded')
            dest = directory / ('receipt-' + str(receipt['assetId']) + '.json')
            download(receipt['assetId'], dest)
            check(dest.stat().st_size <= 16 * 1024**2 and digest(dest.read_bytes()) == receipt['sha256'], 'Receipt checksum mismatch')
            data = json.loads(dest.read_text())
            check(all(data.get(k) == receipt[k] for k in ('gate', 'status', 'productSource', 'configSha256')), 'Receipt content mismatch')
        inspect_archive(archive, m)
        report['archiveVerified'] = True
        loaded = command('docker', 'image', 'load', '--input', str(archive))
        refs = re.findall(r'^Loaded image(?: ID)?: (.+)$', loaded, re.M)
        check(len(refs) == 1, 'One loaded image identity required')
        loaded_ref = refs[0].strip()
        saved = directory / 'loaded-identity.tar'
        command('docker', 'image', 'save', '--output', str(saved), loaded_ref)
        from archive import inspect
        loaded_identity = inspect(saved)
        for key in ('configSha256', 'platform', 'diffIds'):
            check(loaded_identity[key] == m[key], 'Loaded identity mismatch: ' + key)
        # Docker29 Id may be OCI manifest digest. Tag the verified load handle, not configSHA.
        reference = REGISTRY + ':' + m['immutableTag']
        if args.publish:
            # Refuse replacing a tag. A transport/auth error must also fail closed, not be treated as absent.
            probe = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', '--raw', reference], capture_output=True, text=True)
            if probe.returncode == 0:
                raise RuntimeError('Immutable destination tag already exists')
            check('manifest unknown' in probe.stderr.lower() or 'not found' in probe.stderr.lower(), 'Cannot prove destination tag absent')
            command('docker', 'image', 'tag', loaded_ref, reference)
            command('docker', 'image', 'push', reference)
            config_digest, remote, manifest_digest = remote_config(reference)
            check(config_digest == 'sha256:' + m['configSha256'], 'Registry config identity mismatch')
            check(remote['rootfs']['diff_ids'] == m['diffIds'], 'Registry layer identity mismatch')
            check(remote['os'] + '/' + remote['architecture'] == m['platform'], 'Registry platform mismatch')
            report.update(published=True, reference=reference, childManifestDigest=manifest_digest, configDigest=config_digest)
    pathlib.Path(args.report).write_text(json.dumps(report, indent=2) + '\n')

if __name__ == '__main__':
    main()
