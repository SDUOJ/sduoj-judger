plugins {
    id("cn.edu.sdu.qd.oj.judger.java-conventions")
}

dependencies {
    /* 1-st party dependency */
    implementation(project(":sduoj-judger-interface"))
    implementation(files("/Users/rajeev/Desktop/judge_experiments/SDUOJ/sduoj-server/sduoj-common/sduoj-common-entity/build/libs/sduoj-common-entity-0.0.1-SNAPSHOT.jar"))
    implementation(files("/Users/rajeev/Desktop/judge_experiments/SDUOJ/sduoj-server/sduoj-common/sduoj-common-util/build/libs/sduoj-common-util-0.0.1-SNAPSHOT.jar"))

    /* 2-nd party dependency */
    implementation(files("/Users/rajeev/Desktop/judge_experiments/SDUOJ/sduoj-server/sduoj-problem/sduoj-problem-interface/build/libs/sduoj-problem-interface-0.0.1-SNAPSHOT.jar"))
    implementation(files("/Users/rajeev/Desktop/judge_experiments/SDUOJ/sduoj-server/sduoj-submit/sduoj-submit-interface/build/libs/sduoj-submit-interface-0.0.1-SNAPSHOT.jar"))
    implementation(files("/Users/rajeev/Desktop/judge_experiments/SDUOJ/sduoj-server/sduoj-filesys/sduoj-filesys-interface/build/libs/sduoj-filesys-interface-0.0.1-SNAPSHOT.jar"))

    /* 3-rd party dependency */
    implementation("org.springframework.cloud:spring-cloud-starter-netflix-ribbon")
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