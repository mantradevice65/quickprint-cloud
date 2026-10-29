@echo off
title QuickPrint Cloud - Deploy to GitHub
color 0A
echo ========================================================
echo        QuickPrint 24/7 Cloud Queue - GitHub Push
echo ========================================================
echo.
echo Pehle https://github.com/new par ja kar ek naya repository banaye:
echo Repository name: quickprint-cloud
echo.
set /p REPO_URL="Apna GitHub Repository URL yahan paste karein (e.g. https://github.com/username/quickprint-cloud.git): "

if "%REPO_URL%"=="" (
    echo Error: URL khali nahi ho sakta!
    pause
    exit /b
)

git remote remove origin 2>nul
git remote add origin %REPO_URL%
git branch -M main
echo.
echo Code GitHub par upload ho raha hai...
git push -u origin main

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo   SUCCESS! Code GitHub par successfully push ho gaya!
    echo   Ab Render.com par jakar 'New Web Service' me is repo ko
    echo   select karein aur deploy par click karein.
    echo ========================================================
) else (
    echo.
    echo GitHub push me koi issue aaya. Kripya apna login aur URL check karein.
)

pause
