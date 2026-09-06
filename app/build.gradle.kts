import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

val supabaseEnvironment = providers.gradleProperty("supabaseEnvironment")
    .orElse("local")
    .get()
    .trim()
    .lowercase()
if (supabaseEnvironment != "local" && supabaseEnvironment != "hosted") {
    throw GradleException(
        "Unsupported supabaseEnvironment='$supabaseEnvironment'. Use 'local' or 'hosted'.",
    )
}

val supabasePropertiesFile = rootProject.file(
    if (supabaseEnvironment == "hosted") "local.hosted.properties" else "local.properties",
)
if (supabaseEnvironment == "hosted" && !supabasePropertiesFile.isFile) {
    throw GradleException(
        "supabaseEnvironment=hosted requires ${supabasePropertiesFile.absolutePath}. " +
            "Run scripts\\connect-hosted-supabase-device.ps1 first.",
    )
}

val supabaseProperties = Properties().apply {
    if (supabasePropertiesFile.isFile) {
        supabasePropertiesFile.inputStream().use(::load)
    }
}

fun buildConfigValue(name: String): String {
    val fileValue = supabaseProperties.getProperty(name)?.trim().orEmpty()
    return fileValue.ifBlank { System.getenv(name)?.trim().orEmpty() }
}

val supabaseUrl = buildConfigValue("SUPABASE_URL")
val supabasePublishableKey = supabaseProperties.getProperty("SUPABASE_PUBLISHABLE_KEY")
    ?.trim()
    .orEmpty()
    .ifBlank {
        supabaseProperties.getProperty("SUPABASE_ANON_KEY")?.trim().orEmpty()
    }
    .ifBlank {
        System.getenv("SUPABASE_PUBLISHABLE_KEY")?.trim().orEmpty()
    }
    .ifBlank {
        System.getenv("SUPABASE_ANON_KEY")?.trim().orEmpty()
    }

if (supabaseEnvironment == "hosted") {
    if (supabaseUrl.isBlank()) {
        throw GradleException(
            "Hosted Supabase URL is empty in ${supabasePropertiesFile.absolutePath} " +
                "and SUPABASE_URL is not set in the environment.",
        )
    }
    if (supabasePublishableKey.isBlank()) {
        throw GradleException(
            "Hosted Supabase client key is empty in ${supabasePropertiesFile.absolutePath}. " +
                "Set SUPABASE_PUBLISHABLE_KEY (or legacy SUPABASE_ANON_KEY).",
        )
    }
}

fun quoteBuildConfig(value: String): String = "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

android {
    namespace = "com.ffocalors.sharedledger"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.ffocalors.sharedledger"
        minSdk = 30
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "SUPABASE_URL", quoteBuildConfig(supabaseUrl))
        buildConfigField(
            "String",
            "SUPABASE_PUBLISHABLE_KEY",
            quoteBuildConfig(supabasePublishableKey),
        )
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        buildConfig = true
        compose = true
    }
}

dependencies {
    implementation(platform(libs.supabase.bom))
    implementation(libs.supabase.core)
    implementation(libs.supabase.auth)
    implementation(libs.supabase.postgrest)
    implementation(libs.ktor.client.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.extended)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}
