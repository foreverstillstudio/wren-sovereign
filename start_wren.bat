@echo off
rem Wren launcher — starts her server, output appended to data\wren_runtime.log
cd /d "C:\foreverstill\systems\wren_sovereign"
"C:\Users\chris\AppData\Local\Programs\Python\Python312\python.exe" server.py >> "data\wren_runtime.log" 2>&1
