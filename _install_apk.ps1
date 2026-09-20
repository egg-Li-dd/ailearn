$adb = "C:\Users\21142\AppData\Local\Android\Sdk\platform-tools\adb.exe"
$apk = "C:\ailearn\app\build\app\outputs\flutter-apk\app-release.apk"
$deviceIp = "192.168.3.5:36461"

Write-Output "=== Starting adb server ==="
& $adb start-server
Start-Sleep -Seconds 2

Write-Output "=== Connecting to $deviceIp ==="
& $adb connect $deviceIp
Start-Sleep -Seconds 3

Write-Output "=== Devices ==="
& $adb devices

Write-Output "=== Installing APK ==="
& $adb -s $deviceIp install -r $apk
Write-Output "=== Install exit code: $LASTEXITCODE ==="
