plugins {
    id("cn.edu.sdu.qd.oj.judger.java-conventions")
    id("maven-publish")
}

dependencies {
    /* 1-st party dependency */

    /* 2-nd party dependency */
    api("cn.edu.sdu.qd.oj.submit:sduoj-submit-interface:${Versions.sduoj}")

    /* 3-rd party dependency */
    api("org.apache.commons:commons-lang3:${Versions.commonsLang3}")
    api("com.fasterxml.jackson.core:jackson-databind:${Versions.jackson}")
}

publishing {
    publications.create<MavenPublication>("maven") {
        artifact(tasks.jar)
    }
}

description = "sduoj-judger-interface"