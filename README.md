# sduoj-judger
Fetch the code, compile and run it, and return the result.

## Get started
Make sure `Docker v19.03.7` or higher version is installed.

## Run

* pull image: 
```sh
docker pull registry.cn-beijing.aliyuncs.com/sduoj/sduoj-judger
```

* Run it:
```sh
docker run -di \
  --name=sduoj-judger \
  --cpuset-cpus="0" \
  -e CORE_NUM=1 \
  -e NACOS_ADDR=127.0.0.1:8848 \
  -e ACTIVE=prod \
  registry.cn-beijing.aliyuncs.com/sduoj/sduoj-judger
```

* Docker parms:
    * `CORE_NUM` and `--cpuset-cpus`: the number of cpu
    * `NACOS_ADDR`: the host of Nacos
    * `ACTIVE`:`dev` or `prod`