# Frozen image inputs are supplied by the deployment lock, never mutable latest.
ARG JUDGE_IMAGE
ARG TOOLS_IMAGE
ARG DEBUG_TOOLS_IMAGE
ARG JUDGE_IMAGE_ID
FROM ${JUDGE_IMAGE} AS judge
FROM ${DEBUG_TOOLS_IMAGE} AS debug-tools
USER root
RUN mkdir -p /nsjail-runtime/lib \
    && cp /usr/local/bin/nsjail /nsjail-runtime/nsjail \
    && ldd /usr/local/bin/nsjail | awk '/=> \/|^\s*\// {for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}' \
       | xargs -r -I '{}' cp -L '{}' /nsjail-runtime/lib/ \
    && cp -L /lib/ld-linux-aarch64.so.1 /nsjail-runtime/lib/

FROM ${TOOLS_IMAGE} AS worker
USER root
# The compiler/runtime root filesystem is copied intact from Judger. LSP and
# the control interpreter use their independent management runtime outside it.
COPY --from=judge / /opt/judge-rootfs/
COPY --from=judge /opt/python/3.11/ /opt/python/3.11/
COPY --from=judge /opt/java/ /opt/java/
COPY --from=debug-tools /nsjail-runtime/ /opt/nsjail-runtime/
COPY --from=debug-tools /usr/local/libexec/sduoj-debug-bootstrap /usr/local/libexec/sduoj-debug-bootstrap
COPY --from=debug-tools /rootfs-real/opt/sduoj-debug/ /opt/judge-rootfs/opt/sduoj-debug/
COPY --from=debug-tools /rootfs-real/opt/python/3.11/lib/python3.11/site-packages/debugpy/ /opt/judge-rootfs/opt/python/3.11/lib/python3.11/site-packages/debugpy/
RUN apt-get update -qq && apt-get install -y --no-install-recommends uidmap \
    && rm -rf /var/lib/apt/lists/* \
    && (id ide >/dev/null 2>&1 || useradd -u 10001 -m ide) \
    && printf 'ide:100000:65536\n' > /etc/subuid \
    && printf 'ide:100000:65536\n' > /etc/subgid
WORKDIR /opt/sduoj-ide
COPY sduoj-judger/ide-worker/ide_intelligence ./ide_intelligence
COPY sduoj-judger/ide-worker/ide_debug ./ide_debug
COPY sduoj-judger/ide-worker/sduoj_ide_worker ./sduoj_ide_worker
COPY sduoj-judger/ide-worker/scripts ./scripts
COPY sduoj-judger/ide-worker/ide_debug/ /opt/judge-rootfs/opt/sduoj-debug/ide_debug/
COPY sduoj-judger/ide-worker/toolchain-templates.json /opt/sduoj-ide/toolchain-templates.json
COPY sduoj-deploy/templates/debug/arm64-debug-v1.candidate.policy /opt/sduoj-ide/debug.policy
ARG JUDGE_IMAGE_ID
RUN python3 scripts/prepare_image.py --judge-image "$JUDGE_IMAGE_ID" \
    && python3 -c 'import redis.asyncio,pydantic,httpx' \
    && chmod 0755 scripts/entrypoint.py scripts/nsjail
ENV PYTHONPATH=/opt/sduoj-ide \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUTOLAB_IDE_SERVER_MODE=host \
    AUTOLAB_IDE_INTELLIGENCE_ENABLED=1 \
    AUTOLAB_IDE_JAVA_HOMES='{"8":"/opt/java/openjdk8","17":"/opt/java/openjdk17","21":"/opt/java/openjdk21"}' \
    AUTOLAB_IDE_PYTHON_PATHS='{"cpython-3.11":"/opt/python/3.11/bin/python"}' \
    AUTOLAB_IDE_CLANGD_COMMAND="clangd --background-index=false" \
    AUTOLAB_IDE_PYRIGHT_COMMAND="/opt/node/bin/node /opt/node/lib/node_modules/pyright/dist/pyright-langserver.js --stdio" \
    AUTOLAB_IDE_JDTLS_COMMAND="/opt/jdtls/bin/jdtls --jvm-arg=-Xms64m --jvm-arg=-Xmx384m" \
    AUTOLAB_IDE_JAVA_IMMUTABLE_URI=1 \
    SDUOJ_JUDGE_ROOTFS=/opt/judge-rootfs \
    AUTOLAB_DEBUG_MANIFEST=/opt/sduoj-ide/debug-profiles.json \
    AUTOLAB_DEBUG_NSJAIL=/opt/sduoj-ide/scripts/nsjail
USER ide
ENTRYPOINT ["python3", "/opt/sduoj-ide/scripts/entrypoint.py"]
