plugins {
    id("com.sduoj.judger.java-conventions")
}

dependencies {
    /* 1-st party dependency */
    api("com.sduoj.common:sduoj-common-entity:${Versions.sduoj}")

    /* 2-nd party dependency */
    api("com.sduoj.problem:sduoj-problem-interface:${Versions.sduoj}")

    /* 3-rd party dependency */
    api("org.apache.commons:commons-lang3:${Versions.commonsLang3}")
    api("com.fasterxml.jackson.core:jackson-databind")
}

description = "sduoj-judger-interface"