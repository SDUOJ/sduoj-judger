FROM ubuntu:18.04
MAINTAINER SDUOJ-Team

ENV LANG C.UTF-8

COPY docker/sources.list /etc/apt/sources.list
COPY docker/mavenSettings.xml /usr/share/maven/conf/settings.xml
COPY docker/testlib /testlib.h
COPY docker/checkers/ /checkers/

ADD https://github.com/SDUOJ/docker-compose-wait/releases/download/2.7.3/wait /wait
RUN mkdir /sduoj \
 && chmod +x /wait

# install OS software
RUN apt-get update \
 && apt-get install -y make=4.1-9.1ubuntu1   dosbox=0.74-4.3   cmake \
                       sudo git unzip wget libseccomp-dev libseccomp2 seccomp build-essential \
                       python3-pip python vim dos2unix openjdk-8-jdk maven \
 && mkdir /usr/share/maven/conf/logging \
 && ln -sf /usr/lib/jvm/java-8-openjdk-amd64/bin/java /usr/bin/java \
 && ln -sf /usr/lib/jvm/java-8-openjdk-amd64/bin/javac /usr/bin/javac

# compile and install sduoj-sandbox
RUN wget -O /sduoj/sandbox.zip https://codeload.github.com/SDUOJ/sduoj-sandbox/zip/master \
 && unzip -o -q -d /sduoj /sduoj/sandbox.zip \
 && cd /sduoj/sduoj-sandbox-master \
 && make \
 && make install

# download source code
RUN wget -O /sduoj/server.zip https://codeload.github.com/SDUOJ/sduoj-server/zip/master \
 && wget -O /sduoj/judger.zip https://codeload.github.com/SDUOJ/sduoj-judger/zip/migrate-maven-to-gradle \
 && unzip -o -q -d /sduoj/dockerWorkspace /sduoj/server.zip \
 && unzip -o -q -d /sduoj/dockerWorkspace /sduoj/judger.zip \
 && rm /sduoj/*.zip

# compile and install sduoj-server
RUN cd /sduoj/dockerWorkspace/sduoj-server* \
 && mvn install -Dmaven.test.skip=true

# compile sduoj-judger
RUN cd /sduoj/dockerWorkspace/sduoj-judger* \
 && chmod +x ./gradlew \
 && ./gradlew build \
 && mv ./sduoj-judger-service/build/libs/sduoj-judger.jar /sduoj/sduoj-judger.jar

# clean
RUN rm -rf ~/.m2 \
 && rm -rf ~/.gradle \
 && rm -rf /sduoj/dockerWorkspace \
 && apt-get purge -y maven

ENV NACOS_ADDR=nacos.oj.qd.sdu.edu.cn:8848
ENV ACTIVE=prod

WORKDIR /sduoj

CMD /wait \
 && java -jar sduoj-judger.jar \
         --sduoj.config.nacos-addr=$NACOS_ADDR \
         --sduoj.config.active=$ACTIVE \
         >> /sduoj/sduoj.log
