ARG UBUNTU_VERSION=18.04
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
            make=4.1-9.1ubuntu1 cmake \
# install dosbox for Assembly Course
            dosbox=0.74-4.3 \
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
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_gcc-7.5.0 /opt/ /opt/
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_gcc-13.2.0 /opt/ /opt/
# install Rust
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_rust-1.78.0 /opt/ /opt/
# install sduoj-sandbox
COPY --from=ghcr.io/sduoj/judging-containers:ubuntu-18.04_sduoj-sandbox /opt/ /opt/
# install docker-compose-wait
COPY --from=ghcr.io/sduoj/docker-compose-wait:latest /wait /wait

# configure the environment
RUN mkdir -p /sduoj \
 && ln -s /opt/sduoj-sandbox/bin/sandbox /usr/bin/sandbox \
 && ln -s /opt/python/3.11/bin/python    /usr/bin/python3 \
 && ln -s /opt/gcc/7.5.0/bin/gcc         /usr/bin/gcc \
 && ln -s /opt/gcc/7.5.0/bin/g++         /usr/bin/g++

# copy sduoj-judger
COPY sduoj-judger-service/build/libs/ /sduoj/
# copy testlib.h
COPY docker/testlib /testlib.h
# copy checkers
COPY docker/checkers/ /checkers/

ENV NACOS_ADDR=127.0.0.1:8848
ENV ACTIVE=prod
ENV CPU_PER_JUDGER=1

WORKDIR /sduoj

ENTRYPOINT /wait                                                   \
 && JAVA_OPT="${JAVA_OPT} -jar sduoj-judger.jar"                   \
 && JAVA_OPT="${JAVA_OPT} --sduoj.config.active=$ACTIVE"           \
 && JAVA_OPT="${JAVA_OPT} --sduoj.config.nacos-addr=$NACOS_ADDR"   \
 && echo "SDUOJ is starting, you can check the '/sduoj/sduoj.log'" \
 && echo "Run: java ${JAVA_OPT}"                                   \
 && exec java ${JAVA_OPT} >> /sduoj/sduoj.log 2>&1
