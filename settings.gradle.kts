rootProject.name = "sduoj-judger"
include("sduoj-judger-interface")
include("sduoj-judger-service")

// Build this release from its matching reviewed server source, not mutable SNAPSHOTs.
val serverSource = providers.gradleProperty("sduojServerSource").orNull
if (serverSource != null) {
    includeBuild(serverSource) {
        dependencySubstitution {
            substitute(module("com.sduoj.common:sduoj-common-entity")).using(project(":sduoj-common:sduoj-common-entity"))
            substitute(module("com.sduoj.common:sduoj-common-util")).using(project(":sduoj-common:sduoj-common-util"))
            substitute(module("com.sduoj.common:sduoj-common-rpc")).using(project(":sduoj-common:sduoj-common-rpc"))
            substitute(module("com.sduoj.common:sduoj-common-mq")).using(project(":sduoj-common:sduoj-common-mq"))
            substitute(module("com.sduoj.common:sduoj-common-redis")).using(project(":sduoj-common:sduoj-common-redis"))
            substitute(module("com.sduoj.problem:sduoj-problem-interface")).using(project(":sduoj-problem:sduoj-problem-interface"))
            substitute(module("com.sduoj.filesys:sduoj-filesys-interface")).using(project(":sduoj-filesys:sduoj-filesys-interface"))
            substitute(module("com.sduoj.user:sduoj-user-interface")).using(project(":sduoj-user:sduoj-user-interface"))
        }
    }
}
