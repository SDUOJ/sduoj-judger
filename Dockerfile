ARG UBUNTU_VERSION=18.04
ARG IDE_TOOLS_IMAGE
ARG IDE_DEBUG_TOOLS_IMAGE

# Upstream SDK images are build inputs only. The published worker remains this
# original Ubuntu/Java17 image; no separate IDE image is published.
FROM ${IDE_TOOLS_IMAGE} AS ide-tools
FROM ${IDE_DEBUG_TOOLS_IMAGE} AS ide-debug-tools
FROM ubuntu:${UBUNTU_VERSION} as basic
# metadata
LABEL maintainer="SDUOJ-Team"
ENV JUDGER_TAG="default"

# fix encoding
ENV LANG=C.UTF-8 \
# fix timezone issue
  TZ=Asia/Shanghai \
# suppress the interactive prompt from tzdata
  DEBIAN_FRONTEND=noninteractive \
# prevent Python from writing pyc files
  PYTHONDONTWRITEBYTECODE=1

# install runtime dependencies
ARG ENABLE_REPLACE_APT_SOURCES=false
RUN --mount=type=bind,source=docker/replace-apt-sources.sh,target=replace-apt-sources.sh \
 bash replace-apt-sources.sh ${ENABLE_REPLACE_APT_SOURCES} \
 && apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
            ca-certificates tzdata \
            sudo git unzip wget curl host dos2unix vim \
            make cmake \
            build-essential \
# install dosbox for Assembly Course
            dosbox=0.74-4.3 \
# install tini
  && TINI_ARCH=$(dpkg --print-architecture) \
  && curl -L "https://github.com/krallin/tini/releases/download/v0.19.0/tini-${TINI_ARCH}" -o /usr/bin/tini \
  && chmod +x /usr/bin/tini \
# clean up
  && apt-get clean autoclean \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -f /var/cache/apt/archives/*.deb

# install JDK
COPY --from=eclipse-temurin:8  /opt/java/openjdk /opt/java/openjdk8
COPY --from=eclipse-temurin:17 /opt/java/openjdk /opt/java/openjdk17
COPY --from=eclipse-temurin:21 /opt/java/openjdk /opt/java/openjdk21
# set the default JDK to JDK17
ENV JAVA_HOME=/opt/java/openjdk17
ENV PATH="${JAVA_HOME}/bin:${PATH}"
# install Python
COPY --from=ghcr.io/sduoj/judging-containers:python-3.6 /opt/ /opt/
COPY --from=ghcr.io/sduoj/judging-containers:python-3.11 /opt/ /opt/
COPY --from=ghcr.io/sduoj/judging-containers:python-3.12-csp /opt/ /opt/
# install PyPy
COPY --from=ghcr.io/sduoj/judging-containers:pypy-3.10-v7.3.15 /opt/ /opt/
# install GCC
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_gcc-13.2.0 /opt/ /opt/
# install Rust
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_rust-1.78.0 /opt/ /opt/
# install sduoj-sandbox and its trusted entrypoint from the original producer
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_sduoj-sandbox /opt/ /opt/
RUN test -x /opt/sduoj-sandbox/bin/judge-entrypoint \
 && ln -s /opt/sduoj-sandbox/bin/judge-entrypoint /usr/local/bin/sduoj-judge-entrypoint
# install docker-compose-wait
COPY --from=ghcr.io/sduoj/docker-compose-wait:latest /wait /wait

# configure the environment
RUN mkdir -p /sduoj \
 && ln -s /opt/sduoj-sandbox/bin/sandbox /usr/bin/sandbox \
 && ln -s /opt/python/3.11/bin/python    /usr/bin/python3


# Freeze the original formal judge/runtime contents before adding application
# jars and the optional IDE worker. The IDE rootfs is an explicit /opt
# toolchain whitelist; it never copies the final image recursively.
FROM basic AS judge-runtime
FROM judge-runtime AS final
COPY --from=judge-runtime /opt /opt/judge-rootfs/opt

# Relocatable upstream SDK payloads. Node and clangd carry private loaders;
# Python wheels are unpacked into the existing Judger Python 3.11 runtime
# target rather than replacing the image's management/runtime libc.
COPY --from=ide-tools /opt/node /opt/node
COPY --from=ide-tools /opt/jdtls /opt/jdtls
COPY --from=ide-tools /opt/ide-tools /opt/ide-tools
COPY --from=ide-tools /opt/toolchain-provenance /opt/sduoj-ide/toolchain-provenance
COPY --from=ide-debug-tools /artifacts/nsjail-runtime /opt/nsjail-runtime
COPY --from=ide-debug-tools /artifacts/gdb-runtime /opt/sduoj-debug/gdb-runtime
COPY --from=ide-debug-tools /artifacts/debugpy /opt/sduoj-debug/debugpy
COPY --from=ide-debug-tools /opt/toolchain-provenance /opt/sduoj-debug/toolchain-provenance
RUN mkdir -p /opt/sduoj-ide/deps /opt/ide-sdk/bin \
 && find /opt/ide-tools/python-wheels -type f -name '*.whl' -print0 \
    | sort -z \
    | xargs -0 -n1 unzip -q -d /opt/sduoj-ide/deps \
 && rm -rf /opt/ide-tools/python-wheels \
 && ln -s /opt/node/bin/node /opt/ide-sdk/bin/node \
 && ln -s /opt/node/bin/pyright /opt/ide-sdk/bin/pyright \
 && ln -s /opt/node/bin/pyright-langserver /opt/ide-sdk/bin/pyright-langserver \
 && ln -s /opt/ide-tools/bin/clangd-wrapper /opt/ide-sdk/bin/clangd \
 && mkdir -p /opt/sduoj-debug/bridge \
 && chmod 0555 /opt/nsjail-runtime/nsjail /opt/ide-tools/bin/clangd-wrapper

# Worker source and reviewed adapters are owned by Judger. This copy does not
# install a policy or mark profiles qualified; startup must load an
# operator-approved manifest and fail closed otherwise.
COPY ide-worker/ide_intelligence /opt/sduoj-ide/ide_intelligence
COPY ide-worker/ide_debug /opt/sduoj-ide/ide_debug
COPY ide-worker/sduoj_ide_worker /opt/sduoj-ide/sduoj_ide_worker
COPY ide-worker/scripts /opt/sduoj-ide/scripts
COPY ide-worker/toolchain-templates.json /opt/sduoj-ide/toolchain-templates.json
COPY ide-worker/extraction.json /opt/sduoj-ide/extraction.json
RUN /opt/java/openjdk17/bin/javac -d /opt/sduoj-debug/bridge /opt/sduoj-ide/ide_debug/adapters/DebugBridge.java \
 && chmod 0555 /opt/sduoj-ide/scripts/entrypoint.py /opt/sduoj-ide/scripts/nsjail

WORKDIR /app

# copy sduoj-judger.jar
COPY sduoj-judger-service/build/libs/ /app/
# copy testlib.h
COPY docker/testlib /testlib.h
# copy checkers
COPY docker/checkers/ /checkers/

ENV NACOS_ADDR="127.0.0.1:8848" \
    ACTIVE="prod" \
    CPU_PER_JUDGER=1 \
    JAVA_OPT="" \
    JAVA_OPT_EXT=""

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/sduoj-judge-entrypoint"]

CMD /wait                                                          \
 && JAVA_OPT="${JAVA_OPT} -jar sduoj-judger.jar"                   \
 && JAVA_OPT="${JAVA_OPT} ${JAVA_OPT_EXT}"                         \
 && JAVA_OPT="${JAVA_OPT} --sduoj.config.active=$ACTIVE"           \
 && JAVA_OPT="${JAVA_OPT} --sduoj.config.nacos-addr=$NACOS_ADDR"   \
 && echo "SDUOJ is starting. Logs are in '/app/logs/judger.log'"   \
 && echo "Run: java ${JAVA_OPT}"                                   \
 && mkdir -p /app/logs                                             \
 && exec java ${JAVA_OPT} >> /app/logs/judger.log 2>&1
