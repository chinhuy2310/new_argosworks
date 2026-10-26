@echo off
REM ============================================================================
REM  ARGOS WORKS — Automated Test Suite Runner (Windows)
REM  Chay toan bo kiem thu tu dong: Unit -> Integration -> E2E -> Legacy unittest
REM  Dung:  run_tests.bat            (day du)
REM         run_tests.bat unit       (chi unit tests)
REM         CI=1 run_tests.bat       (khong dung pause, dung cho CI)
REM ============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ====================================================
echo   ARGOS WORKS - Automated Test Suite
echo ====================================================
echo.

REM Activate venv if exists
if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
)

REM Test environment secrets (values are throwaway, never used in production)
if "%ARGOS_MASTER_KEY%"=="" set ARGOS_MASTER_KEY=test-master-key-for-unit-tests-2026
if "%ARGOS_LICENSE_SECRET%"=="" set ARGOS_LICENSE_SECRET=CI_TEST_LICENSE_SECRET_KEY_12345

echo [1/4] Installing test dependencies...
python -m pip install -r requirements-dev.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo [WARN] pip install failed - assuming dependencies are already present.
)

set TARGET=%1
if "%TARGET%"=="" set TARGET=all

if /I "%TARGET%"=="unit" goto run_unit
if /I "%TARGET%"=="integration" goto run_integration
if /I "%TARGET%"=="e2e" goto run_e2e
goto run_all

:run_unit
echo.
echo [2/4] UNIT Tests (utils, auth, security)...
echo -----------------------------------------------
python -m pytest tests/test_unit_utils.py tests/test_unit_auth.py tests/test_unit_security.py -q --tb=short
if errorlevel 1 goto fail
goto done

:run_integration
echo.
echo [2/4] INTEGRATION Tests (database, API handlers, private records)...
echo -----------------------------------------------
python -m pytest tests/test_integration_db.py tests/test_integration_api_handlers.py -q --tb=short
if errorlevel 1 goto fail
goto done

:run_e2e
echo.
echo [2/4] E2E Tests (full user flows)...
echo -----------------------------------------------
python -m pytest tests/test_e2e_user_flows.py -q --tb=short
if errorlevel 1 goto fail
goto done

:run_all
echo.
echo [2/4] PYTEST Suites (new: unit + integration + e2e)...
echo -----------------------------------------------
python -m pytest -q --tb=short
if errorlevel 1 goto fail

echo.
echo [3/4] LEGACY unittest Suites (audit / rbac / wsgi / postgres smoke)...
echo -----------------------------------------------
python -m unittest discover -s tests -v
if errorlevel 1 goto fail

goto done

:fail
echo.
echo [FAIL] Test suite failed. Fix errors before shipping.
if not "%CI%"=="1" pause
exit /b 1

:done
echo.
echo ====================================================
echo   ALL TESTS PASSED
echo ====================================================
if not "%CI%"=="1" pause
exit /b 0

