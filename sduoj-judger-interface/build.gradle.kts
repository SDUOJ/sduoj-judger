plugins {
    id("cn.edu.sdu.qd.oj.judger.java-conventions")
}

dependencies {
    /* 1-st party dependency */

    /* 2-nd party dependency */
    api("cn.edu.sdu.qd.oj.submit:sduoj-submit-interface:${Versions.sduoj}")

    /* 3-rd party dependency */
    api("org.apache.commons:commons-lang3:${Versions.commonsLang3}")
    api("com.fasterxml.jackson.core:jackson-databind:${Versions.jackson}")
}

description = "sduoj-judger-interface"