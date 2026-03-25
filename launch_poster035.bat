@echo off
cd /d %~dp0legacy\valkyrie-poster035
if not exist node_modules (
  echo Installing poster bot dependencies...
  call npm install
)
echo Starting Valkyrie_POSTER035 PRO...
call npm start
