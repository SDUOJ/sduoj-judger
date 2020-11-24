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
  --pids-limit=1024 \
  --cpuset-cpus="0" \
  --cpu-shares=100 \
  --memory=1024M \
  --memory-swap=1024M \
  -e NACOS_ADDR=127.0.0.1:8848 \
  -e ACTIVE=prod \
  registry.cn-beijing.aliyuncs.com/sduoj/sduoj-judger
```

* Docker parms:
    * `--pids-limit`: the limit of process in container
    * `--cpuset-cpus`: the settings of cpu
    * `--cpu-shares`: the relative weight of cpu
    * `NACOS_ADDR`: the host of Nacos
    * `ACTIVE`: `dev` or `prod`