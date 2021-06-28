FROM ubuntu:18.04
MAINTAINER SDUOJ-dev

ENV LANG C.UTF-8

COPY docker/sources.list /etc/apt/sources.list
COPY docker/mavenSettings.xml /usr/share/maven/conf/settings.xml
COPY docker/testlib /testlib.h
COPY docker/checkers/ /checkers/
ADD https://github.com/SDUOJ/docker-compose-wait/releases/download/2.7.3/wait /wait

RUN apt-get update \
 && apt-get install -y sudo git unzip wget libseccomp-dev libseccomp2 seccomp build-essential python3-pip python dosbox vim dos2unix openjdk-8-jdk maven cmake

RUN git clone https://github.com/SDUOJ/sduoj-sandbox.git \
 && cd sduoj-sandbox \
 && make \
 && make install

RUN ln -sf /usr/lib/jvm/java-8-openjdk-amd64/bin/java /usr/bin/java \
 && ln -sf /usr/lib/jvm/java-8-openjdk-amd64/bin/javac /usr/bin/javac \
 && mkdir /sduoj \
 && wget -O /sduoj/server.zip https://codeload.github.com/SDUOJ/sduoj-server/zip/master \
 && wget -O /sduoj/judger.zip https://codeload.github.com/SDUOJ/sduoj-judger/zip/master \
 && unzip -o -q -d /sduoj /sduoj/server.zip \
 && unzip -o -q -d /sduoj /sduoj/judger.zip \
 && mkdir /usr/share/maven/conf/logging \
 && cd /sduoj/sduoj-server-master \
 && mvn install \
 && cd /sduoj/sduoj-judger-master \
 && mvn package \
 && mv sduoj-judger-service/target/sduoj-judger.jar ../sduoj-judger.jar \
 && rm -rf ~/.m2 \
 && rm -rf /sduoj/sduoj-server-master \
 && rm -rf /sduoj/sduoj-judger-master \
 && apt-get purge -y maven \
 && chmod +x /wait

ENV NACOS_ADDR=nacos.oj.qd.sdu.edu.cn:8848
ENV ACTIVE=prod

WORKDIR /sduoj
CMD /wait \
 && java -jar sduoj-judger.jar --sduoj.config.nacos-addr=$NACOS_ADDR --sduoj.config.active=$ACTIVE >> /sduoj/sduoj.log
