# FROM python:3.7-alpine3.9
FROM ubuntu:18.04
MAINTAINER SDUOJ-dev

# # sduoj-sandbox
# RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apk/repositories && \
#     apk add --update alpine-sdk libseccomp-dev && \
#     git clone https://github.com/SDUOJ/sduoj-sandbox.git && \
#     cd sduoj-sandbox && make && make install
RUN sed -i s/archive.ubuntu.com/mirrors.aliyun.com/g /etc/apt/sources.list \
    && sed -i s/security.ubuntu.com/mirrors.aliyun.com/g /etc/apt/sources.list \
    && apt-get update && apt-get install -y libseccomp-dev libseccomp2 seccomp build-essential python3-pip git && \
    git clone https://github.com/SDUOJ/sduoj-sandbox.git && \
    cd sduoj-sandbox && make && make install


# sduoj-judger
RUN git clone https://github.com/SDUOJ/sduoj-judger.git && \
    cd sduoj-judger && \
    pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple some-package \
                 -r requirements.txt
WORKDIR /sduoj-judger

CMD ["python3", "-m", "judger.server"]