plugins {
    alias(libs.plugins.android.application)
}

android {
    enableKotlin = false
    namespace = "com.kartik.vista"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.kartik.vista"
        // WFF version 2 requires Wear OS 5 / API 34, which is what Galaxy Watch 7 launched with.
        minSdk = 34
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        debug {
            isMinifyEnabled = true
        }
        release {
            isMinifyEnabled = true
            // Keep every raw/drawable resource. WFF packages are resource-only.
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}
