@echo off
REM Build installer without bundled libraries (requires local Python dependencies)
REM Usage: build.bat [version]
REM   version: Optional version number (e.g., 1.2.3). Defaults to 1.1.0 if not specified.

setlocal
cd /d "%~dp0"

set DEFAULT_VERSION=1.1.0
set BUILD_RESULT=0
set VERSION=%~1
if "%VERSION%"=="" (
    echo Building clean installer with default version...
    set EFFECTIVE_VERSION=%DEFAULT_VERSION%
    set VERSION_ARG=
) else (
    echo Building clean installer version %VERSION%...
    set EFFECTIVE_VERSION=%VERSION%
    set VERSION_ARG=-d Version=%VERSION%
)
set OUTPUT_MSI=AirfoilSpline-%EFFECTIVE_VERSION%.msi

set GENERATED_PACKAGE_XML=PackageContents.generated.xml
set BACKUP_PACKAGE_XML=PackageContents.original.xml
set GENERATED_MANIFEST=AirfoilSpline.generated.manifest
set BACKUP_MANIFEST=AirfoilSpline.original.manifest

copy /y PackageContents.xml "%BACKUP_PACKAGE_XML%" >nul
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

copy /y ..\AirfoilSpline.manifest "%BACKUP_MANIFEST%" >nul
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

python update_packagecontents_version.py --input PackageContents.xml --output "%GENERATED_PACKAGE_XML%" --version "%EFFECTIVE_VERSION%"
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

python update_manifest_version.py --input ..\AirfoilSpline.manifest --output "%GENERATED_MANIFEST%" --version "%EFFECTIVE_VERSION%"
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

copy /y "%GENERATED_PACKAGE_XML%" PackageContents.xml >nul
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

copy /y "%GENERATED_MANIFEST%" ..\AirfoilSpline.manifest >nul
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

python prepare_core.py
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

python generate_wxs_fragment.py --exclude-lib --output Files.wxs
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

wix build AirfoilSplineAddin.wxs Files.wxs -ext WixToolset.UI.wixext -ext WixToolset.Util.wixext %VERSION_ARG% -o "%OUTPUT_MSI%"
if errorlevel 1 (
    set BUILD_RESULT=1
    goto :cleanup
)

echo.
echo Installer built successfully: %OUTPUT_MSI%

:cleanup
if exist "%BACKUP_PACKAGE_XML%" move /y "%BACKUP_PACKAGE_XML%" PackageContents.xml >nul
if exist "%BACKUP_MANIFEST%" move /y "%BACKUP_MANIFEST%" ..\AirfoilSpline.manifest >nul
if exist "%GENERATED_PACKAGE_XML%" del /q "%GENERATED_PACKAGE_XML%"
if exist "%GENERATED_MANIFEST%" del /q "%GENERATED_MANIFEST%"
exit /b %BUILD_RESULT%
