@echo off
:: এই file চালালে Desktop-এ shortcut তৈরি হবে
:: প্রথমে নিচের URL টা তোমার Render link দিয়ে বদলে দাও

set APP_URL=https://YOUR-APP-NAME.onrender.com
set SHORTCUT_NAME=Project Tracker

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\%SHORTCUT_NAME%.lnk'); $s.TargetPath = 'C:\Program Files\Google\Chrome\Application\chrome.exe'; $s.Arguments = '--app=%APP_URL% --window-size=1200,800'; $s.Description = 'Project Tracker'; $s.Save()"

echo.
echo Desktop shortcut তৈরি হয়েছে!
echo এখন Desktop-এ "Project Tracker" icon দেখতে পাবে।
echo.
pause
