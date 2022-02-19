plugins {
    id("cn.edu.sdu.qd.oj.judger.java-conventions")
    id("org.springframework.boot") version Versions.springBoot
}

dependencies {
    /* 1-st party dependency */
    implementation(project(":sduoj-judger-interface"))
    implementation("cn.edu.sdu.qd.oj.common:sduoj-common-entity:${Versions.sduoj}")
    implementation("cn.edu.sdu.qd.oj.common:sduoj-common-util:${Versions.sduoj}")

    /* 2-nd party dependency */
    implementation("cn.edu.sdu.qd.oj.problem:sduoj-problem-interface:${Versions.sduoj}")
    implementation("cn.edu.sdu.qd.oj.submit:sduoj-submit-interface:${Versions.sduoj}")
    implementation("cn.edu.sdu.qd.oj.filesys:sduoj-filesys-interface:${Versions.sduoj}")

    /* 3-rd party dependency */
    implementation("com.alibaba.cloud:spring-cloud-starter-alibaba-nacos-config")
    implementation("com.alibaba.cloud:spring-cloud-starter-alibaba-nacos-discovery")
    implementation("org.springframework.cloud:spring-cloud-starter-openfeign")
    implementation("org.springframework:spring-aop")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.springframework.boot:spring-boot-starter")
    implementation("org.springframework.boot:spring-boot-configuration-processor")
    implementation("org.springframework.amqp:spring-rabbit")
    implementation("com.google.guava:guava:${Versions.guava}")
    implementation("com.alibaba:fastjson:${Versions.fastjson}")
    implementation("org.aspectj:aspectjrt:${Versions.aspectj}")
    implementation("org.apache.httpcomponents:fluent-hc:${Versions.httpclient}")
    implementation("org.apache.httpcomponents:httpclient:${Versions.httpclient}")
}

description = "sduoj-judger-service"

tasks.bootJar {
    archiveName = "sduoj-judger.jar"
}