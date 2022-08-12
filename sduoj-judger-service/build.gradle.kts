plugins {
    id("cn.edu.sdu.qd.oj.judger.java-conventions")
}

dependencies {
    /* 1-st party dependency */
    implementation(project(":sduoj-judger-interface"))
    implementation("cn.edu.sdu.qd.oj.common:sduoj-common-util:${Versions.sduoj}")
    implementation("cn.edu.sdu.qd.oj.common:sduoj-common-rpc:${Versions.sduoj}")
    implementation("cn.edu.sdu.qd.oj.common:sduoj-common-mq:${Versions.sduoj}")

    /* 2-nd party dependency */
    implementation("cn.edu.sdu.qd.oj.filesys:sduoj-filesys-interface:${Versions.sduoj}")

    /* 3-rd party dependency */
    implementation("com.alibaba.cloud:spring-cloud-starter-alibaba-nacos-config")
    implementation("org.springframework:spring-aop")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.springframework.boot:spring-boot-starter")
    implementation("org.springframework.boot:spring-boot-configuration-processor")
    implementation("org.springframework.cloud:spring-cloud-starter-bootstrap")
}

description = "sduoj-judger-service"