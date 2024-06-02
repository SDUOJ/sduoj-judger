#!/bin/bash

set -eux

# Check if the argument is provided
if [ $# -ne 1 ]; then
  echo "Usage: $0 true|false"
  exit 0
fi

if [ $1 == "true" ]; then
cat << "EOF" > /etc/apt/sources.list
deb http://mirrors.aliyun.com/ubuntu/ bionic main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ bionic-security main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ bionic-updates main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ bionic-backports main restricted universe multiverse
EOF
fi
