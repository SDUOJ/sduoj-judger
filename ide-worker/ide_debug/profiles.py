"""Bind an authorized template to a locally installed, operator-approved rootfs.

Templates are parsed, never passed to a shell. Runtime versions/flags must match
an exact approved template hash; a browser cannot select executables or mounts.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from dataclasses import dataclass, field
import math
from ide_intelligence.toolchain import parse_template, _argv, ToolchainUnavailable
from .config import MiB
from .judge_compile import CompileLimits


def phase_startup_budget(runtime_startup, compile_bytes, *, artifact_max_bytes=64 * MiB,
                         compile_setup_bytes=64 * MiB):
    """One kernel-domain grant; only two artifact copies may survive to runtime.

    The drained compiler workspace and diagnostic body must be removed before
    runtime starts. Limits are candidate inputs, never browser overrides.
    """
    if (any(type(value) is not int or value <= 0 or value % os.sysconf("SC_PAGE_SIZE")
            for value in (runtime_startup, compile_bytes, artifact_max_bytes, compile_setup_bytes)) or
            not 32 * MiB <= runtime_startup <= 8 * 1024 * MiB or
            compile_bytes > 8 * 1024 * MiB or artifact_max_bytes > 64 * MiB or
            compile_setup_bytes != 64 * MiB):
        raise ValueError("Invalid compile/runtime phase budget")
    return max(compile_bytes + compile_setup_bytes, runtime_startup + 2 * artifact_max_bytes)


def validate_phase_budget(profile, policy):
    required = phase_startup_budget(profile.runtime_startup,
        profile.compile_limits["memory_bytes"], artifact_max_bytes=profile.artifact_max_bytes,
        compile_setup_bytes=profile.compile_setup_bytes)
    if (profile.startup != required or policy.cgroup_version != 2 or
            required + policy.guardian_memory > policy.budget - policy.reserve or
            required + policy.guardian_memory > policy.hard):
        raise DebugError("DEBUG_COMPILE_PHASE_BUDGET_INVALID", 503)
    return required


def verify_compile_policy(path, expected):
    """Bind setup permissions to the reviewed file before accepting a profile."""
    target = Path(path)
    if (not target.is_absolute() or ".." in target.parts or
            not re.fullmatch(r"[a-f0-9]{64}", str(expected))):
        raise DebugError("DEBUG_COMPILE_POLICY_NOT_VERIFIED", 503)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or
                    info.st_uid not in (0, os.getuid()) or not 0 < info.st_size <= 65536):
                raise ValueError("Untrusted compile policy")
            raw = stream.read(65537)
            after = os.fstat(stream.fileno())
            if (len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != expected or
                    (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError("Compile policy identity changed")
    except (OSError, ValueError) as error:
        raise DebugError("DEBUG_COMPILE_POLICY_NOT_VERIFIED", 503) from error


def sandbox_binary(root):
    """Resolve image-absolute symlinks inside rootfs, never on the host root.

    The judge image may publish /usr/bin/sandbox as a symlink into /opt. Host
    Path.resolve() would follow that absolute link outside the image.
    """
    root = Path(root)
    parts, resolved, links = ["usr", "bin", "sandbox"], [], 0
    while parts:
        part = parts.pop(0)
        if part in ("", ".", "/"):
            continue
        if part == "..":
            if not resolved:
                raise DebugError("DEBUG_COMPILE_SANDBOX_NOT_VERIFIED", 503)
            resolved.pop()
            continue
        candidate = root.joinpath(*resolved, part)
        if candidate.is_symlink():
            links += 1
            if links > 16:
                raise DebugError("DEBUG_COMPILE_SANDBOX_NOT_VERIFIED", 503)
            target = Path(os.readlink(candidate))
            if target.is_absolute():
                resolved = []
            parts = list(target.parts) + parts
        else:
            resolved.append(part)
    result = root.joinpath(*resolved)
    if not result.is_file() or result.stat().st_mode & 0o022:
        raise DebugError("DEBUG_COMPILE_SANDBOX_NOT_VERIFIED", 503)
    return result


class DebugError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def debug_compile(template, language):
    """Preserve linking, macros, ABI and library options; only explicit debug overrides."""
    profile = parse_template(template, language, str(template["id"]))
    config = json.loads(template["shellScript"])["user"]
    args = _argv(config["compile"]["commands"][0])
    if language in ("c", "cpp"):
        args = [
            a
            for a in args
            if not (
                re.fullmatch(r"-O(?:[0-3sgz]|fast)", a)
                or re.fullmatch(r"--optimize=[0-3sg]", a)
                or a in ("-s", "-flto")
                or a.startswith(("-flto=", "-Wl,--strip", "-Wl,-s"))
            )
        ]
        args += ["-O0", "-g", "-fno-omit-frame-pointer", "-fno-optimize-sibling-calls"]
    elif language == "java":
        args += ["-g"]
    return profile, args


@dataclass(frozen=True)
class Profile:
    template_id: str
    template_hash: str
    language: str
    rootfs: str
    artifact_digest: str
    source: str
    compile: list
    runner: str
    python: str
    debugger: list
    hard: int
    startup: int
    floor: int
    margin: int
    pids: int
    cpu_seconds: int
    compile_seconds: int
    active: int
    starting: int
    seccomp: str
    tmpfs: int
    java_options: list
    target_python: str = ""
    run_seconds: float = 0
    compile_limits: dict = field(default_factory=dict)
    compile_sandbox_sha256: str = ""
    compile_path_env: str = ""
    runtime_startup: int = 0
    artifact_max_bytes: int = 64 * MiB
    compile_setup_bytes: int = 64 * MiB
    compile_seccomp: str = ""
    compile_policy_sha256: str = ""

    @classmethod
    def resolve(cls, manifest, template, language, parameters=None):
        analysis, argv = debug_compile(template, language)
        run = _argv(json.loads(template["shellScript"])["user"]["run"]["command"])
        if language in ("c", "cpp") and run not in (["main"], ["./main"]):
            raise DebugError("DEBUG_RUN_TEMPLATE_UNSUPPORTED", 503)
        if language == "java" and (
            not run or run[-1] != Path(analysis["sourceName"]).stem
        ):
            raise DebugError("DEBUG_RUN_TEMPLATE_UNSUPPORTED", 503)
        entry = manifest.get(str(template["id"]))
        if (
            not entry
            or entry.get("templateHash") != analysis["templateHash"]
            or entry.get("templateVersion") != template["version"]
        ):
            raise DebugError("DEBUG_TOOLCHAIN_NOT_VERIFIED", 503)
        if entry.get("language") != language or not entry.get("verified"):
            raise DebugError("DEBUG_TOOLCHAIN_NOT_VERIFIED", 503)
        try:
            limits = CompileLimits.template(template)
            profile = cls(
                template_id=str(template["id"]),
                template_hash=analysis["templateHash"],
                language=language,
                source=analysis["sourceName"],
                compile=argv,
                target_python=analysis.get("pythonPath", ""),
                compile_limits=dict(cpu_ms=limits.cpu_ms, real_ms=limits.real_ms,
                                    memory_bytes=limits.memory_bytes),
                compile_seconds=math.ceil(limits.real_ms / 1000) + 3,
                **{
                    key: entry[key]
                    for key in cls.__dataclass_fields__
                    if key
                    not in (
                        "template_id",
                        "template_hash",
                        "language",
                        "source",
                        "compile",
                        "target_python",
                        "run_seconds",
                        "compile_limits",
                        "compile_seconds",
                    )
                }
            )
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", profile.artifact_digest):
                raise ValueError("Artifact digest required")
            if not re.fullmatch(r"[a-f0-9]{64}", profile.compile_sandbox_sha256):
                raise ValueError("Verified judge sandbox digest required")
            limits.argv(argv, profile.compile_path_env, cgroup_root="/compile-cgroup", pids=profile.pids)
            if profile.startup != phase_startup_budget(profile.runtime_startup, limits.memory_bytes,
                    artifact_max_bytes=profile.artifact_max_bytes, compile_setup_bytes=profile.compile_setup_bytes):
                raise ValueError("Phase startup grant must include compiler and artifact overhead")
            if (not re.fullmatch(r"[a-f0-9]{64}", profile.compile_policy_sha256) or
                    not Path(profile.compile_seccomp).is_absolute() or ".." in Path(profile.compile_seccomp).parts):
                raise ValueError("Trusted separate compile policy required")
            # Use the authoritative judge wall-time multiplier, never a browser limit.
            from dataclasses import replace

            real_factor = json.loads(template["shellScript"])["user"]["run"].get(
                "maxRealTimeFactor", 1
            )
            base_ms = (parameters or {}).get("problemTimeLimit")
            if type(real_factor) is not int or not 1 <= real_factor <= 100:
                raise ValueError("Invalid language time multiplier")
            if base_ms is not None:
                if type(base_ms) is not int or not 0 < base_ms <= 3600000:
                    raise ValueError("Invalid problem time limit")
                profile = replace(profile, run_seconds=2 * base_ms * real_factor / 1000)
            if not (
                32 * MiB
                <= profile.floor
                <= profile.hard
                <= profile.startup
                <= 8 * 1024 * MiB
                and 0 < profile.margin <= profile.hard
                and 0 < profile.pids <= 1024
                and 0 < profile.active <= 32
                and 0 < profile.starting <= 8
                and 0 < profile.cpu_seconds <= 1800
                and 0 < profile.compile_seconds <= 63
                and 0 < profile.tmpfs <= profile.startup
            ):
                raise ValueError("Invalid resource profile")
            if (
                language == "java"
                and profile.debugger[0] != analysis["javaHome"] + "/bin/java"
            ):
                raise ValueError("JDI must use the selected template JDK")
            if language == "java" and profile.starting != 1:
                raise ValueError("Java cold start concurrency must be one")
            for path in (profile.rootfs, profile.seccomp):
                if not Path(path).is_absolute() or ".." in Path(path).parts:
                    raise ValueError("Absolute trusted paths required")
            for path in (profile.runner, profile.python, *[profile.debugger[0]]):
                if not path.startswith("/") or ".." in Path(path).parts:
                    raise ValueError("Invalid rootfs executable")
            if language == "java":
                base = run[1:-1]
                parameters = parameters or {}
                for name in ("problemMemoryLimit", "problemTimeLimit"):
                    value = parameters.get(name)
                    if type(value) is int and value > 0:
                        base = [
                            arg.replace("{" + name + "}", str(value)) for arg in base
                        ]
                # Dynamic judge placeholders need explicit RPC values; do not
                # guess a problem memory limit from a debug sandbox cap.
                if any("{" in arg or "}" in arg for arg in base):
                    raise DebugError("DEBUG_RUN_PARAMETERS_UNRESOLVED", 503)
                from dataclasses import replace

                extras = [arg for arg in profile.java_options if arg not in base]
                profile = replace(profile, java_options=base + extras)
            return profile
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise DebugError("DEBUG_PROFILE_INVALID", 503) from error


def load_manifest(path):
    if not path:
        raise DebugError("DEBUG_MANIFEST_REQUIRED", 503)
    target = Path(path)
    if target.stat().st_mode & 0o022 or target.stat().st_uid not in (0, os.getuid()):
        raise DebugError("DEBUG_MANIFEST_PERMISSIONS", 503)
    if target.stat().st_size > 1048576:
        raise DebugError("DEBUG_MANIFEST_INVALID", 503)
    value = json.loads(target.read_text())
    if not isinstance(value, dict) or len(value) > 128:
        raise DebugError("DEBUG_MANIFEST_INVALID", 503)
    for key, entry in value.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[1-9][0-9]{0,18}", key)
            or not isinstance(entry, dict)
        ):
            raise DebugError("DEBUG_MANIFEST_INVALID", 503)
        if not entry.get("verified"):
            continue
        if (not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("compile_sandbox_sha256", "")))
                or not isinstance(entry.get("compile_path_env"), str)
                or not entry["compile_path_env"]):
            raise DebugError("DEBUG_COMPILE_SANDBOX_NOT_VERIFIED", 503)
        root = Path(entry["rootfs"])
        policy = Path(entry["seccomp"])
        verify_compile_policy(entry.get("compile_seccomp", ""),
                              entry.get("compile_policy_sha256"))
        for item in (root, policy):
            if (
                not item.is_absolute()
                or ".." in item.parts
                or item.stat().st_mode & 0o022
                or item.stat().st_uid not in (0, os.getuid())
            ):
                raise DebugError("DEBUG_ARTIFACT_PERMISSIONS", 503)
        stamp = root / ".sduoj-debug-toolchain.json"
        if stamp.stat().st_size > 65536:
            raise DebugError("DEBUG_ARTIFACT_IDENTITY", 503)
        identity = json.loads(stamp.read_text())
        expected = {
            "templateVersion": entry["templateVersion"],
            "templateHash": entry["templateHash"],
            "compilePathEnv": entry["compile_path_env"],
        }
        if (
            identity.get("artifactDigest") != entry["artifact_digest"]
            or identity.get("sandboxSha256") != entry["compile_sandbox_sha256"]
            or identity.get("compilePolicySha256") != entry["compile_policy_sha256"]
            or identity.get("templates", {}).get(key) != expected
        ):
            raise DebugError("DEBUG_ARTIFACT_IDENTITY", 503)
        sandbox = sandbox_binary(root)
        if (hashlib.sha256(sandbox.read_bytes()).hexdigest()
                != entry["compile_sandbox_sha256"]):
            raise DebugError("DEBUG_COMPILE_SANDBOX_NOT_VERIFIED", 503)
    return value
