@echo off
SET SCRIPT_NAME=ebs_pipeline_gui.py
SET APP_NAME=EBS_Pipeline_GUI

echo.
echo --- Bat dau qua trinh build file EXE ---
echo.

:: --- Luu y: Dat file icon.ico trong cung thu muc voi script nay neu ban muon co icon. ---
:: --- Neu khong co icon, ban co the xoa phan --icon "%ICON_FILE%" trong lenh pyinstaller. ---
SET ICON_FILE=icon.ico

:: --- Buoc 1: Xoa cac thu muc build truoc do ---
echo Kiem tra va xoa cac file/thu muc build cu...
IF EXIST build rmdir /s /q build
IF EXIST dist rmdir /s /q dist
IF EXIST "%APP_NAME%.spec" del "%APP_NAME%.spec"
echo Da xoa cac file/thu muc build cu.
echo.

:: --- Buoc 2: Chay PyInstaller ---
echo Dang tien hanh build "%APP_NAME%.exe"...
:: Lenh co icon
pyinstaller --noconsole --onefile --name "%APP_NAME%" --icon "%ICON_FILE%" "%SCRIPT_NAME%"
:: Hoac lenh khong co icon (neu ban khong co file icon.ico):
:: pyinstaller --noconsole --onefile --name "%APP_NAME%" "%SCRIPT_NAME%"

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo --------------------------------------------------------------------------------
    echo --- LOI: PyInstaller khong the tao file thuc thi. Vui long kiem tra log. ---
    echo --------------------------------------------------------------------------------
    echo.
    pause
    EXIT /B %ERRORLEVEL%
)

echo.
echo --- Qua trinh build hoan tat! ---
echo File thuc thi (EXE) cua ban nam o: dist\%APP_NAME%.exe
echo.
echo Luu y: Mot so antivirus co the phat hien nham cac file duoc dong goi boi PyInstaller.
echo.
pause
EXIT /B 0
