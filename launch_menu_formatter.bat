@echo off
cd /d %~dp0legacy\menu-formatter-bot
if not exist node_modules (
  echo Installing menu formatter dependencies...
  call npm install
)
echo Starting legacy menu formatter bot...
call npm start
