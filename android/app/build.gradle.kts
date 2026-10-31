plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.meuapp.segundatela"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.meuapp.segundatela"
        minSdk = 26 // ícone adaptativo sem PNG de fallback
        targetSdk = 35
        versionCode = 2
        versionName = "1.1"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
