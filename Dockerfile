FROM ubuntu:18.04
MAINTAINER SDUOJ-Team

ENV LANG C.UTF-8

COPY docker/sources.list /etc/apt/sources.list
COPY docker/testlib /testlib.h

# download docker-compose-wait
COPY --from=sduoj/docker-compose-wait:latest /wait /wait

RUN mkdir -p /sduoj/dockerWorkspace

# install JDKs
ENV JAVA_HOME=/opt/java/openjdk
COPY --from=eclipse-temurin:8 $JAVA_HOME ${JAVA_HOME}8
#COPY --from=eclipse-temurin:17 $JAVA_HOME ${JAVA_HOME}17
# set the default JDK to JDK8
ENV JAVA_HOME=/opt/java/openjdk8
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# install OS softwares
RUN apt-get update \
 && apt-get install -qq -y \
                    make=4.1-9.1ubuntu1   dosbox=0.74-4.3 cmake \
                    sudo git unzip wget libseccomp-dev libseccomp2 seccomp build-essential \
                    python3-pip python vim dos2unix

# compile and install sduoj-sandbox
RUN wget -q -O /sduoj/sandbox.zip https://codeload.github.com/SDUOJ/sduoj-sandbox/zip/master \
 && unzip -o -q -d /sduoj /sduoj/sandbox.zip \
 && rm /sduoj/sandbox.zip \
 && cd /sduoj/sduoj-sandbox* \
 && make \
 && make install

# download source code
RUN wget -q -O /sduoj/server.zip https://codeload.github.com/SDUOJ/sduoj-server/zip/stable \
 && wget -q -O /sduoj/judger.zip https://codeload.github.com/SDUOJ/sduoj-judger/zip/stable \
 && unzip -o -q -d /sduoj/dockerWorkspace /sduoj/server.zip \
 && unzip -o -q -d /sduoj/dockerWorkspace /sduoj/judger.zip \
 && rm /sduoj/server.zip \
 && rm /sduoj/judger.zip

# compile and install sduoj-server
RUN cd /sduoj/dockerWorkspace/sduoj-server* \
 && chmod +x ./gradlew \
 && ./gradlew publishToMavenLocal -x test \
# compile sduoj-judger
 && cd /sduoj/dockerWorkspace/sduoj-judger* \
 && chmod +x ./gradlew \
 && ./gradlew build \
 && mv ./sduoj-judger-service/build/libs/sduoj-judger.jar /sduoj/sduoj-judger.jar \
# clean
 && rm -rf ~/.m2 \
 && rm -rf ~/.gradle \
 && rm -rf /sduoj/dockerWorkspace

ENV ACTIVE=prd

WORKDIR /sduoj

CMD /wait \
 && java -jar sduoj-judger.jar \
         -Dspring.profiles.active=$ACTIVE
