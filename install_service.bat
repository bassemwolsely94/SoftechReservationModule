@echo off
REM ElRezeiky Pharmacy Platform — Windows Service Installer
REM Run this as Administrator
REM Requires NSSM (Non-Sucking Service Manager): https://nssm.cc/

SET PYTHON=C:\Python311\python.exe
SET APP_DIR=C:\elrezeiky_platform
SET LOG_DIR=%APP_DIR%\logs

echo =============================================
echo  ElRezeiky Platform — Windows Service Setup
echo =============================================

REM Create logs directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Collect static files
echo Collecting static files...
"%PYTHON%" "%APP_DIR%\manage.py" collectstatic --noinput

REM Run migrations
echo Running database migrations...
"%PYTHON%" "%APP_DIR%\manage.py" migrate

REM Test Sybase connection
echo Testing Sybase connection...
"%PYTHON%" "%APP_DIR%\manage.py" test_sybase_connection

REM Install service with NSSM
echo Installing Windows service...
nssm install ElRezeikyPlatform "%PYTHON%" "%APP_DIR%\manage.py runserver 0.0.0.0:8000"
nssm set ElRezeikyPlatform AppDirectory "%APP_DIR%"
nssm set ElRezeikyPlatform DisplayName "ElRezeiky Pharmacy Platform"
nssm set ElRezeikyPlatform Description "ElRezeiky Pharmacy CRM and Reservation Platform"
nssm set ElRezeikyPlatform Start SERVICE_AUTO_START
nssm set ElRezeikyPlatform AppStdout "%LOG_DIR%\service.log"
nssm set ElRezeikyPlatform AppStderr "%LOG_DIR%\error.log"
nssm set ElRezeikyPlatform AppRotateFiles 1
nssm set ElRezeikyPlatform AppRotateBytes 10485760

REM Start the service
net start ElRezeikyPlatform

echo.
echo =============================================
echo  Platform running at http://YOUR_SERVER_IP:8000
echo  Admin panel:       http://YOUR_SERVER_IP:8000/admin/
echo =============================================
pause
