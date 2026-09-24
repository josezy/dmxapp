plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "org.deovolente.beam"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.deovolente.beam"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "2.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    testOptions {
        unitTests.isIncludeAndroidResources = false
    }

    sourceSets {
        getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/assets"))
    }
}

val copySequences by tasks.registering(Copy::class) {
    from(rootProject.projectDir.resolve("../beam-halo-duo/sequences"))
    into(layout.buildDirectory.dir("generated/assets/sequences"))
    include("*.json")
}

val copyShow by tasks.registering(Copy::class) {
    from(rootProject.projectDir.resolve("../beam-halo-duo/show.json"))
    into(layout.buildDirectory.dir("generated/assets"))
}

val copyShowCatalog by tasks.registering(Copy::class) {
    from(rootProject.projectDir.resolve("../show"))
    into(layout.buildDirectory.dir("generated/assets/show"))
    include("looks.json", "palettes.json")
}

val copyLpcSequences by tasks.registering(Copy::class) {
    from(rootProject.projectDir.resolve("../lpc008-duo/sequences"))
    into(layout.buildDirectory.dir("generated/assets/lpc-sequences"))
    include(
        "breathe-calida.json",
        "strobe-primario-medio.json",
        "chase-primario-medio.json",
        "fade-medio.json",
        "relampago-blanco.json",
    )
}

tasks.named("preBuild") {
    dependsOn(copySequences, copyShow, copyShowCatalog, copyLpcSequences)
}
tasks.configureEach {
    if (name.startsWith("merge") && name.endsWith("Assets")) {
        dependsOn(copySequences, copyShow, copyShowCatalog, copyLpcSequences)
    }
}

val seqDir = rootProject.projectDir.resolve("../beam-halo-duo/sequences").absolutePath
val goldenDir = layout.projectDirectory.dir("src/test/resources/goldens").asFile.absolutePath

tasks.withType<Test>().configureEach {
    environment("BEAM_SEQ_DIR", seqDir)
    environment("BEAM_GOLDEN_DIR", goldenDir)
    environment("SHOW_DIR", rootProject.projectDir.resolve("../show").absolutePath)
    environment("LPC_SEQ_DIR", rootProject.projectDir.resolve("../lpc008-duo/sequences").absolutePath)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
