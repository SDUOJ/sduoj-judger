FROM ubuntu:18.04 as basic
MAINTAINER SDUOJ-Team

# fix encoding
ENV LANG C.UTF-8
# fix timezone issue
ENV TZ Asia/Shanghai
# suppress the interactive prompt from tzdata
ENV DEBIAN_FRONTEND=noninteractive

# install runtime dependencies
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
            ca-certificates tzdata

# substitute apt sources
# COPY docker/sources.list /etc/apt/sources.list

# install OS softwares
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
            make=4.1-9.1ubuntu1 dosbox=0.74-4.3 \
            cmake sudo git unzip wget curl host dos2unix vim \
            libseccomp-dev libseccomp2 seccomp build-essential \
  && apt-get clean autoclean \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/* \
  && rm -f /var/cache/apt/archives/*.deb

# ---------------------------------------------
FROM continuumio/miniconda3 as py-builder

RUN for PYTHON_VERSION in 3.6 3.11; do \
        conda create --prefix /opt/python/${PYTHON_VERSION} python=${PYTHON_VERSION} -y -q \
     && /opt/python/${PYTHON_VERSION}/bin/python -m pip install --upgrade pip \
    ; done

# ---------------------------------------------
FROM basic

# copy sduoj-judger
COPY sduoj-judger-service/build/libs/ /sduoj/
# copy testlib.h
COPY docker/testlib /testlib.h
# copy checkers
COPY docker/checkers/ /checkers/

# download docker-compose-wait
COPY --from=sduoj/docker-compose-wait:latest /wait /wait

# install Python(s)
COPY --from=py-builder /opt/python/ /opt/python/
RUN ln -s /opt/python/3.11/bin/python /usr/bin/python3 \
 && ln -s /opt/python/3.11/bin/python /usr/bin/python3.11 \
 && ln -s /opt/python/3.6/bin/python /usr/bin/python3.6

# install JDK(s)
ENV JAVA_HOME=/opt/java/openjdk
COPY --from=eclipse-temurin:8 $JAVA_HOME ${JAVA_HOME}8
COPY --from=eclipse-temurin:17 $JAVA_HOME ${JAVA_HOME}17
# set the default JDK to JDK17
ENV JAVA_HOME=/opt/java/openjdk17
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# compile and install sduoj-sandbox
RUN wget -q -O /sduoj/sandbox.zip https://codeload.github.com/SDUOJ/sduoj-sandbox/zip/master \
 && unzip -o -q -d /sduoj /sduoj/sandbox.zip \
 && rm /sduoj/sandbox.zip \
 && cd /sduoj/sduoj-sandbox* \
 && make \
 && make install

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
