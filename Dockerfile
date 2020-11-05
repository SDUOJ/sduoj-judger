FROM ubuntu:18.04
MAINTAINER SDUOJ-dev

COPY sources.list /etc/apt/sources.list

RUN apt-get update \
 && apt-get install -y sudo git unzip wget libseccomp-dev libseccomp2 seccomp build-essential python3-pip dosbox openjdk-8-jre openjdk-8-jdk maven

RUN git clone https://github.com/SDUOJ/sduoj-sandbox.git \
 && cd sduoj-sandbox \
 && make \
 && make install

COPY mavenSettings.xml /usr/share/maven/conf/settings.xml

ENV CORE_NUM=1
ENV NACOS_ADDR=nacos.oj.qd.sdu.edu.cn:8848
ENV ACTIVE=prod

RUN mkdir /sduoj \
 && wget -O /sduoj/server.zip https://codeload.github.com/SDUOJ/sduoj-server/zip/master \
 && wget -O /sduoj/judger.zip https://codeload.github.com/SDUOJ/sduoj-judger/zip/master \
 && unzip -o -q -d /sduoj /sduoj/server.zip \
 && unzip -o -q -d /sduoj /sduoj/judger.zip \
 && cd /sduoj/sduoj-server-master \
 && mvn install \
 && cd /sduoj/sduoj-judger-master \
 && mvn package \
 && mv sduoj-judger-service/target/sduoj-judger.jar ../sduoj-judger.jar \
 && rm -rf ~/.m2 \
 && rm -rf /sduoj/sduoj-server-master \
 && rm -rf /sduoj/sduoj-judger-master \
 && apt-get purge -y maven

WORKDIR /sduoj
CMD java -jar sduoj-judger.jar --sduoj.judger.core-num=$CORE_NUM --sduoj.config.nacos-addr=$NACOS_ADDR --sduoj.config.active=$ACTIVE > /sduoj/sduoj.log
