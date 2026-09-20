# AI学 - APK 一键打包脚本 (PowerShell)
# 用法: 右键 -> 使用 PowerShell 运行，或在 PowerShell 中执行 .\build-apk.ps1

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 写入不带 BOM 的 UTF-8 文件（Gradle/Groovy 不支持 BOM）
function Write-Utf8NoBom($path, $content) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($path, $content, $utf8NoBom)
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AI学 - APK 一键打包脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ===== 配置 =====
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AndroidProject = Join-Path $ProjectDir "android-build"
$AppId = "com.aixue.app"
$AppName = "AI学"
$MinSdk = 26
$TargetSdk = 34
$CompileSdk = 34

# ===== 检查 Java =====
Write-Host "[1/7] 检查环境..." -ForegroundColor Yellow
$javaCmd = Get-Command java -ErrorAction SilentlyContinue
if ($javaCmd) {
    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $javaVerOutput = cmd /c "java -version 2>&1" | Out-String
    $ErrorActionPreference = $oldEAP
    if ($javaVerOutput -match 'version "([0-9]+)') {
        $javaMajor = [int]$Matches[1]
        if ($javaMajor -eq 1) {
            if ($javaVerOutput -match 'version "1\.([0-9]+)') { $javaMajor = [int]$Matches[1] }
        }
        Write-Host "  Java: OK (JDK $javaMajor)" -ForegroundColor Green
        if ($javaMajor -lt 11) {
            Write-Host "  [警告] JDK $javaMajor 版本较低，AGP 8.x 需要 JDK 17+" -ForegroundColor Yellow
            Write-Host "  自动构建可能失败，建议用 Android Studio 打开（自带 JDK 17）" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Java: OK" -ForegroundColor Green
    }
} else {
    Write-Host "  [警告] 未找到 Java，自动构建可能失败" -ForegroundColor Yellow
    Write-Host "  建议安装 JDK 17+，或用 Android Studio 打开项目（自带 JDK）" -ForegroundColor Yellow
}

# ===== 检查 Android SDK =====
$AndroidHome = $env:ANDROID_HOME
if (-not $AndroidHome) {
    $candidate = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path $candidate) { $AndroidHome = $candidate }
    elseif (Test-Path "C:\Android\Sdk") { $AndroidHome = "C:\Android\Sdk" }
}
if (-not $AndroidHome) {
    Write-Host "  [错误] 未找到 Android SDK，请设置 ANDROID_HOME 环境变量" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
Write-Host "  Android SDK: $AndroidHome" -ForegroundColor Green
$env:ANDROID_HOME = $AndroidHome

# ===== 检查前端文件 =====
$FrontendFile = Join-Path $ProjectDir "prototype\chat.html"
if (-not (Test-Path $FrontendFile)) {
    Write-Host "  [错误] 未找到前端文件 prototype\chat.html" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
Write-Host "  前端文件: OK" -ForegroundColor Green

# ===== 输入后端 API 地址 =====
Write-Host ""
Write-Host "[2/7] 配置后端 API 地址" -ForegroundColor Yellow
Write-Host "  注意：APK 安装到手机后，localhost 指向手机本身"
Write-Host "  模拟器测试: 直接回车 (默认 http://10.0.2.2:8000)"
Write-Host "  真机局域网: 输入电脑IP，如 http://192.168.3.4:8000"
Write-Host "  服务器部署: 输入服务器公网地址"
Write-Host ""
$ApiBase = Read-Host "请输入后端 API 地址 (默认 http://10.0.2.2:8000)"
if ([string]::IsNullOrWhiteSpace($ApiBase)) { $ApiBase = "http://10.0.2.2:8000" }
Write-Host "  API 地址: $ApiBase" -ForegroundColor Green

# ===== 创建项目目录 =====
Write-Host ""
Write-Host "[3/7] 创建 Android 项目结构..." -ForegroundColor Yellow
if (Test-Path $AndroidProject) {
    Write-Host "  清理旧项目..."
    Remove-Item $AndroidProject -Recurse -Force
}

$Dirs = @(
    "app\src\main\java\com\aixue\app",
    "app\src\main\res\values",
    "app\src\main\assets",
    "gradle\wrapper"
)
foreach ($d in $Dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $AndroidProject $d) | Out-Null
}
Write-Host "  目录结构: OK" -ForegroundColor Green

# ===== 生成配置文件 =====
Write-Host ""
Write-Host "[4/7] 生成配置文件..." -ForegroundColor Yellow

# settings.gradle
$content = @"
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "$AppName"
include ':app'
"@
Write-Utf8NoBom (Join-Path $AndroidProject "settings.gradle") $content

# build.gradle (项目级)
$content = @"
plugins {
    id 'com.android.application' version '8.1.0' apply false
}
"@
Write-Utf8NoBom (Join-Path $AndroidProject "build.gradle") $content

# gradle.properties
$content = @"
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
android.nonTransitiveRClass=true
android.overridePathCheck=true
"@
Write-Utf8NoBom (Join-Path $AndroidProject "gradle.properties") $content

# app/build.gradle
$content = @"
plugins {
    id 'com.android.application'
}
android {
    namespace '$AppId'
    compileSdk $CompileSdk
    defaultConfig {
        applicationId "$AppId"
        minSdk $MinSdk
        targetSdk $TargetSdk
        versionCode 1
        versionName "1.0"
    }
    buildTypes {
        release {
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }
    }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }
}
dependencies {
    implementation 'androidx.appcompat:appcompat:1.6.1'
    implementation 'com.google.android.material:material:1.11.0'
}
"@
Write-Utf8NoBom (Join-Path $AndroidProject "app\build.gradle") $content

# AndroidManifest.xml
$content = @"
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <application
        android:allowBackup="true"
        android:icon="@mipmap/ic_launcher"
        android:label="@string/app_name"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:supportsRtl="true"
        android:usesCleartextTraffic="true"
        android:theme="@style/Theme.AIXue">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"@
Write-Utf8NoBom (Join-Path $AndroidProject "app\src\main\AndroidManifest.xml") $content

# MainActivity.java
$content = @"
package com.aixue.app;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {
    private WebView webView;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setBuiltInZoomControls(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        webView.loadUrl("file:///android_asset/chat.html");
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
"@
Write-Utf8NoBom (Join-Path $AndroidProject "app\src\main\java\com\aixue\app\MainActivity.java") $content

# strings.xml
$content = @"
<resources>
    <string name="app_name">$AppName</string>
</resources>
"@
Write-Utf8NoBom (Join-Path $AndroidProject "app\src\main\res\values\strings.xml") $content

# themes.xml
$content = @"
<resources>
    <style name="Theme.AIXue" parent="Theme.MaterialComponents.DayNight.NoActionBar">
        <item name="colorPrimary">#3E63DD</item>
        <item name="colorPrimaryVariant">#2A4CB8</item>
        <item name="colorOnPrimary">#FFFFFF</item>
    </style>
</resources>
"@
Write-Utf8NoBom (Join-Path $AndroidProject "app\src\main\res\values\themes.xml") $content

Write-Host "  配置文件: OK" -ForegroundColor Green

# ===== 复制前端文件 =====
Write-Host ""
Write-Host "[5/7] 复制前端文件到 assets..." -ForegroundColor Yellow
$AssetsDir = Join-Path $AndroidProject "app\src\main\assets"
Copy-Item -Path (Join-Path $ProjectDir "prototype\*") -Destination $AssetsDir -Recurse -Force
Write-Host "  前端文件: OK" -ForegroundColor Green

# ===== 修改 API 地址 =====
Write-Host "  修改 API 地址为: $ApiBase"
$ChatHtml = Join-Path $AssetsDir "chat.html"
$content = Get-Content $ChatHtml -Raw -Encoding UTF8
$content = $content -replace 'http://localhost:8000', $ApiBase
Write-Utf8NoBom $ChatHtml $content
Write-Host "  API 地址: OK" -ForegroundColor Green

# ===== 生成 Gradle Wrapper =====
Write-Host ""
Write-Host "[6/7] 生成 Gradle Wrapper..." -ForegroundColor Yellow

# gradle-wrapper.properties
$content = @"
distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\://services.gradle.org/distributions/gradle-8.0-bin.zip
networkTimeout=10000
validateDistributionUrl=true
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
"@
Write-Utf8NoBom (Join-Path $AndroidProject "gradle\wrapper\gradle-wrapper.properties") $content

$gradleCmd = Get-Command gradle -ErrorAction SilentlyContinue
if ($gradleCmd) {
    Write-Host "  使用系统 gradle 生成 wrapper..."
    Push-Location $AndroidProject
    gradle wrapper --gradle-version 8.0 2>&1 | Out-Null
    Pop-Location
    Write-Host "  Gradle Wrapper: OK" -ForegroundColor Green
} else {
    Write-Host "  未找到系统 gradle，将使用 Android Studio 构建" -ForegroundColor Yellow
}

# ===== 构建 APK =====
Write-Host ""
Write-Host "[7/7] 构建 APK..." -ForegroundColor Yellow

$GradlewBat = Join-Path $AndroidProject "gradlew.bat"
if (Test-Path $GradlewBat) {
    Write-Host "  使用 Gradle Wrapper 构建（首次需要下载依赖，请耐心等待）..."
    Push-Location $AndroidProject
    & .\gradlew.bat assembleDebug --no-daemon
    $BuildResult = $LASTEXITCODE
    Pop-Location

    if ($BuildResult -eq 0) {
        $ApkPath = Join-Path $AndroidProject "app\build\outputs\apk\debug\app-debug.apk"
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  APK 构建成功！" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  APK 路径: $ApkPath"
        Write-Host ""
        Write-Host "  安装到手机: adb install -r `"$ApkPath`""
        Write-Host "========================================"
        Write-Host ""
        $choice = Read-Host "是否打开 APK 所在目录? (Y/N)"
        if ($choice -eq "Y" -or $choice -eq "y") {
            explorer (Split-Path $ApkPath)
        }
    } else {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "  APK 构建失败，错误码: $BuildResult" -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "  可能原因:"
        Write-Host "  1. Gradle 依赖下载失败（检查网络）"
        Write-Host "  2. Android SDK Build-tools 未安装"
        Write-Host "  3. Java 版本不兼容（需要 JDK 11+）"
        Write-Host ""
        Write-Host "  建议用 Android Studio 打开项目查看详细错误:"
        Write-Host "  项目路径: $AndroidProject"
        Write-Host "========================================"
        Write-Host ""
        Read-Host "按回车打开项目目录"
        explorer $AndroidProject
    }
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  无法自动构建（缺少 Gradle Wrapper）"
    Write-Host "  请用 Android Studio 打开项目手动构建:"
    Write-Host "  项目路径: $AndroidProject"
    Write-Host ""
    Write-Host "  1. Android Studio -> Open -> 选择上述目录"
    Write-Host "  2. 等待 Gradle 同步完成"
    Write-Host "  3. Build -> Build Bundle(s)/APK(s) -> Build APK(s)"
    Write-Host "  4. 构建完成后点击 locate 找到 APK"
    Write-Host "========================================"
    Write-Host ""
    Read-Host "按回车打开项目目录"
    explorer $AndroidProject
}
