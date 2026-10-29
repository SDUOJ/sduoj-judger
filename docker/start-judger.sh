#!/bin/sh
/wait                                                          \
 && JAVA_OPT="${JAVA_OPT} -jar sduoj-judger.jar"                   \
 && JAVA_OPT="${JAVA_OPT} ${JAVA_OPT_EXT}"                         \
 && JAVA_OPT="${JAVA_OPT} --sduoj.config.active=$ACTIVE"           \
 && JAVA_OPT="${JAVA_OPT} --sduoj.config.nacos-addr=$NACOS_ADDR"   \
 && echo "SDUOJ is starting. Logs are in '/app/logs/judger.log'"   \
 && echo "Run: java ${JAVA_OPT}"                                   \
 && mkdir -p /app/logs                                             \
 && exec java ${JAVA_OPT} >> /app/logs/judger.log 2>&1
