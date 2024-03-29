/*
 * This file was generated by the Gradle 'init' task.
 */

plugins {
    `java-library`
    `maven-publish`
    id("org.springframework.boot")
    id("io.spring.dependency-management")
}

group = "cn.edu.sdu.qd.oj.judger"
version = Versions.sduoj

java.sourceCompatibility = JavaVersion.VERSION_1_8
java.targetCompatibility = JavaVersion.VERSION_1_8


repositories {
    mavenLocal()
    mavenCentral()
//    maven { url = uri("https://maven.aliyun.com/repository/public/") }
//    maven { url = uri("https://maven.aliyun.com/repository/spring/") }
}

dependencies {
    implementation("org.projectlombok:lombok:${Versions.lombok}")
    annotationProcessor("org.projectlombok:lombok:${Versions.lombok}")
}


dependencyManagement {
    imports {
        mavenBom("org.springframework.cloud:spring-cloud-dependencies:${Versions.springCloud}")
        mavenBom("com.alibaba.cloud:spring-cloud-alibaba-dependencies:${Versions.springCloudAlibaba}")
    }
}

allprojects {
    val projectName = this.name
    val isService = projectName.contains(Regex("-(service)$"))
    if (isService) {
        tasks.bootJar {
            enabled = true
            archiveName = projectName.replace("-service", "") + ".jar"
        }
        tasks.jar {
            enabled = false
        }
    } else {
        tasks.bootJar {
            enabled = false
        }
        tasks.jar {
            enabled = true
        }
        publishing {
            publications.create<MavenPublication>("maven") {
                artifact(tasks.jar)
            }
        }
    }
}

tasks.withType<JavaCompile>() {
    options.encoding = "UTF-8"
}
