FROM ubuntu:18.04
MAINTAINER SDUOJ-Team

# fix encoding
ENV LANG C.UTF-8

# fix timezone issue
ENV TZ Asia/Shanghai
# suppress the interactive prompt from tzdata
ENV DEBIAN_FRONTEND=noninteractive

COPY sduoj-judger-service/build/libs/ /sduoj/
# COPY docker/sources.list /etc/apt/sources.list
COPY docker/testlib /testlib.h
COPY docker/checkers/ /checkers/

# download docker-compose-wait
COPY --from=sduoj/docker-compose-wait:latest /wait /wait

# install JDKs
ENV JAVA_HOME=/opt/java/openjdk
COPY --from=eclipse-temurin:8 $JAVA_HOME ${JAVA_HOME}8
COPY --from=eclipse-temurin:17 $JAVA_HOME ${JAVA_HOME}17
# set the default JDK to JDK17
ENV JAVA_HOME=/opt/java/openjdk17
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# install OS softwares
RUN apt-get update \
 && apt-get install -qq -y \
                    make=4.1-9.1ubuntu1   dosbox=0.74-4.3 cmake \
                    tzdata sudo git unzip wget host libseccomp-dev libseccomp2 seccomp build-essential \
                    python3-pip python vim dos2unix

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
