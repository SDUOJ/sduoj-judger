#!/bin/bash

set -eux

dpkgArch="$(dpkg --print-architecture)"

# install pypy3.10-v7.3.15
case "${dpkgArch##*-}" in
	'amd64')
		url='https://downloads.python.org/pypy/pypy3.10-v7.3.15-linux64.tar.bz2'
		sha256='33c584e9a70a71afd0cb7dd8ba9996720b911b3b8ed0156aea298d4487ad22c3'
		;;
	'arm64')
		url='https://downloads.python.org/pypy/pypy3.10-v7.3.15-aarch64.tar.bz2'
		sha256='52146fccaf64e87e71d178dda8de63c01577ec3923073dc69e1519622bcacb74'
		;;
	'i386')
		url='https://downloads.python.org/pypy/pypy3.10-v7.3.15-linux32.tar.bz2'
		sha256='75dd58c9abd8b9d78220373148355bc3119febcf27a2c781d64ad85e7232c4aa'
		;;
	's390x')
		url='https://downloads.python.org/pypy/pypy3.10-v7.3.15-s390x.tar.bz2'
		sha256='209e57596381e13c9914d1332f359dc4b78de06576739747eb797bdbf85062b8'
		;;
	*)
		echo >&2 "error: current architecture ($dpkgArch) does not have a corresponding PyPy $PYPY_VERSION binary release"
		exit 1
		;;
esac
wget -O pypy.tar.bz2 "$url" --progress=dot:giga
echo "$sha256 *pypy.tar.bz2" | sha256sum --check --strict -
mkdir -p /opt/pypy/3.10
tar -xjC /opt/pypy/3.10 --strip-components=1 -f pypy.tar.bz2
