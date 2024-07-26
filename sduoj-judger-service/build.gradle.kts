plugins {
    id("com.sduoj.judger.java-conventions")
}

dependencies {
    /* 1-st party dependency */
    implementation(project(":sduoj-judger-interface"))
    implementation("com.sduoj.common:sduoj-common-util:${Versions.sduoj}")
    implementation("com.sduoj.common:sduoj-common-rpc:${Versions.sduoj}")
    implementation("com.sduoj.common:sduoj-common-mq:${Versions.sduoj}")

    /* 2-nd party dependency */
    implementation("com.sduoj.filesys:sduoj-filesys-interface:${Versions.sduoj}")

    /* 3-rd party dependency */
    implementation("com.alibaba.cloud:spring-cloud-starter-alibaba-nacos-config")
    implementation("org.springframework:spring-aop")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.springframework.boot:spring-boot-starter")
    implementation("org.springframework.boot:spring-boot-configuration-processor")
    implementation("org.springframework.cloud:spring-cloud-starter-bootstrap")
    testImplementation("junit:junit")
}

description = "sduoj-judger-service"
