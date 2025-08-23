plugins {
    id("cn.edu.sdu.qd.oj.judger.java-conventions")
}

dependencies {
    /* 1-st party dependency */

    /* 2-nd party dependency */
    api(files("/Users/rajeev/Desktop/judge_experiments/SDUOJ/sduoj-server/sduoj-submit/sduoj-submit-interface/build/libs/sduoj-submit-interface-0.0.1-SNAPSHOT.jar"))

    /* 3-rd party dependency */
    api("org.apache.commons:commons-lang3:${Versions.commonsLang3}")
    api("com.fasterxml.jackson.core:jackson-databind:${Versions.jackson}")
}

description = "sduoj-judger-interface"