@echo off
rem Met le site en ligne (adresse provisoire qui CHANGE a chaque lancement)
rem et fabrique 8 liens neufs, affiches ici et copies dans le presse-papiers.
rem Une seule fenetre : elle fait tourner le site (relance auto s'il plante) et le tunnel.
rem Les codes en clair ne sont ecrits dans AUCUN fichier.
rem Autre nombre de liens : METTRE-EN-LIGNE.bat 20
rem Si tu fermes la fenetre ou eteins/mets en veille le PC, le site n'est plus joignable.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set N=%1
if "%N%"=="" set N=8
py -3.12 outils\demarrer_en_ligne.py --nombre %N%
pause
