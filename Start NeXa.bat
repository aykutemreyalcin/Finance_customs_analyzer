@echo off
cd /d "%~dp0"
echo Starting NeXa...
echo Once it says "You can now view your Streamlit app", it will open in your browser.
echo To stop the app, close this window or press Ctrl+C.
echo.
".\venv\Scripts\python.exe" -m streamlit run app.py
pause
