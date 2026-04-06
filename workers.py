import json
import subprocess

from PySide6.QtCore import QObject, Signal, Slot


class InfoWorker(QObject):
    finished = Signal()
    result = Signal(dict)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, url: str, yt_dlp_cmd: str = "yt-dlp"):
        super().__init__()
        self.url = url
        self.yt_dlp_cmd = yt_dlp_cmd

    @Slot()
    def run(self):
        if not self.url:
            self.error.emit("網址是空的")
            self.finished.emit()
            return

        cmd = [self.yt_dlp_cmd, "--dump-single-json", "--skip-download", self.url]
        self.log.emit("開始讀取影片資訊...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except FileNotFoundError:
            self.error.emit("找不到 yt-dlp，請先安裝或確認 PATH")
            self.finished.emit()
            return
        except subprocess.CalledProcessError as exc:
            error_text = exc.stderr.strip() or exc.stdout.strip() or "未知錯誤"
            self.error.emit(f"讀取失敗：{error_text}")
            self.finished.emit()
            return
        except Exception as exc:
            self.error.emit(f"執行時發生錯誤：{exc}")
            self.finished.emit()
            return

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.error.emit("yt-dlp 有回應，但 JSON 解析失敗")
            self.finished.emit()
            return

        self.result.emit(data)
        self.finished.emit()


class FormatWorker(QObject):
    finished = Signal()
    result = Signal(dict)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, url: str, yt_dlp_cmd: str = "yt-dlp"):
        super().__init__()
        self.url = url
        self.yt_dlp_cmd = yt_dlp_cmd

    @Slot()
    def run(self):
        if not self.url:
            self.error.emit("網址是空的")
            self.finished.emit()
            return

        cmd = [self.yt_dlp_cmd, "--dump-single-json", "--skip-download", self.url]
        self.log.emit("開始讀取格式列表...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except FileNotFoundError:
            self.error.emit("找不到 yt-dlp，請先安裝或確認 PATH")
            self.finished.emit()
            return
        except subprocess.CalledProcessError as exc:
            error_text = exc.stderr.strip() or exc.stdout.strip() or "未知錯誤"
            self.error.emit(f"讀取格式失敗：{error_text}")
            self.finished.emit()
            return
        except Exception as exc:
            self.error.emit(f"執行時發生錯誤：{exc}")
            self.finished.emit()
            return

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.error.emit("yt-dlp 有回應，但 JSON 解析失敗")
            self.finished.emit()
            return

        self.result.emit(data)
        self.finished.emit()
