@echo off
rem Convenience wrapper: run stickctl from anywhere in this repo.
rem   stick capture ps3
rem   stick list
rem   stick switch ps3
py "%~dp0stickctl\stickctl.py" %*
