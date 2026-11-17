@echo off
rem Lance le site en local sur http://127.0.0.1:8100
rem --no-access-log : les codes sont dans l'adresse des liens, on ne les journalise PAS.
cd /d "%~dp0"
py -3.12 -m uvicorn app:app --host 127.0.0.1 --port 8100 --no-access-log
pause
