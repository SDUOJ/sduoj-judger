"""Trusted template snapshots for analysis; template commands are never executed."""
import asyncio
try:
    from asyncio import timeout
except ImportError:  # Python 3.10 in the standalone image.
    from async_timeout import timeout
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit


class ToolchainUnavailable(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def profile_hash(profile, language):
    return profile['hash'] if profile else 'legacy-' + language


def _argv(value):
    if not isinstance(value, str) or len(value) > 32768 or any(char in value for char in '\n\r\x00`$;&|<>'):
        raise ToolchainUnavailable('Unsupported template command')
    try:
        return shlex.split(value)
    except ValueError as error:
        raise ToolchainUnavailable('Invalid template command') from error


def _path(value):
    if not value.startswith('/') or '..' in Path(value).parts or len(value) > 1024:
        raise ToolchainUnavailable('Unsupported toolchain path')
    return value


def parse_template(template, language, requested_id):
    """Extract a small supported argv vocabulary, never interpret shell programs."""
    try:
        template_id = str(template['id'])
        version = template['version']
        if template_id != requested_id or not template_id.isascii() or not template_id.isdecimal():
            raise ToolchainUnavailable('Template identity mismatch')
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ToolchainUnavailable('Invalid template version')
        raw = template['shellScript']
        if not isinstance(raw, str) or len(raw) > 262144:
            raise ToolchainUnavailable('Invalid template configuration')
        user = json.loads(raw)['user']
        compile_config, run_config = user['compile'], user['run']
        commands = compile_config['commands']
        if not isinstance(commands, list) or len(commands) != 1:
            raise ToolchainUnavailable('Only single-command templates are supported')
        args, run = _argv(commands[0]), _argv(run_config['command'])
        source = compile_config['srcName']
        if not isinstance(source, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.(?:c|cpp|cc|cxx|java|py)', source):
            raise ToolchainUnavailable('Unsupported template source name')
        extensions = {'c': ('.c',), 'cpp': ('.cc', '.cpp', '.cxx'), 'java': ('.java',), 'python': ('.py',)}
        if language not in extensions or not source.endswith(extensions[language]):
            raise ToolchainUnavailable('Source name does not match language')
        result = {'schema': 1, 'templateId': template_id, 'templateVersion': version,
                  'templateHash': _digest(raw), 'language': language, 'sourceName': source,
                  'analysisFlags': [], 'compiler': _path(args[0])}
        executable = Path(args[0]).name
        if language in {'c', 'cpp'}:
            valid = {'c': {'gcc', 'clang'}, 'cpp': {'g++', 'clang++'}}[language]
            if executable not in valid:
                raise ToolchainUnavailable('Compiler does not match language')
            standard, flags = None, []
            index = 1
            while index < len(args):
                arg = args[index]
                if arg.startswith(('-std=', '--std=')):
                    standard = arg.split('=', 1)[1]
                    supported = (r'(?:gnu|c)(?:89|90|99|11|17|18|2x|23)' if language == 'c'
                                 else r'(?:gnu\+\+|c\+\+)(?:98|03|11|14|17|20|2a|23|2b|26|2c)')
                    if not re.fullmatch(supported, standard):
                        raise ToolchainUnavailable('Unsupported language standard')
                elif arg in {'-D', '-U', '-I', '-isystem', '-iquote', '--sysroot', '-isysroot', '-target', '--target'}:
                    index += 1
                    if index >= len(args):
                        raise ToolchainUnavailable('Missing compiler argument')
                    value = args[index]
                    if arg in {'-I', '-isystem', '-iquote', '--sysroot', '-isysroot'}:
                        _path(value)
                    elif not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_=.+-]*', value):
                        raise ToolchainUnavailable('Unsupported compiler argument')
                    flags.extend([arg, value])
                elif arg.startswith('--define-macro='):
                    value = arg.split('=', 1)[1]
                    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_=.+-]*', value):
                        raise ToolchainUnavailable('Unsupported compiler definition')
                    flags.append('-D' + value)
                elif arg.startswith(('-D', '-U')):
                    if not re.fullmatch(r'-[DU][A-Za-z_][A-Za-z0-9_=.+-]*', arg):
                        raise ToolchainUnavailable('Unsupported compiler definition')
                    flags.append(arg)
                elif arg.startswith('-I'):
                    _path(arg[2:]); flags.append(arg)
                elif arg.startswith(('--sysroot=', '--target=')):
                    if arg.startswith('--sysroot='):
                        _path(arg.split('=', 1)[1])
                    flags.append(arg)
                elif re.fullmatch(r'-O(?:[0-3sgz]|fast)', arg):
                    flags.append(arg)
                elif re.fullmatch(r'--optimize=[0-3sg]', arg):
                    flags.append('-O' + arg.split('=', 1)[1])
                elif arg in {'-o', '-L', '-l'}:
                    index += 1
                    if index >= len(args):
                        raise ToolchainUnavailable('Missing compiler output argument')
                elif (arg in {'-static', '-s', '-pipe', '-pthread', '-fno-asm', '-fno-strict-aliasing',
                              '-fno-optimize-sibling-calls', '-fwrapv', '-fno-common', '-w', '-g', '-c', '--no-warnings'}
                      or re.fullmatch(r'-O(?:[0-3sgz]|fast)', arg)
                      or re.fullmatch(r'--optimize=[0-3sg]', arg)
                      or arg.startswith(('-W', '-l', '-L', '--output=', '-fmax-errors='))
                      or arg == source or re.fullmatch(r'\{[A-Za-z_][A-Za-z0-9_]*\}', arg)):
                    # Output/link flags do not configure the analyzer. Optimization
                    # flags above must remain: they alter predefined macros.
                    pass
                else:
                    raise ToolchainUnavailable('Unsupported compiler option')
                index += 1
            if not standard:
                raise ToolchainUnavailable('Template must state its language standard')
            result['analysisFlags'] = ['-std=' + standard, *flags]
            for semantic in ('-fno-asm', '-fno-strict-aliasing', '-fwrapv', '-fno-common'):
                if semantic in args:
                    result['analysisFlags'].append(semantic)
            if '-pthread' in args:
                result['analysisFlags'].append('-pthread')
            result['standard'] = standard
        elif language == 'java':
            match = re.fullmatch(r'(/opt/java/openjdk(8|11|17|21|25))/bin/javac', args[0])
            if not match or not run or run[0] != match[1] + '/bin/java':
                raise ToolchainUnavailable('Unsupported Java toolchain')
            remaining = args[1:]
            if remaining not in ([source, '-encoding', 'UTF8'], [source, '-encoding', 'UTF-8'], [source]):
                raise ToolchainUnavailable('Custom Java build requires an explicit profile')
            result.update(javaVersion=match[2], javaHome=match[1])
        elif language == 'python':
            match = re.search(r'/(?:python|pypy)/(3\.[0-9]+)(?:[^/]*)/bin/(?:python(?:3(?:\.[0-9]+)?)?|pypy3?)$', args[0])
            if not match or args[1:3] != ['-m', 'py_compile'] or not run or run[0] != args[0]:
                raise ToolchainUnavailable('Unsupported Python toolchain')
            if args[3:] != [source]:
                raise ToolchainUnavailable('Custom Python build requires an explicit profile')
            result.update(pythonVersion=match[1], pythonPath=args[0],
                          pythonImplementation='pypy' if '/pypy/' in args[0] else 'cpython')
        else:
            raise ToolchainUnavailable('Unsupported language')
        result['hash'] = _digest(result)
        return result
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ToolchainUnavailable('Unsupported template configuration') from error


def configured_path(profile, kind):
    """Optional deploy-controlled maps; never accept path overrides from the browser."""
    version = profile['javaVersion' if kind == 'java' else 'pythonVersion']
    env = 'AUTOLAB_IDE_JAVA_HOMES' if kind == 'java' else 'AUTOLAB_IDE_PYTHON_PATHS'
    original = profile['javaHome' if kind == 'java' else 'pythonPath']
    try:
        mappings = json.loads(os.environ.get(env, '{}'))
        key = (profile.get('pythonImplementation', 'cpython') + '-' + version) if kind == 'python' else version
        value = mappings.get(key, mappings.get(version, original)
                             if kind != 'python' or profile.get('pythonImplementation') == 'cpython' else original)
        if not isinstance(value, str):
            raise ValueError()
        return _path(value)
    except (ValueError, AttributeError) as error:
        raise ToolchainUnavailable('Invalid runtime mapping') from error


def require_runtime(profile):
    if not profile:
        return
    if profile['language'] == 'java':
        path = Path(configured_path(profile, 'java')) / 'bin/java'
    elif profile['language'] == 'python':
        path = Path(configured_path(profile, 'python'))
    else:
        return
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ToolchainUnavailable('Target analysis runtime is not installed')


class ToolchainResolver:
    def __init__(self):
        import httpx
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(2., connect=.5),
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8), follow_redirects=False, trust_env=False)
        self.permits = asyncio.Semaphore(16)
        self.waiting = 0

    async def resolve(self, template_id, language, user, context, problem_code):
        url = os.environ.get('AUTOLAB_IDE_TOOLCHAIN_RESOLVER_URL', '')
        token = os.environ.get('AUTOLAB_IDE_TOOLCHAIN_TOKEN', '')
        parts = urlsplit(url)
        if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password
                or parts.path != '/internal/ide/toolchain/resolve' or parts.query or parts.fragment or not token):
            raise ToolchainUnavailable('Toolchain resolver is not configured')
        if self.waiting >= 64:
            raise ToolchainUnavailable('Toolchain resolver is busy')
        self.waiting += 1
        try:
            async with timeout(2.5):
                async with self.permits:
                    async with self.client.stream('POST', url, headers={'sduoj-token': token}, json={
                        'judgeTemplateId': template_id, 'user': user, 'context': context,
                        'problemCode': problem_code}) as response:
                        response.raise_for_status()
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 262144:
                                raise ToolchainUnavailable('Template response too large')
                            chunks.append(chunk)
                        template = json.loads(b''.join(chunks))
            profile = parse_template(template, language, template_id)
            require_runtime(profile)
            return profile
        except ToolchainUnavailable:
            raise
        except Exception as error:
            raise ToolchainUnavailable('Toolchain resolution failed') from error
        finally:
            self.waiting -= 1

    async def close(self):
        await self.client.aclose()
