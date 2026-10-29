#!/bin/sh
set -eu

case "${SDUOJ_WORKER_MODE:-judge}" in
    judge)
        # Run uses the same Java route and its existing sduoj.run.worker config.
        if [ "$#" -eq 0 ]; then
            set -- /usr/local/bin/sduoj-start-judger
        fi
        exec /usr/local/bin/sduoj-judge-entrypoint "$@"
        ;;
    ide)
        # Identity and delegation are supplied by the role's deployment profile.
        # This path must never bootstrap host permissions or run the root dev lab.
        if [ "$(id -u)" -ne 10001 ] || [ "$(id -g)" -ne 10001 ]; then
            printf '%s\n' 'IDE mode requires UID/GID 10001:10001' >&2
            exit 64
        fi
        if [ "$(uname -m)" != aarch64 ]; then
            printf '%s\n' 'IDE mode currently requires native ARM64 tools' >&2
            exit 64
        fi
        case "${SDUOJ_IDE_DEV_DEBUG_LAB:-0}" in
            0|'') ;;
            *) printf '%s\n' 'The unified worker does not allow root dev-lab bootstrap' >&2; exit 64 ;;
        esac
        if [ "${1-}" = /usr/local/bin/sduoj-start-judger ]; then
            shift
        fi
        unset PYTHONHOME
        export JAVA_HOME=/opt/java/openjdk21
        export PATH="/opt/ide-sdk/bin:$JAVA_HOME/bin:$PATH"
        export PYTHONPATH=/opt/sduoj-ide:/opt/sduoj-ide/deps:/opt/sduoj-debug/debugpy
        export PYTHONUNBUFFERED=1
        export AUTOLAB_IDE_SERVER_MODE="${AUTOLAB_IDE_SERVER_MODE:-host}"
        export AUTOLAB_IDE_INTELLIGENCE_ENABLED="${AUTOLAB_IDE_INTELLIGENCE_ENABLED:-1}"
        if [ -z "${AUTOLAB_IDE_JAVA_HOMES:-}" ]; then
            export AUTOLAB_IDE_JAVA_HOMES='{"8":"/opt/java/openjdk8","17":"/opt/java/openjdk17","21":"/opt/java/openjdk21"}'
        fi
        if [ -z "${AUTOLAB_IDE_PYTHON_PATHS:-}" ]; then
            export AUTOLAB_IDE_PYTHON_PATHS='{"cpython-3.11":"/opt/python/3.11/bin/python"}'
        fi
        export AUTOLAB_IDE_CLANGD_COMMAND="${AUTOLAB_IDE_CLANGD_COMMAND:-clangd --background-index=false}"
        export AUTOLAB_IDE_PYRIGHT_COMMAND="${AUTOLAB_IDE_PYRIGHT_COMMAND:-/opt/node/bin/pyright-langserver --stdio}"
        export AUTOLAB_IDE_JDTLS_COMMAND="${AUTOLAB_IDE_JDTLS_COMMAND:-/opt/jdtls/bin/jdtls --jvm-arg=-Xms64m --jvm-arg=-Xmx384m}"
        export AUTOLAB_IDE_JAVA_IMMUTABLE_URI="${AUTOLAB_IDE_JAVA_IMMUTABLE_URI:-1}"
        export SDUOJ_JUDGE_ROOTFS="${SDUOJ_JUDGE_ROOTFS:-/opt/judge-rootfs}"
        export AUTOLAB_DEBUG_NSJAIL="${AUTOLAB_DEBUG_NSJAIL:-/opt/sduoj-ide/scripts/nsjail}"
        exec /opt/python/3.11/bin/python /opt/sduoj-ide/scripts/entrypoint.py "$@"
        ;;
    *)
        printf '%s\n' 'SDUOJ_WORKER_MODE must be judge or ide' >&2
        exit 64
        ;;
esac
