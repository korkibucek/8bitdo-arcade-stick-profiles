@echo off
rem Launch the 8BitDo Arcade Stick tray switcher (no console window).
rem To start it with Windows: press Win+R, type shell:startup, and put a
rem shortcut to this file in that folder.
start "" pyw "%~dp0stickctl\tray.py"
