
@echo off
echo [1/3] 가상환경 활성화...
call .venv\Scripts\activate

echo [2/3] 필수 패키지 설치 확인...
pip install PySide6 Pillow pyinstaller

echo [3/3] 실행 파일 빌드 시작 (잠시만 기다려 주세요)...
pyinstaller --noconsole --onefile --clean --name "ImageCompressor" image_compressor.py

echo.
echo ======================================================
echo 빌드가 완료되었습니다!
echo 'dist' 폴더 안에 생성된 'SmartImageCompressor.exe'를 확인하세요.
echo ======================================================
pause