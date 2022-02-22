FROM ubuntu:18.04
MAINTAINER SDUOJ-Team

ENV LANG C.UTF-8

COPY sduoj-judger-service/build/libs/ /sduoj/
# COPY docker/sources.list /etc/apt/sources.list
COPY docker/testlib /testlib.h
COPY docker/checkers/ /checkers/

ADD https://github.com/SDUOJ/docker-compose-wait/releases/download/2.7.3/wait /wait
RUN mkdir -p /sduoj/dockerWorkspace \
 && chmod +x /wait

# install OS softwares
RUN apt-get update \
 && apt-get install -qq -y \
                    make=4.1-9.1ubuntu1   dosbox=0.74-4.3 cmake \
                    sudo git unzip wget libseccomp-dev libseccomp2 seccomp build-essential \
                    python3-pip python vim dos2unix openjdk-8-jdk \
 && ln -sf /usr/lib/jvm/java-8-openjdk-amd64/bin/java /usr/bin/java \
 && ln -sf /usr/lib/jvm/java-8-openjdk-amd64/bin/javac /usr/bin/javac

# compile and install sduoj-sandbox
RUN wget -q -O /sduoj/sandbox.zip https://codeload.github.com/SDUOJ/sduoj-sandbox/zip/master \
 && unzip -o -q -d /sduoj /sduoj/sandbox.zip \
 && rm /sduoj/sandbox.zip \
 && cd /sduoj/sduoj-sandbox* \
 && make \
 && make install

ENV NACOS_ADDR=127.0.0.1:8848
ENV ACTIVE=prod

WORKDIR /sduoj

CMD /wait \
 && java -jar sduoj-judger.jar \
         --sduoj.config.nacos-addr=$NACOS_ADDR \
         --sduoj.config.active=$ACTIVE \
         >> /sduoj/sduoj.log
