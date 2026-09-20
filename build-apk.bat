@echo off
setlocal enabledelayedexpansion

echo ========================================
echo    AI学 - APK 一键打包脚本
echo ========================================
echo.

:: ===== 配置 =====
set "PROJECT_DIR=%~dp0"
set "ANDROID_PROJECT=%PROJECT_DIR%android-build"
set "APP_ID=com.aixue.app"
set "APP_NAME=AI学"
set "MIN_SDK=24"
set "TARGET_SDK=34"
set "COMPILE_SDK=34"

:: ===== 检查 Java =====
echo [1/7] 检查环境...
java -version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Java，请安装 JDK 8 或更高版本
    pause
    exit /b 1
)
echo   Java: OK

:: ===== 检查 Android SDK =====
if "%ANDROID_HOME%"=="" (
    if exist "%LOCALAPPDATA%\Android\Sdk" (
        set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
    ) else if exist "C:\Android\Sdk" (
        set "ANDROID_HOME=C:\Android\Sdk"
    )
)
if "%ANDROID_HOME%"=="" (
    echo [错误] 未找到 Android SDK，请设置 ANDROID_HOME 环境变量
    pause
    exit /b 1
)
echo   Android SDK: %ANDROID_HOME%

:: ===== 检查前端文件 =====
if not exist "%PROJECT_DIR%prototype\chat.html" (
    echo [错误] 未找到前端文件 prototype\chat.html
    pause
    exit /b 1
)
echo   前端文件: OK

:: ===== 输入后端 API 地址 =====
echo.
echo [2/7] 配置后端 API 地址
echo   注意：APK 安装到手机后，localhost 指向手机本身
echo   局域网测试请输入电脑 IP，如 http://192.168.1.100:8000
echo   服务器部署请输入服务器地址，如 https://api.example.com
echo.
set /p "API_BASE=请输入后端 API 地址 (默认 http://10.0.2.2:8000 模拟器用): "
if "%API_BASE%"=="" set "API_BASE=http://10.0.2.2:8000"
echo   API 地址: %API_BASE%

:: ===== 创建项目目录 =====
echo.
echo [3/7] 创建 Android 项目结构...
if exist "%ANDROID_PROJECT%" (
    echo   清理旧项目...
    rmdir /s /q "%ANDROID_PROJECT%"
)

mkdir "%ANDROID_PROJECT%\app\src\main\java\com\aixue\app"
mkdir "%ANDROID_PROJECT%\app\src\main\res\values"
mkdir "%ANDROID_PROJECT%\app\src\main\assets"
mkdir "%ANDROID_PROJECT%\gradle\wrapper"
echo   目录结构: OK

:: ===== 生成配置文件 =====
echo.
echo [4/7] 生成配置文件...

:: settings.gradle
(
echo pluginManagement {
echo     repositories {
echo         google^()
echo         mavenCentral^()
echo         gradlePluginPortal^()
echo     }
echo }
echo dependencyResolutionManagement {
echo     repositoriesMode.set^(RepositoriesMode.FAIL_ON_PROJECT_REPOS^)
echo     repositories {
echo         google^()
echo         mavenCentral^()
echo     }
echo }
echo rootProject.name = "%APP_NAME%"
echo include ':app'
) > "%ANDROID_PROJECT%\settings.gradle"

:: build.gradle (项目级)
(
echo plugins {
echo     id 'com.android.application' version '8.1.0' apply false
echo }
) > "%ANDROID_PROJECT%\build.gradle"

:: gradle.properties
(
echo org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
echo android.useAndroidX=true
echo android.nonTransitiveRClass=true
) > "%ANDROID_PROJECT%\gradle.properties"

:: app/build.gradle
(
echo plugins {
echo     id 'com.android.application'
echo }
echo android {
echo     namespace '%APP_ID%'
echo     compileSdk %COMPILE_SDK%
echo     defaultConfig {
echo         applicationId "%APP_ID%"
echo         minSdk %MIN_SDK%
echo         targetSdk %TARGET_SDK%
echo         versionCode 1
echo         versionName "1.0"
echo     }
echo     buildTypes {
echo         release {
echo             minifyEnabled false
echo             proguardFiles getDefaultProguardFile^('proguard-android-optimize.txt'^), 'proguard-rules.pro'
echo         }
echo     }
echo     compileOptions {
echo         sourceCompatibility JavaVersion.VERSION_1_8
echo         targetCompatibility JavaVersion.VERSION_1_8
echo     }
echo }
echo dependencies {
echo     implementation 'androidx.appcompat:appcompat:1.6.1'
echo }
) > "%ANDROID_PROJECT%\app\build.gradle"

:: AndroidManifest.xml
(
echo ^<?xml version="1.0" encoding="utf-8"?^>
echo ^<manifest xmlns:android="http://schemas.android.com/apk/res/android"^>
echo     ^<uses-permission android:name="android.permission.INTERNET" /^>
echo     ^<application
echo         android:allowBackup="true"
echo         android:icon="@mipmap/ic_launcher"
echo         android:label="@string/app_name"
echo         android:roundIcon="@mipmap/ic_launcher_round"
echo         android:supportsRtl="true"
echo         android:usesCleartextTraffic="true"
echo         android:theme="@style/Theme.AIXue"^>
echo         ^<activity
echo             android:name=".MainActivity"
echo             android:exported="true"
echo             android:configChanges="orientation|screenSize|keyboardHidden"^>
echo             ^<intent-filter^>
echo                 ^<action android:name="android.intent.action.MAIN" /^>
echo                 ^<category android:name="android.intent.category.LAUNCHER" /^>
echo             ^</intent-filter^>
echo         ^</activity^>
echo     ^</application^>
echo ^</manifest^>
) > "%ANDROID_PROJECT%\app\src\main\AndroidManifest.xml"

:: MainActivity.java
(
echo package com.aixue.app;
echo.
echo import android.annotation.SuppressLint;
echo import android.os.Bundle;
echo import android.webkit.WebChromeClient;
echo import android.webkit.WebSettings;
echo import android.webkit.WebView;
echo import android.webkit.WebViewClient;
echo import androidx.appcompat.app.AppCompatActivity;
echo.
echo public class MainActivity extends AppCompatActivity {
echo     private WebView webView;
echo.
echo     @SuppressLint^("SetJavaScriptEnabled"^)
echo     @Override
echo     protected void onCreate^(Bundle savedInstanceState^) {
echo         super.onCreate^(savedInstanceState^);
echo         webView = new WebView^(this^);
echo         setContentView^(webView^);
echo.
echo         WebSettings settings = webView.getSettings^();
echo         settings.setJavaScriptEnabled^(true^);
echo         settings.setDomStorageEnabled^(true^);
echo         settings.setAllowFileAccess^(true^);
echo         settings.setAllowContentAccess^(true^);
echo         settings.setLoadWithOverviewMode^(true^);
echo         settings.setUseWideViewPort^(true^);
echo         settings.setBuiltInZoomControls^(false^);
echo         settings.setCacheMode^(WebSettings.LOAD_DEFAULT^);
echo         settings.setMixedContentMode^(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW^);
echo.
echo         webView.setWebViewClient^(new WebViewClient^()^);
echo         webView.setWebChromeClient^(new WebChromeClient^()^);
echo         webView.loadUrl^("file:///android_asset/chat.html"^);
echo     }
echo.
echo     @Override
echo     public void onBackPressed^() {
echo         if ^(webView.canGoBack^()^) webView.goBack^();
echo         else super.onBackPressed^();
echo     }
echo }
) > "%ANDROID_PROJECT%\app\src\main\java\com\aixue\app\MainActivity.java"

:: strings.xml
(
echo ^<resources^>
echo     ^<string name="app_name"^>%APP_NAME%^</string^>
echo ^</resources^>
) > "%ANDROID_PROJECT%\app\src\main\res\values\strings.xml"

:: themes.xml
(
echo ^<resources^>
echo     ^<style name="Theme.AIXue" parent="Theme.MaterialComponents.DayNight.NoActionBar"^>
echo         ^<item name="colorPrimary"^>#3E63DD^</item^>
echo         ^<item name="colorPrimaryVariant"^>#2A4CB8^</item^>
echo         ^<item name="colorOnPrimary"^>#FFFFFF^</item^>
echo     ^</style^>
echo ^</resources^>
) > "%ANDROID_PROJECT%\app\src\main\res\values\themes.xml"

echo   配置文件: OK

:: ===== 复制前端文件 =====
echo.
echo [5/7] 复制前端文件到 assets...
xcopy /E /I /Y /Q "%PROJECT_DIR%prototype\*" "%ANDROID_PROJECT%\app\src\main\assets\" >nul
echo   前端文件: OK

:: ===== 修改 API 地址 =====
echo   修改 API 地址为: %API_BASE%
powershell -Command "(Get-Content '%ANDROID_PROJECT%\app\src\main\assets\chat.html' -Raw) -replace 'http://localhost:8000', '%API_BASE%' | Set-Content '%ANDROID_PROJECT%\app\src\main\assets\chat.html' -NoNewline"
echo   API 地址: OK

:: ===== 生成 Gradle Wrapper =====
echo.
echo [6/7] 生成 Gradle Wrapper...

:: gradle-wrapper.properties
(
echo distributionBase=GRADLE_USER_HOME
echo distributionPath=wrapper/dists
echo distributionUrl=https\://services.gradle.org/distributions/gradle-8.0-bin.zip
echo networkTimeout=10000
echo validateDistributionUrl=true
echo zipStoreBase=GRADLE_USER_HOME
echo zipStorePath=wrapper/dists
) > "%ANDROID_PROJECT%\gradle\wrapper\gradle-wrapper.properties"

:: 检查是否有 gradle 命令
where gradle >nul 2>&1
if not errorlevel 1 (
    echo   使用系统 gradle 生成 wrapper...
    pushd "%ANDROID_PROJECT%"
    gradle wrapper --gradle-version 8.0 >nul 2>&1
    popd
    echo   Gradle Wrapper: OK
) else (
    echo   未找到系统 gradle，尝试下载 wrapper jar...
    echo   请确保网络可访问 services.gradle.org
)

:: ===== 构建 APK =====
echo.
echo [7/7] 构建 APK...

if exist "%ANDROID_PROJECT%\gradlew.bat" (
    echo   使用 Gradle Wrapper 构建...
    pushd "%ANDROID_PROJECT%"
    call gradlew.bat assembleDebug --no-daemon
    set BUILD_RESULT=%ERRORLEVEL%
    popd
) else (
    echo.
    echo ========================================
    echo   无法自动构建（缺少 Gradle Wrapper）
    echo   请用 Android Studio 打开项目手动构建:
    echo   项目路径: %ANDROID_PROJECT%
    echo   1. Android Studio → Open → 选择上述目录
    echo   2. 等待 Gradle 同步完成
    echo   3. Build → Build Bundle(s)/APK(s) → Build APK(s)
    echo   4. 构建完成后点击 locate 找到 APK
    echo ========================================
    echo.
    echo 项目已生成完毕，按任意键打开项目目录...
    pause
    explorer "%ANDROID_PROJECT%"
    exit /b 0
)

if "%BUILD_RESULT%"=="0" (
    echo.
    echo ========================================
    echo   APK 构建成功！
    echo ========================================
    echo   APK 路径: %ANDROID_PROJECT%\app\build\outputs\apk\debug\app-debug.apk
    echo.
    echo   安装到手机: adb install -r "%ANDROID_PROJECT%\app\build\outputs\apk\debug\app-debug.apk"
    echo ========================================
    echo.
    choice /c YN /m "是否打开 APK 所在目录"
    if errorlevel 2 exit /b 0
    explorer "%ANDROID_PROJECT%\app\build\outputs\apk\debug"
) else (
    echo.
    echo ========================================
    echo   APK 构建失败，错误码: %BUILD_RESULT%
    echo ========================================
    echo   可能原因:
    echo   1. Gradle 依赖下载失败（检查网络）
    echo   2. Android SDK Build-tools 未安装
    echo   3. Java 版本不兼容（需要 JDK 11+）
    echo.
    echo   建议用 Android Studio 打开项目查看详细错误:
    echo   项目路径: %ANDROID_PROJECT%
    echo ========================================
    echo.
    pause
)

endlocal
