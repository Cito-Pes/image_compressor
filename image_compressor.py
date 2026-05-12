import sys
import os
import shutil
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance
import io

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar, QTextEdit,
    QGroupBox, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QObject

# ─────────────────────────────────────────────
# 상수 설정
# ─────────────────────────────────────────────
TARGET_KB = 300
TARGET_BYTES = TARGET_KB * 1024
SCAN_EXTS = {'.jpg', '.jpeg', '.tif', '.tiff', '.png'}

STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #1e2330;
    color: #e0e6f0;
    font-family: '맑은 고딕', 'Malgun Gothic', sans-serif;
}
QGroupBox {
    border: 1px solid #3a4460;
    border-radius: 6px;
    margin-top: 15px;
    padding-top: 15px;
    font-weight: bold;
    color: #8ab4f8;
}
QPushButton#btn_start {
    background-color: #1a6fe0;
    color: #ffffff;
    font-size: 15px;
    font-weight: bold;
    padding: 12px;
    border-radius: 4px;
}
QPushButton#btn_start:hover { background-color: #2680f5; }
QTextEdit {
    background-color: #111622;
    color: #9ab8d8;
    border: 1px solid #2a3350;
    font-family: 'Consolas', monospace;
}
"""

# ─────────────────────────────────────────────
# 고정형 자동 압축 엔진
# ─────────────────────────────────────────────

def get_optimized_image(img):
    """글자 선명도 최적화 전처리"""
    if img.mode != 'L':
        img = img.convert('L')
    # 자동 대비: 배경은 하얗게, 글씨는 검게
    img = ImageOps.autocontrast(img, cutoff=1)
    # 선명도 보정
    enhancer = ImageEnhance.Sharpness(img)
    return enhancer.enhance(2.0)

def smart_compress(src_path: Path, dst_path: Path) -> dict:
    """
    그레이스케일 -> 흑백(Group4) -> 해상도 조절 순으로 자동 압축
    """
    try:
        with Image.open(src_path) as raw_img:
            # 0. 기본 전처리 (회전 보정 및 선명화)
            img = ImageOps.exif_transpose(raw_img)
            img = get_optimized_image(img)
            orig_w, orig_h = img.size

            # --- 1단계: 그레이스케일 LZW 시도 ---
            buf = io.BytesIO()
            img.save(buf, format='TIFF', compression='tiff_lzw')
            if buf.tell() <= TARGET_BYTES:
                dst_path.write_bytes(buf.getvalue())
                return {'success': True, 'mode': '그레이스케일', 'size': buf.tell()}

            # --- 2단계: 흑백(1비트) CCITT Group4 시도 (해상도 100%) ---
            # 흑백 변환 시 가독성을 위해 임계값 적용
            bw_img = img.point(lambda x: 255 if x > 145 else 0, mode='1')
            buf = io.BytesIO()
            bw_img.save(buf, format='TIFF', compression='group4')
            if buf.tell() <= TARGET_BYTES:
                dst_path.write_bytes(buf.getvalue())
                return {'success': True, 'mode': '흑백(최대화질)', 'size': buf.tell()}

            # --- 3단계: 흑백 상태에서 해상도 축소 시도 ---
            scales = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]
            for scale in scales:
                nw, nh = int(orig_w * scale), int(orig_h * scale)
                # 리사이즈 후 다시 흑백 처리 (계단 현상 방지)
                resized_img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                bw_resized = resized_img.point(lambda x: 255 if x > 145 else 0, mode='1')
                
                buf = io.BytesIO()
                bw_resized.save(buf, format='TIFF', compression='group4')
                
                if buf.tell() <= TARGET_BYTES:
                    dst_path.write_bytes(buf.getvalue())
                    return {'success': True, 'mode': f'흑백(축소 {int(scale*100)}%)', 'size': buf.tell()}

            # 최종 실패 시 가장 작은 사이즈라도 저장
            dst_path.write_bytes(buf.getvalue())
            return {'success': True, 'mode': '흑백(최소화)', 'size': buf.tell()}

    except Exception as e:
        return {'success': False, 'msg': str(e)}

# ─────────────────────────────────────────────
# UI 및 실행 스레드
# ─────────────────────────────────────────────

class Worker(QObject):
    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal()

    def __init__(self, src_folder):
        super().__init__()
        self.src_folder = Path(src_folder)
        self.dst_folder = self.src_folder / "압축완료_TIFF"

    def run(self):
        files = [f for f in self.src_folder.glob('*') if f.suffix.lower() in SCAN_EXTS]
        if not files:
            self.log.emit("❌ 처리할 이미지가 폴더에 없습니다.")
            self.finished.emit()
            return

        self.dst_folder.mkdir(exist_ok=True)
        self.log.emit(f"🚀 총 {len(files)}개 파일 압축 시작...")

        for i, src in enumerate(files, 1):
            self.progress.emit(i, len(files))
            dst = self.dst_folder / (src.stem + ".tif")
            
            res = smart_compress(src, dst)
            
            if res['success']:
                size_kb = res['size'] // 1024
                self.log.emit(f"✅ {src.name} -> {size_kb}KB [{res['mode']}]")
            else:
                self.log.emit(f"❌ {src.name} 오류: {res['msg']}")

        self.log.emit(f"\n📂 저장 완료: {self.dst_folder}")
        self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("문서 가독성 최적화 자동 압축기 (TIFF)")
        self.setMinimumSize(700, 550)
        self.setStyleSheet(STYLE_SHEET)
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 폴더 선택
        grp_folder = QGroupBox("파일 경로 설정")
        lay_folder = QHBoxLayout(grp_folder)
        self.lbl_path = QLabel("압축할 파일이 담긴 폴더를 선택하세요.")
        btn_browse = QPushButton("📂 폴더 선택")
        btn_browse.clicked.connect(self._browse)
        lay_folder.addWidget(self.lbl_path, 1)
        lay_folder.addWidget(btn_browse)
        layout.addWidget(grp_folder)

        # 안내 문구
        info_label = QLabel("※ 자동으로 그레이스케일/흑백을 전환하여 300KB 미만으로 맞춥니다.")
        info_label.setStyleSheet("color: #ffa500; font-size: 11px; margin-left: 5px;")
        layout.addWidget(info_label)

        # 로그 박스
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        # 진행바
        self.pbar = QProgressBar()
        self.pbar.setTextVisible(True)
        layout.addWidget(self.pbar)

        # 시작 버튼
        self.btn_start = QPushButton("▶ 자동 압축 시작 (TIFF 고정)")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self._start_process)
        layout.addWidget(self.btn_start)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if d: self.lbl_path.setText(d)

    def _start_process(self):
        path = self.lbl_path.text()
        if not os.path.isdir(path):
            self.log_box.append("⚠ 유효한 폴더를 먼저 선택해 주세요.")
            return

        self.btn_start.setEnabled(False)
        self.log_box.clear()
        
        self.thread = QThread()
        self.worker = Worker(path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self.log_box.append)
        self.worker.finished.connect(self._on_finished)
        self.thread.start()

    def _on_progress(self, cur, total):
        self.pbar.setMaximum(total)
        self.pbar.setValue(cur)

    def _on_finished(self):
        self.btn_start.setEnabled(True)
        self.thread.quit()
        self.thread.wait()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())