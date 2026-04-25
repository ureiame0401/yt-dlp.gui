import locale
import os
import re
import shlex
import shutil
import subprocess
import sys
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from PySide6.QtCore import Qt, QProcess, QThread, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from presets import load_presets_from_disk, save_presets_to_disk
from runtime_paths import detect_runtime_tools
from utils import format_bytes, format_seconds
from workers import FormatWorker, InfoWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("yt-dlp GUI")
        self.resize(1380, 920)
        self.setMinimumSize(1140, 780)

        self.info_thread = None
        self.info_worker = None
        self.format_thread = None
        self.format_worker = None

        self.download_process = None
        self.process_buffer = ""
        self.stdout_buffer = b""
        self.stderr_buffer = b""
        self.download_queue = []
        self.current_task = None
        self.stop_requested = False
        self.ansi_escape_re = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

        self.presets = load_presets_from_disk()
        self.runtime_tools = detect_runtime_tools()

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        top_box = QGroupBox("快速操作")
        top_layout = QVBoxLayout(top_box)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("貼上影片、播放清單或頻道網址")
        self.example_btn = QPushButton("範例")
        url_row.addWidget(QLabel("網址"))
        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(self.example_btn)

        action_row = QHBoxLayout()
        self.info_btn = QPushButton("讀取資訊")
        self.format_btn = QPushButton("讀取格式")
        self.queue_btn = QPushButton("加入佇列")
        self.download_btn = QPushButton("立即下載")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        action_row.addStretch()
        action_row.addWidget(self.info_btn)
        action_row.addWidget(self.format_btn)
        action_row.addWidget(self.queue_btn)
        action_row.addWidget(self.download_btn)
        action_row.addWidget(self.stop_btn)

        top_layout.addLayout(url_row)
        top_layout.addLayout(action_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = self.build_left_panel()
        right_panel = self.build_right_panel()
        left_panel.setMinimumWidth(470)
        right_panel.setMinimumWidth(520)

        splitter.addWidget(self.wrap_in_scroll_area(left_panel))
        splitter.addWidget(self.wrap_in_scroll_area(right_panel))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([670, 710])

        log_box = QGroupBox("執行紀錄")
        log_layout = QVBoxLayout(log_box)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(180)
        log_layout.addWidget(self.log_output)

        root_layout.addWidget(top_box)
        root_layout.addWidget(splitter, 1)
        root_layout.addWidget(log_box, 1)

        self.bind_events()
        self.configure_responsive_ui()
        self.apply_detected_runtime_tools()
        self.refresh_preset_list()
        self.refresh_environment_status()
        self.on_track_options_changed()
        self.on_naming_scheme_changed()
        self.on_use_custom_format_changed()

    # -------------------------------------------------
    # UI build
    # -------------------------------------------------
    def build_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.tabs = QTabWidget()

        simple_tab = QWidget()
        simple_layout = QVBoxLayout(simple_tab)

        tools_box = QGroupBox("工具與輸出")
        tools_layout = QVBoxLayout(tools_box)

        ytdlp_row = QHBoxLayout()
        self.ytdlp_input = QLineEdit("yt-dlp")
        self.ytdlp_input.setPlaceholderText("yt-dlp 或完整路徑")
        self.choose_ytdlp_btn = QPushButton("選擇")
        ytdlp_row.addWidget(QLabel("yt-dlp"))
        ytdlp_row.addWidget(self.ytdlp_input)
        ytdlp_row.addWidget(self.choose_ytdlp_btn)

        ffmpeg_row = QHBoxLayout()
        self.ffmpeg_input = QLineEdit()
        self.ffmpeg_input.setPlaceholderText("ffmpeg 所在資料夾")
        self.choose_ffmpeg_btn = QPushButton("選擇")
        ffmpeg_row.addWidget(QLabel("FFmpeg"))
        ffmpeg_row.addWidget(self.ffmpeg_input)
        ffmpeg_row.addWidget(self.choose_ffmpeg_btn)

        output_row = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("下載資料夾")
        self.choose_output_btn = QPushButton("選擇")
        output_row.addWidget(QLabel("輸出"))
        output_row.addWidget(self.output_input)
        output_row.addWidget(self.choose_output_btn)

        output_option_row = QHBoxLayout()
        self.batch_list_folder_checkbox = QCheckBox("批次下載建立清單資料夾")
        self.batch_list_folder_checkbox.setChecked(True)
        output_option_row.addStretch()
        output_option_row.addWidget(self.batch_list_folder_checkbox)

        tools_layout.addLayout(ytdlp_row)
        tools_layout.addLayout(ffmpeg_row)
        tools_layout.addLayout(output_row)
        tools_layout.addLayout(output_option_row)

        content_box = QGroupBox("下載選項")
        content_layout = QVBoxLayout(content_box)

        scope_row = QHBoxLayout()
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("自動判斷", "auto")
        self.scope_combo.addItem("單支影片", "single")
        self.scope_combo.addItem("整個播放清單", "playlist")
        self.scope_combo.addItem("整個頻道", "channel")
        scope_row.addWidget(QLabel("範圍"))
        scope_row.addWidget(self.scope_combo)

        track_box = QGroupBox("要下載什麼")
        track_layout = QHBoxLayout(track_box)
        self.download_video_checkbox = QCheckBox("影片")
        self.download_audio_checkbox = QCheckBox("音訊")
        self.merge_output_checkbox = QCheckBox("合成單一檔案")
        self.download_video_checkbox.setChecked(True)
        self.download_audio_checkbox.setChecked(True)
        self.merge_output_checkbox.setChecked(True)
        track_layout.addWidget(self.download_video_checkbox)
        track_layout.addWidget(self.download_audio_checkbox)
        track_layout.addWidget(self.merge_output_checkbox)
        track_layout.addStretch()

        quality_row = QHBoxLayout()
        self.quality_combo = QComboBox()
        quality_row.addWidget(QLabel("畫質 / 音質策略"))
        quality_row.addWidget(self.quality_combo)

        audio_preference_row = QHBoxLayout()
        self.audio_preference_label = QLabel("音訊偏好")
        self.audio_preference_combo = QComboBox()
        self.audio_preference_combo.addItem("自動最佳", "auto")
        self.audio_preference_combo.addItem("偏好 M4A", "m4a")
        self.audio_preference_combo.addItem("偏好 OPUS", "opus")
        audio_preference_row.addWidget(self.audio_preference_label)
        audio_preference_row.addWidget(self.audio_preference_combo)
        audio_preference_row.addStretch()

        audio_format_row = QHBoxLayout()
        self.audio_format_combo = QComboBox()
        for value in ["mp3", "m4a", "opus", "flac", "wav", "aac"]:
            self.audio_format_combo.addItem(value.upper(), value)
        audio_format_row.addWidget(QLabel("音訊輸出格式"))
        audio_format_row.addWidget(self.audio_format_combo)
        audio_format_row.addStretch()

        cover_row = QHBoxLayout()
        self.embed_thumbnail_checkbox = QCheckBox("嵌入縮圖 / 封面")
        self.embed_metadata_checkbox = QCheckBox("嵌入 metadata")
        self.embed_metadata_checkbox.setChecked(True)
        cover_row.addWidget(self.embed_thumbnail_checkbox)
        cover_row.addWidget(self.embed_metadata_checkbox)
        cover_row.addStretch()

        self.human_hint_label = QLabel()
        self.human_hint_label.setWordWrap(True)

        content_layout.addLayout(scope_row)
        content_layout.addWidget(track_box)
        content_layout.addLayout(quality_row)
        content_layout.addLayout(audio_preference_row)
        content_layout.addLayout(audio_format_row)
        content_layout.addLayout(cover_row)
        content_layout.addWidget(self.human_hint_label)

        subtitle_box = QGroupBox("字幕")
        subtitle_layout = QVBoxLayout(subtitle_box)
        subtitle_check_row = QHBoxLayout()
        self.write_subs_checkbox = QCheckBox("下載字幕")
        self.write_auto_subs_checkbox = QCheckBox("下載自動字幕")
        subtitle_check_row.addWidget(self.write_subs_checkbox)
        subtitle_check_row.addWidget(self.write_auto_subs_checkbox)
        subtitle_check_row.addStretch()

        subtitle_lang_row = QHBoxLayout()
        self.subtitle_lang_combo = QComboBox()
        self.subtitle_lang_combo.setEditable(True)
        self.subtitle_lang_combo.addItems(
            ["自動", "zh-TW", "zh-Hant", "zh-Hans", "zh", "en", "ja", "ko"]
        )
        subtitle_lang_row.addWidget(QLabel("字幕語言"))
        subtitle_lang_row.addWidget(self.subtitle_lang_combo)

        subtitle_layout.addLayout(subtitle_check_row)
        subtitle_layout.addLayout(subtitle_lang_row)

        simple_layout.addWidget(tools_box)
        simple_layout.addWidget(content_box)
        simple_layout.addWidget(subtitle_box)
        simple_layout.addStretch()

        naming_tab = QWidget()
        naming_layout = QVBoxLayout(naming_tab)

        naming_box = QGroupBox("檔名設計")
        naming_box_layout = QVBoxLayout(naming_box)

        naming_scheme_row = QHBoxLayout()
        self.naming_scheme_combo = QComboBox()
        self.naming_scheme_combo.addItem("只用標題", "title_only")
        self.naming_scheme_combo.addItem("日期 + 標題", "date_title")
        self.naming_scheme_combo.addItem("頻道 + 標題", "channel_title")
        self.naming_scheme_combo.addItem("頻道 / 日期 + 標題", "channel_date_title")
        self.naming_scheme_combo.addItem("播放清單序號 + 標題", "playlist_index_title")
        self.naming_scheme_combo.addItem("自訂模板", "custom")
        naming_scheme_row.addWidget(QLabel("命名方式"))
        naming_scheme_row.addWidget(self.naming_scheme_combo)

        self.title_template_input = QLineEdit("%(title)s.%(ext)s")
        self.title_template_input.setPlaceholderText("只有選『自訂模板』時才需要改")

        insert_row = QHBoxLayout()
        self.insert_token_combo = QComboBox()
        self.insert_token_combo.addItem("插入：標題", "%(title)s")
        self.insert_token_combo.addItem("插入：頻道", "%(uploader)s")
        self.insert_token_combo.addItem("插入：日期", "%(upload_date)s")
        self.insert_token_combo.addItem("插入：播放清單序號", "%(playlist_index)s")
        self.insert_token_combo.addItem("插入：ID", "%(id)s")
        self.insert_token_combo.addItem("插入：副檔名", "%(ext)s")
        self.insert_token_btn = QPushButton("插入欄位")
        insert_row.addWidget(self.insert_token_combo)
        insert_row.addWidget(self.insert_token_btn)

        self.filename_preview_label = QLabel("檔名範例：My Video.mp4")
        self.filename_preview_label.setWordWrap(True)

        naming_box_layout.addLayout(naming_scheme_row)
        naming_box_layout.addWidget(self.title_template_input)
        naming_box_layout.addLayout(insert_row)
        naming_box_layout.addWidget(self.filename_preview_label)

        format_box = QGroupBox("進階格式")
        format_box_layout = QVBoxLayout(format_box)
        self.use_custom_format_checkbox = QCheckBox("使用自訂 format 字串")
        self.format_input = QLineEdit("bestvideo+bestaudio/best")
        self.format_input.setPlaceholderText(
            "只有勾選時才使用，例如 bestvideo+bestaudio/best"
        )
        format_box_layout.addWidget(self.use_custom_format_checkbox)
        format_box_layout.addWidget(self.format_input)

        naming_layout.addWidget(naming_box)
        naming_layout.addWidget(format_box)
        naming_layout.addStretch()

        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        self.extra_args_input = QLineEdit()
        self.extra_args_input.setPlaceholderText(
            "例如：--playlist-end 20 --ignore-errors"
        )
        self.cookies_input = QLineEdit()
        self.cookies_input.setPlaceholderText("cookies.txt 路徑")
        advanced_layout.addWidget(QLabel("額外參數"))
        advanced_layout.addWidget(self.extra_args_input)
        advanced_layout.addWidget(QLabel("Cookies"))
        advanced_layout.addWidget(self.cookies_input)
        advanced_layout.addStretch()

        command_tab = QWidget()
        command_layout = QVBoxLayout(command_tab)
        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.build_cmd_btn = QPushButton("產生命令")
        command_layout.addWidget(QLabel("命令預覽"))
        command_layout.addWidget(self.command_preview)
        command_layout.addWidget(self.build_cmd_btn)

        presets_tab = QWidget()
        presets_layout = QVBoxLayout(presets_tab)

        quick_row_1 = QHBoxLayout()
        self.quick_video_btn = QPushButton("單支影片")
        self.quick_audio_btn = QPushButton("單支音樂")
        quick_row_1.addWidget(self.quick_video_btn)
        quick_row_1.addWidget(self.quick_audio_btn)

        quick_row_2 = QHBoxLayout()
        self.quick_channel_video_btn = QPushButton("頻道影片")
        self.quick_channel_audio_btn = QPushButton("頻道音樂")
        quick_row_2.addWidget(self.quick_channel_video_btn)
        quick_row_2.addWidget(self.quick_channel_audio_btn)

        preset_name_row = QHBoxLayout()
        self.preset_name_input = QLineEdit()
        self.preset_name_input.setPlaceholderText("例如：頻道 MP3 / 1080p MP4")
        preset_name_row.addWidget(QLabel("預設名稱"))
        preset_name_row.addWidget(self.preset_name_input)

        preset_btn_row = QHBoxLayout()
        self.save_preset_btn = QPushButton("儲存/覆蓋")
        self.load_preset_btn = QPushButton("載入")
        self.delete_preset_btn = QPushButton("刪除")
        preset_btn_row.addWidget(self.save_preset_btn)
        preset_btn_row.addWidget(self.load_preset_btn)
        preset_btn_row.addWidget(self.delete_preset_btn)

        self.preset_list = QListWidget()

        presets_layout.addLayout(quick_row_1)
        presets_layout.addLayout(quick_row_2)
        presets_layout.addLayout(preset_name_row)
        presets_layout.addLayout(preset_btn_row)
        presets_layout.addWidget(self.preset_list, 1)

        self.tabs.addTab(simple_tab, "簡單下載")
        self.tabs.addTab(naming_tab, "檔名與格式")
        self.tabs.addTab(advanced_tab, "進階")
        self.tabs.addTab(command_tab, "命令預覽")
        self.tabs.addTab(presets_tab, "預設參數")

        layout.addWidget(self.tabs)
        return panel

    def build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        env_box = QGroupBox("環境檢查")
        env_layout = QVBoxLayout(env_box)
        self.ytdlp_status_label = QLabel("yt-dlp：檢查中")
        self.ffmpeg_status_label = QLabel("FFmpeg：檢查中")
        self.refresh_status_btn = QPushButton("重新檢查")
        env_layout.addWidget(self.ytdlp_status_label)
        env_layout.addWidget(self.ffmpeg_status_label)
        env_layout.addWidget(self.refresh_status_btn)

        info_box = QGroupBox("影片資訊")
        info_layout = QVBoxLayout(info_box)
        self.info_title = QLabel("標題：尚未讀取")
        self.info_channel = QLabel("作者：尚未讀取")
        self.info_duration = QLabel("長度：尚未讀取")
        self.info_type = QLabel("類型：尚未讀取")
        for label in [
            self.info_title,
            self.info_channel,
            self.info_duration,
            self.info_type,
        ]:
            label.setWordWrap(True)
            info_layout.addWidget(label)

        format_box = QGroupBox("格式列表")
        format_layout = QVBoxLayout(format_box)
        self.format_table = QTableWidget(0, 8)
        self.format_table.setHorizontalHeaderLabels(
            ["format_id", "ext", "解析度", "fps", "video", "audio", "大小", "備註"]
        )
        self.format_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.format_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.format_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.format_table.verticalHeader().setVisible(False)
        self.format_table.setAlternatingRowColors(True)
        self.format_preview_label = QLabel("已選格式：尚未選擇")
        self.format_preview_label.setWordWrap(True)
        self.apply_format_btn = QPushButton("套用選中格式")
        format_layout.addWidget(self.format_table, 1)
        format_layout.addWidget(self.format_preview_label)
        format_layout.addWidget(self.apply_format_btn)

        queue_box = QGroupBox("下載佇列")
        queue_layout = QVBoxLayout(queue_box)
        self.queue_list = QListWidget()
        queue_layout.addWidget(self.queue_list)

        progress_box = QGroupBox("進度")
        progress_layout = QVBoxLayout(progress_box)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(env_box)
        layout.addWidget(info_box)
        layout.addWidget(format_box, 1)
        layout.addWidget(queue_box, 1)
        layout.addWidget(progress_box)
        return panel

    # -------------------------------------------------
    # Bind / responsive helpers
    # -------------------------------------------------
    def bind_events(self):
        self.example_btn.clicked.connect(self.fill_example)
        self.info_btn.clicked.connect(self.load_info_in_background)
        self.format_btn.clicked.connect(self.load_formats_in_background)
        self.queue_btn.clicked.connect(self.add_to_queue)
        self.download_btn.clicked.connect(self.download_now)
        self.stop_btn.clicked.connect(self.stop_download)
        self.choose_ytdlp_btn.clicked.connect(self.choose_ytdlp_file)
        self.choose_output_btn.clicked.connect(self.choose_output_folder)
        self.choose_ffmpeg_btn.clicked.connect(self.choose_ffmpeg_folder)
        self.build_cmd_btn.clicked.connect(self.build_command)
        self.apply_format_btn.clicked.connect(self.apply_selected_format)
        self.format_table.itemSelectionChanged.connect(self.preview_selected_format)
        self.format_table.itemDoubleClicked.connect(self.apply_selected_format)
        self.refresh_status_btn.clicked.connect(self.refresh_environment_status)
        self.save_preset_btn.clicked.connect(self.save_preset)
        self.load_preset_btn.clicked.connect(self.load_selected_preset)
        self.delete_preset_btn.clicked.connect(self.delete_selected_preset)
        self.quick_video_btn.clicked.connect(
            lambda: self.apply_quick_profile("single_video")
        )
        self.quick_audio_btn.clicked.connect(
            lambda: self.apply_quick_profile("single_audio")
        )
        self.quick_channel_video_btn.clicked.connect(
            lambda: self.apply_quick_profile("channel_video")
        )
        self.quick_channel_audio_btn.clicked.connect(
            lambda: self.apply_quick_profile("channel_audio")
        )
        self.ytdlp_input.editingFinished.connect(self.refresh_environment_status)
        self.ffmpeg_input.editingFinished.connect(self.refresh_environment_status)
        self.batch_list_folder_checkbox.toggled.connect(
            lambda _checked: self.build_command()
        )
        self.download_video_checkbox.toggled.connect(self.on_track_options_changed)
        self.download_audio_checkbox.toggled.connect(self.on_track_options_changed)
        self.use_custom_format_checkbox.toggled.connect(
            self.on_use_custom_format_changed
        )
        self.naming_scheme_combo.currentIndexChanged.connect(
            self.on_naming_scheme_changed
        )
        self.insert_token_btn.clicked.connect(self.insert_filename_token)
        self.title_template_input.textChanged.connect(self.update_filename_preview)
    def configure_responsive_ui(self):
        for widget in [
            self.url_input,
            self.ytdlp_input,
            self.output_input,
            self.ffmpeg_input,
            self.title_template_input,
            self.format_input,
            self.extra_args_input,
            self.cookies_input,
            self.preset_name_input,
        ]:
            widget.setMinimumHeight(36)

        for widget in [
            self.scope_combo,
            self.quality_combo,
            self.audio_preference_combo,
            self.audio_format_combo,
            self.subtitle_lang_combo,
            self.naming_scheme_combo,
            self.insert_token_combo,
        ]:
            widget.setMinimumHeight(36)
            widget.setMinimumWidth(140)

        for widget in [
            self.example_btn,
            self.info_btn,
            self.format_btn,
            self.queue_btn,
            self.download_btn,
            self.stop_btn,
            self.choose_ytdlp_btn,
            self.choose_output_btn,
            self.choose_ffmpeg_btn,
            self.insert_token_btn,
            self.build_cmd_btn,
            self.apply_format_btn,
            self.refresh_status_btn,
            self.save_preset_btn,
            self.load_preset_btn,
            self.delete_preset_btn,
            self.quick_video_btn,
            self.quick_audio_btn,
            self.quick_channel_video_btn,
            self.quick_channel_audio_btn,
        ]:
            widget.setMinimumHeight(38)
            widget.setMinimumWidth(96)

        self.url_input.setMinimumWidth(420)
        self.command_preview.setMinimumHeight(150)
        self.format_table.setMinimumHeight(260)
        self.queue_list.setMinimumHeight(140)

    def wrap_in_scroll_area(self, widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    # -------------------------------------------------
    # Runtime tool detection / environment
    # -------------------------------------------------
    def apply_detected_runtime_tools(self):
        detected_ytdlp = self.runtime_tools.get("ytdlp")
        detected_ffmpeg_dir = self.runtime_tools.get("ffmpeg_dir")

        if (
            not self.ytdlp_input.text().strip()
            or self.ytdlp_input.text().strip() == "yt-dlp"
        ) and detected_ytdlp:
            self.ytdlp_input.setText(detected_ytdlp)
            self.log_output.appendPlainText(f"已自動偵測 yt-dlp：{detected_ytdlp}")

        if not self.ffmpeg_input.text().strip() and detected_ffmpeg_dir:
            self.ffmpeg_input.setText(detected_ffmpeg_dir)
            self.log_output.appendPlainText(
                f"已自動偵測 FFmpeg 資料夾：{detected_ffmpeg_dir}"
            )

        if not self.output_input.text().strip():
            default_output_dir = self.get_default_output_dir()
            self.output_input.setText(default_output_dir)
            self.log_output.appendPlainText(
                f"已設定預設輸出資料夾：{default_output_dir}"
            )

    def resolve_from_path_only(self, command_name: str) -> str | None:
        path_env = os.environ.get("PATH", "")
        if not path_env:
            return None

        names = [command_name]
        if sys.platform == "win32" and not command_name.lower().endswith(".exe"):
            names.append(f"{command_name}.exe")

        for folder in path_env.split(os.pathsep):
            if not folder:
                continue
            for name in names:
                candidate = Path(folder) / name
                if candidate.exists() and candidate.is_file():
                    return str(candidate)

        return None

    def resolve_command(self, text_value, fallback_name):
        value = text_value.strip()

        if value:
            lowered = value.lower()
            if lowered in {"yt-dlp", "yt-dlp.exe"}:
                resolved = self.resolve_from_path_only("yt-dlp")
                if resolved:
                    return resolved

            if Path(value).exists():
                return value

            resolved = shutil.which(value)
            if resolved:
                return resolved

            return None

        if fallback_name.lower() == "yt-dlp":
            resolved = self.resolve_from_path_only("yt-dlp")
            if resolved:
                return resolved

        return shutil.which(fallback_name)

    def resolve_ffmpeg_path(self):
        value = self.ffmpeg_input.text().strip()
        binary_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        if value:
            path = Path(value)
            if path.is_file():
                return str(path)
            if path.is_dir():
                candidate = path / binary_name
                if candidate.exists():
                    return str(candidate)
                return None
            resolved = shutil.which(value)
            if resolved:
                return resolved
            return None
        return shutil.which("ffmpeg")

    def check_program_version(self, cmd_path, version_arg="--version"):
        if not cmd_path:
            return False, "未找到"

        try:
            result = subprocess.run(
                [cmd_path, version_arg],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return False, f"檢查逾時：{cmd_path}"
        except Exception as exc:
            return False, f"檢查失敗：{exc}"

        output = (result.stdout or result.stderr or "").strip().splitlines()
        first_line = output[0] if output else "可執行，但無版本資訊"
        return (result.returncode == 0), first_line

    def refresh_environment_status(self):
        ytdlp_text = self.ytdlp_input.text().strip()
        ffmpeg_text = self.ffmpeg_input.text().strip()
        ytdlp_path = self.resolve_command(ytdlp_text, "yt-dlp")
        ffmpeg_path = self.resolve_ffmpeg_path()
        ytdlp_ok, ytdlp_msg = self.check_program_version(ytdlp_path, "--version")
        ffmpeg_ok, ffmpeg_msg = self.check_program_version(ffmpeg_path, "-version")

        if ytdlp_ok:
            source = "手動指定或自動帶入"
            detected = self.runtime_tools.get("ytdlp")
            if (
                detected
                and ytdlp_path
                and Path(ytdlp_path).resolve() == Path(detected).resolve()
            ):
                source = "程式同層 / tools 偵測"
            elif ytdlp_text in {"", "yt-dlp"}:
                source = "PATH"
            self.ytdlp_status_label.setText(f"yt-dlp：已找到（{source}） / {ytdlp_msg}")
        else:
            self.ytdlp_status_label.setText(f"yt-dlp：未找到 / {ytdlp_msg}")

        if ffmpeg_ok:
            source = "手動指定或自動帶入"
            detected_dir = self.runtime_tools.get("ffmpeg_dir")
            if (
                detected_dir
                and ffmpeg_path
                and Path(ffmpeg_path).resolve().parent == Path(detected_dir).resolve()
            ):
                source = "程式同層 / tools 偵測"
            elif ffmpeg_text == "":
                source = "PATH"
            self.ffmpeg_status_label.setText(
                f"FFmpeg：已找到（{source}） / {ffmpeg_msg}"
            )
        else:
            self.ffmpeg_status_label.setText(f"FFmpeg：未找到 / {ffmpeg_msg}")

    # -------------------------------------------------
    # Simple UX state / presets
    # -------------------------------------------------
    def fill_example(self):
        self.url_input.setText("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.log_output.appendPlainText("已填入範例網址")

    def on_track_options_changed(self):
        video_on = self.download_video_checkbox.isChecked()
        audio_on = self.download_audio_checkbox.isChecked()

        if not video_on and not audio_on:
            self.download_audio_checkbox.setChecked(True)
            audio_on = True

        both_on = video_on and audio_on
        self.merge_output_checkbox.setEnabled(both_on)
        self.audio_preference_label.setVisible(both_on)
        self.audio_preference_combo.setVisible(both_on)
        self.audio_format_combo.setEnabled(audio_on)

        self.quality_combo.clear()
        if both_on:
            self.quality_combo.addItem("最佳畫質（推薦）", "va_best")
            self.quality_combo.addItem("1080p 以下最佳", "va_1080")
            self.quality_combo.addItem("720p 以下最佳", "va_720")
            self.quality_combo.addItem("MP4 相容優先", "va_mp4")
            self.human_hint_label.setText(
                "影片與音訊會一起下載；音訊偏好可另外選自動最佳、M4A 或 OPUS。批次時也會套用同一套策略。"
            )
        elif video_on:
            self.quality_combo.addItem("最佳畫質（只有畫面）", "v_best")
            self.quality_combo.addItem("1080p 以下", "v_1080")
            self.quality_combo.addItem("720p 以下", "v_720")
            self.human_hint_label.setText("只下載畫面流，通常不含聲音。")
        else:
            self.quality_combo.addItem("最佳音質（推薦）", "a_best")
            self.quality_combo.addItem("M4A 優先", "a_m4a")
            self.quality_combo.addItem("OPUS 優先", "a_opus")
            self.human_hint_label.setText(
                "只下載音訊；輸出格式可轉成 MP3、M4A、OPUS 等。"
            )
            if not self.embed_thumbnail_checkbox.isChecked():
                self.embed_thumbnail_checkbox.setChecked(True)

    def insert_filename_token(self):
        token = self.insert_token_combo.currentData()
        cursor = self.title_template_input.cursorPosition()
        text = self.title_template_input.text()
        self.title_template_input.setText(text[:cursor] + token + text[cursor:])
        self.title_template_input.setFocus()
        self.title_template_input.setCursorPosition(cursor + len(token))
        self.update_filename_preview()

    def on_use_custom_format_changed(self):
        custom_on = self.use_custom_format_checkbox.isChecked()
        self.format_input.setEnabled(custom_on)
        self.quality_combo.setEnabled(not custom_on)
        self.audio_preference_combo.setEnabled(
            not custom_on
            and self.download_video_checkbox.isChecked()
            and self.download_audio_checkbox.isChecked()
        )

    def get_current_preset_state(self):
        return {
            "ytdlp": self.ytdlp_input.text().strip(),
            "output_dir": self.output_input.text().strip(),
            "batch_list_folder": self.batch_list_folder_checkbox.isChecked(),
            "ffmpeg_dir": self.ffmpeg_input.text().strip(),
            "title_template": self.title_template_input.text().strip(),
            "format": self.format_input.text().strip(),
            "extra_args": self.extra_args_input.text().strip(),
            "cookies": self.cookies_input.text().strip(),
            "scope": self.scope_combo.currentData(),
            "video_on": self.download_video_checkbox.isChecked(),
            "audio_on": self.download_audio_checkbox.isChecked(),
            "merge_output": self.merge_output_checkbox.isChecked(),
            "audio_preference": self.audio_preference_combo.currentData(),
            "audio_format": self.audio_format_combo.currentData(),
            "embed_thumbnail": self.embed_thumbnail_checkbox.isChecked(),
            "embed_metadata": self.embed_metadata_checkbox.isChecked(),
            "subtitle_manual": self.write_subs_checkbox.isChecked(),
            "subtitle_auto": self.write_auto_subs_checkbox.isChecked(),
            "subtitle_lang": self.subtitle_lang_combo.currentText(),
            "quality_strategy": self.quality_combo.currentData(),
            "naming_scheme": self.naming_scheme_combo.currentData(),
            "use_custom_format": self.use_custom_format_checkbox.isChecked(),
        }

    def apply_preset_state(self, data):
        self.ytdlp_input.setText(data.get("ytdlp", self.ytdlp_input.text()))
        self.output_input.setText(
            data.get("output_dir") or self.get_default_output_dir()
        )
        self.batch_list_folder_checkbox.setChecked(
            bool(data.get("batch_list_folder", True))
        )
        self.ffmpeg_input.setText(data.get("ffmpeg_dir", ""))
        self.title_template_input.setText(
            data.get("title_template", "%(title)s.%(ext)s")
        )
        self.format_input.setText(data.get("format", self.format_input.text()))
        self.extra_args_input.setText(data.get("extra_args", ""))
        self.cookies_input.setText(data.get("cookies", ""))

        idx = self.scope_combo.findData(data.get("scope", "auto"))
        if idx >= 0:
            self.scope_combo.setCurrentIndex(idx)

        self.download_video_checkbox.setChecked(bool(data.get("video_on", True)))
        self.download_audio_checkbox.setChecked(bool(data.get("audio_on", True)))
        self.merge_output_checkbox.setChecked(bool(data.get("merge_output", True)))

        idx = self.audio_preference_combo.findData(data.get("audio_preference", "auto"))
        if idx >= 0:
            self.audio_preference_combo.setCurrentIndex(idx)

        idx = self.audio_format_combo.findData(data.get("audio_format", "mp3"))
        if idx >= 0:
            self.audio_format_combo.setCurrentIndex(idx)

        self.embed_thumbnail_checkbox.setChecked(
            bool(data.get("embed_thumbnail", False))
        )
        self.embed_metadata_checkbox.setChecked(bool(data.get("embed_metadata", True)))
        self.write_subs_checkbox.setChecked(bool(data.get("subtitle_manual", False)))
        self.write_auto_subs_checkbox.setChecked(bool(data.get("subtitle_auto", False)))
        self.subtitle_lang_combo.setCurrentText(data.get("subtitle_lang", "自動"))
        self.use_custom_format_checkbox.setChecked(
            bool(data.get("use_custom_format", False))
        )

        self.on_track_options_changed()

        idx = self.quality_combo.findData(
            data.get("quality_strategy", self.quality_combo.currentData())
        )
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)

        idx = self.naming_scheme_combo.findData(data.get("naming_scheme", "title_only"))
        if idx >= 0:
            self.naming_scheme_combo.setCurrentIndex(idx)
        self.on_naming_scheme_changed()
        self.on_use_custom_format_changed()
        self.refresh_environment_status()

    def refresh_preset_list(self):
        self.preset_list.clear()
        for name in sorted(self.presets.keys(), key=lambda x: x.lower()):
            self.preset_list.addItem(name)

    def save_preset(self):
        name = self.preset_name_input.text().strip()
        if not name:
            self.log_output.appendPlainText("請先輸入預設名稱")
            return
        self.presets[name] = self.get_current_preset_state()
        save_presets_to_disk(self.presets)
        self.refresh_preset_list()
        self.log_output.appendPlainText(f"已儲存預設：{name}")

    def load_selected_preset(self):
        item = self.preset_list.currentItem()
        if not item:
            self.log_output.appendPlainText("請先選擇一個預設")
            return
        name = item.text()
        data = self.presets.get(name)
        if not data:
            self.log_output.appendPlainText("找不到這個預設")
            return
        self.apply_preset_state(data)
        self.preset_name_input.setText(name)
        self.log_output.appendPlainText(f"已載入預設：{name}")

    def delete_selected_preset(self):
        item = self.preset_list.currentItem()
        if not item:
            self.log_output.appendPlainText("請先選擇要刪除的預設")
            return
        name = item.text()
        if name in self.presets:
            del self.presets[name]
            save_presets_to_disk(self.presets)
            self.refresh_preset_list()
            self.log_output.appendPlainText(f"已刪除預設：{name}")

    def apply_quick_profile(self, profile_name):
        if profile_name == "single_video":
            self.scope_combo.setCurrentIndex(self.scope_combo.findData("single"))
            self.download_video_checkbox.setChecked(True)
            self.download_audio_checkbox.setChecked(True)
            self.merge_output_checkbox.setChecked(True)
            self.audio_preference_combo.setCurrentIndex(
                self.audio_preference_combo.findData("auto")
            )
            self.naming_scheme_combo.setCurrentIndex(
                self.naming_scheme_combo.findData("title_only")
            )
        elif profile_name == "single_audio":
            self.scope_combo.setCurrentIndex(self.scope_combo.findData("single"))
            self.download_video_checkbox.setChecked(False)
            self.download_audio_checkbox.setChecked(True)
            self.audio_format_combo.setCurrentIndex(
                self.audio_format_combo.findData("mp3")
            )
            self.naming_scheme_combo.setCurrentIndex(
                self.naming_scheme_combo.findData("title_only")
            )
            self.embed_thumbnail_checkbox.setChecked(True)
        elif profile_name == "channel_video":
            self.scope_combo.setCurrentIndex(self.scope_combo.findData("channel"))
            self.download_video_checkbox.setChecked(True)
            self.download_audio_checkbox.setChecked(True)
            self.merge_output_checkbox.setChecked(True)
            self.audio_preference_combo.setCurrentIndex(
                self.audio_preference_combo.findData("auto")
            )
            self.naming_scheme_combo.setCurrentIndex(
                self.naming_scheme_combo.findData("channel_date_title")
            )
        elif profile_name == "channel_audio":
            self.scope_combo.setCurrentIndex(self.scope_combo.findData("channel"))
            self.download_video_checkbox.setChecked(False)
            self.download_audio_checkbox.setChecked(True)
            self.audio_format_combo.setCurrentIndex(
                self.audio_format_combo.findData("mp3")
            )
            self.naming_scheme_combo.setCurrentIndex(
                self.naming_scheme_combo.findData("channel_date_title")
            )
            self.embed_thumbnail_checkbox.setChecked(True)
        self.on_track_options_changed()
        self.on_naming_scheme_changed()
        self.log_output.appendPlainText(f"已套用快速模式：{profile_name}")
    def get_creator_name_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        return parts[0] if parts else "未知創作者"

    def is_streetvoice_collection_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if "streetvoice.com" not in parsed.netloc.lower():
            return False

        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return False

        # 單曲：/username/songs/123456/
        if len(parts) >= 3 and parts[1] == "songs" and parts[2].isdigit():
            return False

        # 創作者首頁：/username/
        if len(parts) == 1:
            return True

        # 全部歌曲頁：/username/songs/
        if len(parts) >= 2 and parts[1] == "songs":
            return True

        return False

    def fetch_webpage_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
        )
        with urlopen(request, timeout=15) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

    def normalize_streetvoice_song_url(self, url: str) -> str:
        return url.split("?", 1)[0].split("#", 1)[0].rstrip("/") + "/"

    def normalize_streetvoice_page_url(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path or "/"
        if path.endswith("/songs"):
            path += "/"
        return urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc,
                path,
                "",
                parsed.query,
                "",
            )
        )

    def get_streetvoice_songs_page_url(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]

        # 創作者首頁 /username/ -> /username/songs/
        if len(parts) == 1:
            return self.normalize_streetvoice_page_url(
                f"{parsed.scheme or 'https'}://{parsed.netloc}/{parts[0]}/songs/"
            )

        return self.normalize_streetvoice_page_url(url)

    def extract_streetvoice_next_page_url(self, page_url: str, html: str) -> str | None:
        anchor_pattern = re.compile(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for href, inner_html in anchor_pattern.findall(html):
            label = re.sub(r"<[^>]+>", "", inner_html)
            label = re.sub(r"\s+", "", unescape(label))
            if "下一頁" in label:
                return self.normalize_streetvoice_page_url(
                    urljoin(page_url, unescape(href))
                )

        return None

    def is_streetvoice_song_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if "streetvoice.com" not in parsed.netloc.lower():
            return False

        parts = [part for part in parsed.path.split("/") if part]
        return len(parts) >= 3 and parts[1] == "songs" and parts[2].isdigit()

    def extract_streetvoice_static_lyrics(self, html_text: str) -> str | None:
        match = re.search(
            r"<h2\b[^>]*>\s*歌詞.*?</h2>\s*"
            r"<div\b[^>]*class=[\"'][^\"']*dynamic-height[^\"']*[\"'][^>]*>(.*?)</div>",
            html_text,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None

        lyrics_html = match.group(1)

        lyrics_html = re.sub(
            r"<a\b[^>]*class=[\"'][^\"']*read-more[^\"']*[\"'][^>]*>.*?</a>",
            "",
            lyrics_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        lyrics_html = re.sub(r"<br\s*/?>", "\n", lyrics_html, flags=re.IGNORECASE)
        lyrics_html = re.sub(r"</p\s*>", "\n", lyrics_html, flags=re.IGNORECASE)
        lyrics_html = re.sub(r"<p\b[^>]*>", "", lyrics_html, flags=re.IGNORECASE)
        lyrics_html = re.sub(r"<[^>]+>", "", lyrics_html)

        text = unescape(lyrics_html).replace("\xa0", " ").strip()
        if not text:
            return None

        normalized_lines = []
        last_blank = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                if normalized_lines and not last_blank:
                    normalized_lines.append("")
                last_blank = True
                continue
            normalized_lines.append(line)
            last_blank = False

        while normalized_lines and not normalized_lines[-1]:
            normalized_lines.pop()

        result = "\n".join(normalized_lines).strip()
        return result or None

    def normalize_logged_output_path(self, logged_path: str, output_dir: str) -> str:
        cleaned = logged_path.strip().strip('"')
        if not cleaned:
            return ""

        path = Path(cleaned)
        if path.is_absolute():
            return str(path)

        base_dir = Path(output_dir) if output_dir else Path.cwd()
        return str((base_dir / path).resolve())

    def update_current_task_output_from_log(self, clean_line: str):
        if not self.current_task:
            return

        patterns = [
            r"^\[download\] Destination: (.+)$",
            r"^\[ExtractAudio\] Destination: (.+)$",
            r'^\[Merger\] Merging formats into "(.+)"$',
            r'^\[EmbedThumbnail\] Adding thumbnail to "(.+)"$',
            r'^\[Metadata\] Adding metadata to "(.+)"$',
            r"^\[download\] (.+) has already been downloaded$",
        ]

        for pattern in patterns:
            match = re.match(pattern, clean_line)
            if not match:
                continue

            resolved_path = self.normalize_logged_output_path(
                match.group(1),
                self.current_task.get("output_dir", ""),
            )
            if resolved_path:
                self.current_task["downloaded_file_path"] = resolved_path
            return

    def save_streetvoice_static_lyrics_for_task(self, task: dict):
        if not task or task.get("lyrics_saved"):
            return

        url = task.get("url", "")
        if not self.is_streetvoice_song_url(url):
            return

        output_file = task.get("downloaded_file_path")
        if not output_file:
            self.log_output.appendPlainText("StreetVoice 歌詞略過：找不到輸出檔路徑")
            return

        try:
            html_text = self.fetch_webpage_text(url)
        except Exception as exc:
            self.log_output.appendPlainText(f"StreetVoice 歌詞抓取失敗：{url} / {exc}")
            return

        lyrics_text = self.extract_streetvoice_static_lyrics(html_text)
        if not lyrics_text:
            self.log_output.appendPlainText("StreetVoice：這首歌沒有找到靜態歌詞")
            return

        lyrics_path = Path(output_file).with_suffix(".txt")
        lyrics_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            lyrics_path.write_text(lyrics_text, encoding="utf-8")
        except Exception as exc:
            self.log_output.appendPlainText(
                f"StreetVoice 歌詞儲存失敗：{lyrics_path} / {exc}"
            )
            return

        task["lyrics_saved"] = True
        task["lyrics_file_path"] = str(lyrics_path)
        self.log_output.appendPlainText(f"已儲存靜態歌詞：{lyrics_path}")

    def extract_streetvoice_song_urls(self, url: str) -> list[str]:
        song_pattern = re.compile(
            r"https?://streetvoice[.]com/[^/\\\"'<>]+/songs/[0-9]+/?|/[^/\\\"'<>]+/songs/[0-9]+/?",
            re.IGNORECASE,
        )

        found: list[str] = []
        seen_songs: set[str] = set()
        visited_pages: set[str] = set()
        queued_pages = [self.get_streetvoice_songs_page_url(url)]
        max_pages = 50

        while queued_pages and len(visited_pages) < max_pages:
            page_url = self.normalize_streetvoice_page_url(queued_pages.pop(0))
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)

            try:
                html = self.fetch_webpage_text(page_url)
            except Exception as exc:
                self.log_output.appendPlainText(
                    f"StreetVoice 頁面讀取失敗：{page_url} / {exc}"
                )
                continue

            for match in song_pattern.findall(html):
                full_url = urljoin(page_url, match)
                normalized_song = self.normalize_streetvoice_song_url(full_url)
                if normalized_song not in seen_songs:
                    seen_songs.add(normalized_song)
                    found.append(normalized_song)

            next_page_url = self.extract_streetvoice_next_page_url(page_url, html)
            if next_page_url and next_page_url not in visited_pages:
                queued_pages.append(next_page_url)

        if queued_pages:
            self.log_output.appendPlainText(
                "StreetVoice 分頁超過 50 頁，已停止繼續展開"
            )

        return found

    def expand_source_urls(self, url: str) -> list[str]:
        if self.is_streetvoice_collection_url(url):
            song_urls = self.extract_streetvoice_song_urls(url)
            if song_urls:
                self.log_output.appendPlainText(
                    f"StreetVoice 創作者頁已展開，共找到 {len(song_urls)} 首歌曲"
                )
                return song_urls
            raise ValueError("無法從 StreetVoice 創作者頁擷取歌曲連結")
        return [url]

    def build_task_for_url(self, url: str, batch_folder_name: str | None = None):
        if not url:
            raise ValueError("請先輸入網址")

        args = []
        output_dir = self.get_effective_output_dir()
        ffmpeg_dir = self.ffmpeg_input.text().strip()
        title_template = self.title_template_input.text().strip()
        extra_args = self.extra_args_input.text().strip()
        cookies = self.cookies_input.text().strip()
        yt_dlp_cmd = self.ytdlp_input.text().strip() or "yt-dlp"

        if output_dir:
            args += ["-P", output_dir]
        if ffmpeg_dir:
            args += ["--ffmpeg-location", ffmpeg_dir]

        args += self.build_scope_args()

        effective_title_template = self.build_effective_title_template(
            title_template, batch_folder_name=batch_folder_name
        )
        if effective_title_template:
            args += ["-o", effective_title_template]

        args += self.build_media_args()

        if cookies:
            args += ["--cookies", cookies]
        if self.embed_thumbnail_checkbox.isChecked():
            args += ["--embed-thumbnail"]
        if self.embed_metadata_checkbox.isChecked():
            args += ["--embed-metadata"]

        args += self.build_subtitle_args()
        args += ["--newline"]
        args += ["--no-colors"]
        args += [
            "--progress-template",
            "download:[GUI] %(progress._percent_str)s|%(progress.eta)s|%(info.id)s",
        ]

        if extra_args:
            args += shlex.split(extra_args, posix=(sys.platform != "win32"))

        args.append(url)
        return {
            "url": url,
            "program": yt_dlp_cmd,
            "args": args,
            "status": "等待中",
            "output_dir": output_dir,
            "batch_folder_name": batch_folder_name,
            "downloaded_file_path": None,
            "lyrics_saved": False,
            "lyrics_file_path": None,
        }

    # -------------------------------------------------
    # Read info / formats
    # -------------------------------------------------
    def load_info_in_background(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_output.appendPlainText("請先輸入網址")
            return

        if self.is_streetvoice_collection_url(url):
            try:
                song_urls = self.expand_source_urls(url)
            except ValueError as exc:
                self.log_output.appendPlainText(str(exc))
                return

            creator_name = self.get_creator_name_from_url(url)
            self.info_title.setText(f"標題：StreetVoice / {creator_name}")
            self.info_channel.setText(f"作者：{creator_name}")
            self.info_duration.setText(f"長度：共 {len(song_urls)} 首")
            self.info_type.setText("類型：StreetVoice 創作者頁（已展開成歌曲清單）")
            self.log_output.appendPlainText("StreetVoice 創作者頁資訊讀取完成")
            return

        if self.info_thread is not None:
            self.log_output.appendPlainText("目前已有資訊讀取工作在執行中")
            return

        self.info_btn.setEnabled(False)
        self.info_btn.setText("讀取中...")
        self.progress_bar.setRange(0, 0)

        yt_dlp_cmd = self.ytdlp_input.text().strip() or "yt-dlp"
        self.info_thread = QThread()
        self.info_worker = InfoWorker(url, yt_dlp_cmd)
        self.info_worker.moveToThread(self.info_thread)
        self.info_thread.started.connect(self.info_worker.run)
        self.info_worker.result.connect(self.update_info_panel)
        self.info_worker.error.connect(self.on_info_error)
        self.info_worker.log.connect(self.log_output.appendPlainText)
        self.info_worker.finished.connect(self.info_thread.quit)
        self.info_worker.finished.connect(self.info_worker.deleteLater)
        self.info_thread.finished.connect(self.info_thread.deleteLater)
        self.info_thread.finished.connect(self.on_info_thread_finished)
        self.info_thread.start()

    def load_formats_in_background(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_output.appendPlainText("請先輸入網址")
            return

        if self.is_streetvoice_collection_url(url):
            self.log_output.appendPlainText(
                "StreetVoice 創作者頁目前只支援展開歌曲清單；格式讀取請改用單首歌曲網址"
            )
            return

        if self.format_thread is not None:
            self.log_output.appendPlainText("目前已有格式讀取工作在執行中")
            return

        self.format_btn.setEnabled(False)
        self.format_btn.setText("讀取中...")
        self.progress_bar.setRange(0, 0)

        yt_dlp_cmd = self.ytdlp_input.text().strip() or "yt-dlp"
        self.format_thread = QThread()
        self.format_worker = FormatWorker(url, yt_dlp_cmd)
        self.format_worker.moveToThread(self.format_thread)
        self.format_thread.started.connect(self.format_worker.run)
        self.format_worker.result.connect(self.on_format_result)
        self.format_worker.error.connect(self.on_format_error)
        self.format_worker.log.connect(self.log_output.appendPlainText)
        self.format_worker.finished.connect(self.format_thread.quit)
        self.format_worker.finished.connect(self.format_worker.deleteLater)
        self.format_thread.finished.connect(self.format_thread.deleteLater)
        self.format_thread.finished.connect(self.on_format_thread_finished)
        self.format_thread.start()

    @Slot(dict)
    def update_info_panel(self, data):
        data_type = data.get("_type", "video")
        if data_type == "playlist":
            title = data.get("title", "未知播放清單")
            uploader = (
                data.get("uploader")
                or data.get("channel")
                or data.get("playlist_uploader")
                or "未知"
            )
            count = len(data.get("entries") or [])
            self.info_title.setText(f"標題：{title}")
            self.info_channel.setText(f"作者：{uploader}")
            self.info_duration.setText(f"長度：共 {count} 項")
            self.info_type.setText("類型：播放清單 / 頻道")
        else:
            self.info_title.setText(f"標題：{data.get('title', '未知標題')}")
            self.info_channel.setText(
                f"作者：{data.get('uploader') or data.get('channel') or '未知'}"
            )
            self.info_duration.setText(f"長度：{format_seconds(data.get('duration'))}")
            self.info_type.setText("類型：單支影片")
        self.log_output.appendPlainText("影片資訊讀取完成")

    @Slot(dict)
    def on_format_result(self, data):
        self.update_info_panel(data)
        formats = data.get("formats") or []
        self.populate_format_table(formats)
        self.log_output.appendPlainText(f"格式列表讀取完成，共 {len(formats)} 筆")

    def populate_format_table(self, formats):
        self.format_table.setRowCount(0)
        for fmt in formats:
            row = self.format_table.rowCount()
            self.format_table.insertRow(row)

            resolution = fmt.get("resolution")
            if not resolution:
                if fmt.get("width") and fmt.get("height"):
                    resolution = f"{fmt.get('width')}x{fmt.get('height')}"
                elif fmt.get("height"):
                    resolution = f"{fmt.get('height')}p"
                else:
                    resolution = "audio only"

            values = [
                str(fmt.get("format_id", "")),
                str(fmt.get("ext", "")),
                str(resolution),
                str(fmt.get("fps") or "-"),
                str(fmt.get("vcodec") or "-"),
                str(fmt.get("acodec") or "-"),
                format_bytes(fmt.get("filesize") or fmt.get("filesize_approx")),
                str(fmt.get("format_note") or fmt.get("format") or ""),
            ]

            for col, value in enumerate(values):
                self.format_table.setItem(row, col, QTableWidgetItem(value))

        self.format_table.resizeColumnsToContents()
        self.format_preview_label.setText("已選格式：尚未選擇")

    def preview_selected_format(self):
        rows = sorted(
            {index.row() for index in self.format_table.selectionModel().selectedRows()}
        )
        if not rows:
            self.format_preview_label.setText("已選格式：尚未選擇")
            return

        format_ids = []
        for row in rows:
            item = self.format_table.item(row, 0)
            if item:
                format_ids.append(item.text())

        self.format_preview_label.setText(f"已選格式：{'+'.join(format_ids)}")

    def apply_selected_format(self):
        rows = sorted(
            {index.row() for index in self.format_table.selectionModel().selectedRows()}
        )
        if not rows:
            self.log_output.appendPlainText("請先在格式表格選擇一列或多列")
            return

        format_ids = []
        for row in rows:
            item = self.format_table.item(row, 0)
            if item and item.text():
                format_ids.append(item.text())

        if not format_ids:
            self.log_output.appendPlainText("找不到可用的 format_id")
            return

        self.use_custom_format_checkbox.setChecked(True)
        self.format_input.setText("+".join(format_ids))
        self.tabs.setCurrentIndex(1)
        self.on_use_custom_format_changed()
        self.log_output.appendPlainText(f"已套用格式：{self.format_input.text()}")

    @Slot(str)
    def on_info_error(self, message):
        self.log_output.appendPlainText(message)

    @Slot()
    def on_info_thread_finished(self):
        if self.format_thread is None and (
            not self.download_process
            or self.download_process.state() == QProcess.NotRunning
        ):
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        self.info_btn.setEnabled(True)
        self.info_btn.setText("讀取資訊")
        self.info_thread = None
        self.info_worker = None

    @Slot(str)
    def on_format_error(self, message):
        self.log_output.appendPlainText(message)

    @Slot()
    def on_format_thread_finished(self):
        if self.info_thread is None and (
            not self.download_process
            or self.download_process.state() == QProcess.NotRunning
        ):
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        self.format_btn.setEnabled(True)
        self.format_btn.setText("讀取格式")
        self.format_thread = None
        self.format_worker = None

    def choose_ytdlp_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇 yt-dlp 可執行檔",
            "",
            "Executable Files (*.exe);;All Files (*.*)",
        )
        if file_path:
            self.ytdlp_input.setText(file_path)
            self.refresh_environment_status()
            self.log_output.appendPlainText(f"已選擇 yt-dlp：{file_path}")

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇下載資料夾")
        if folder:
            self.output_input.setText(folder)
            self.log_output.appendPlainText(f"已選擇輸出資料夾：{folder}")

    def choose_ffmpeg_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇 ffmpeg 所在資料夾")
        if folder:
            self.ffmpeg_input.setText(folder)
            self.refresh_environment_status()
            self.log_output.appendPlainText(f"已選擇 ffmpeg 資料夾：{folder}")

    def get_default_output_dir(self) -> str:
        base_dir_text = self.runtime_tools.get("base_dir")
        app_dir = (
            Path(base_dir_text).resolve() if base_dir_text else Path.cwd().resolve()
        )
        default_dir = app_dir.parent / "yt-dlp.gui downloads"
        default_dir.mkdir(parents=True, exist_ok=True)
        return str(default_dir)

    def get_effective_output_dir(self) -> str:
        value = self.output_input.text().strip()
        if value:
            Path(value).mkdir(parents=True, exist_ok=True)
            return value
        return self.get_default_output_dir()

    def sanitize_path_component(self, value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", value or "")
        cleaned = cleaned.strip().strip(".")
        return cleaned or "批次下載"

    def get_batch_folder_name(
        self, source_url: str, expanded_urls: list[str]
    ) -> str | None:
        if not self.batch_list_folder_checkbox.isChecked():
            return None
        if len(expanded_urls) <= 1:
            return None

        if self.is_streetvoice_collection_url(source_url):
            return self.sanitize_path_component(
                self.get_creator_name_from_url(source_url)
            )

        return None

    def build_effective_title_template(
        self, title_template: str, batch_folder_name: str | None = None
    ) -> str:
        effective_template = title_template.strip()

        if batch_folder_name:
            if not effective_template:
                effective_template = "%(title)s.%(ext)s"
            effective_template = f"{batch_folder_name}/{effective_template}"

        return effective_template

    def build_scope_args(self):
        scope = self.scope_combo.currentData()
        if scope == "single":
            return ["--no-playlist"]
        return []

    def build_subtitle_args(self):
        args = []
        if self.write_subs_checkbox.isChecked():
            args.append("--write-subs")
        if self.write_auto_subs_checkbox.isChecked():
            args.append("--write-auto-subs")

        lang = self.subtitle_lang_combo.currentText().strip()
        if (
            lang
            and lang != "自動"
            and (
                self.write_subs_checkbox.isChecked()
                or self.write_auto_subs_checkbox.isChecked()
            )
        ):
            args += ["--sub-langs", lang]

        return args

    def build_strategy_format(self):
        strategy = self.quality_combo.currentData() or "va_best"
        audio_pref = self.audio_preference_combo.currentData() or "auto"
        video_on = self.download_video_checkbox.isChecked()
        audio_on = self.download_audio_checkbox.isChecked()

        if video_on and audio_on:
            pref_audio = {
                "auto": "bestaudio",
                "m4a": "bestaudio[ext=m4a]/bestaudio",
                "opus": "bestaudio[ext=webm]/bestaudio",
            }[audio_pref]

            mapping = {
                "va_best": f"bestvideo+{pref_audio}/best",
                "va_1080": f"bestvideo[height<=1080]+{pref_audio}/best[height<=1080]/best",
                "va_720": f"bestvideo[height<=720]+{pref_audio}/best[height<=720]/best",
                "va_mp4": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            }
            return mapping.get(strategy, f"bestvideo+{pref_audio}/best")

        if video_on:
            mapping = {
                "v_best": "bestvideo",
                "v_1080": "bestvideo[height<=1080]",
                "v_720": "bestvideo[height<=720]",
            }
            return mapping.get(strategy, "bestvideo")

        mapping = {
            "a_best": "bestaudio/best",
            "a_m4a": "bestaudio[ext=m4a]/bestaudio/best",
            "a_opus": "bestaudio[ext=webm]/bestaudio/best",
        }
        return mapping.get(strategy, "bestaudio/best")

    def build_media_args(self):
        video_on = self.download_video_checkbox.isChecked()
        audio_on = self.download_audio_checkbox.isChecked()
        use_custom = self.use_custom_format_checkbox.isChecked()

        fmt_value = (
            self.format_input.text().strip()
            if use_custom
            else self.build_strategy_format()
        )
        args = ["-f", fmt_value]

        if video_on and audio_on:
            if self.merge_output_checkbox.isChecked():
                args += ["--merge-output-format", "mp4"]
        elif audio_on and not video_on:
            args += ["-x", "--audio-format", self.audio_format_combo.currentData()]

        return args

    def build_task_from_ui(self):
        url = self.url_input.text().strip()
        preview_batch_folder_name = None

        if (
            self.is_streetvoice_collection_url(url)
            and self.batch_list_folder_checkbox.isChecked()
        ):
            preview_batch_folder_name = self.sanitize_path_component(
                self.get_creator_name_from_url(url)
            )

        return self.build_task_for_url(url, batch_folder_name=preview_batch_folder_name)

    def command_preview_from_task(self, task):
        if sys.platform == "win32":
            return subprocess.list2cmdline([task["program"], *task["args"]])
        return shlex.join([task["program"], *task["args"]])

    def build_command(self):
        try:
            task = self.build_task_from_ui()
        except ValueError as exc:
            self.log_output.appendPlainText(str(exc))
            self.command_preview.clear()
            return

        self.command_preview.setPlainText(self.command_preview_from_task(task))
        self.log_output.appendPlainText("已更新命令預覽")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_output.appendPlainText("請先輸入網址")
            return

        try:
            expanded_urls = self.expand_source_urls(url)
        except ValueError as exc:
            self.log_output.appendPlainText(str(exc))
            return

        batch_folder_name = self.get_batch_folder_name(url, expanded_urls)
        tasks = [
            self.build_task_for_url(song_url, batch_folder_name=batch_folder_name)
            for song_url in expanded_urls
        ]

        for task in tasks:
            item = QListWidgetItem(f"等待中：{task['url']}")
            task["item"] = item
            self.download_queue.append(task)
            self.queue_list.addItem(item)

        if batch_folder_name:
            output_root = Path(tasks[0]["output_dir"]) / batch_folder_name
            self.log_output.appendPlainText(f"批次資料夾：{output_root}")

        if len(tasks) == 1:
            self.log_output.appendPlainText(f"已加入佇列：{tasks[0]['url']}")
        else:
            self.log_output.appendPlainText(f"已加入佇列，共 {len(tasks)} 首")

        if (
            not self.download_process
            or self.download_process.state() == QProcess.NotRunning
        ):
            self.start_next_download()

    def download_now(self):
        if (
            self.download_process
            and self.download_process.state() != QProcess.NotRunning
        ):
            self.log_output.appendPlainText("目前已有任務在下載中，已改為加入佇列")
            self.add_to_queue()
            return

        url = self.url_input.text().strip()
        if not url:
            self.log_output.appendPlainText("請先輸入網址")
            return

        try:
            expanded_urls = self.expand_source_urls(url)
        except ValueError as exc:
            self.log_output.appendPlainText(str(exc))
            return

        batch_folder_name = self.get_batch_folder_name(url, expanded_urls)
        tasks = [
            self.build_task_for_url(song_url, batch_folder_name=batch_folder_name)
            for song_url in expanded_urls
        ]

        for offset, task in enumerate(tasks):
            item = QListWidgetItem(f"等待中：{task['url']}")
            task["item"] = item
            self.download_queue.insert(offset, task)
            self.queue_list.insertItem(offset, item)

        if batch_folder_name:
            output_root = Path(tasks[0]["output_dir"]) / batch_folder_name
            self.log_output.appendPlainText(f"批次資料夾：{output_root}")

        if len(tasks) == 1:
            self.log_output.appendPlainText(f"準備立即下載：{tasks[0]['url']}")
        else:
            self.log_output.appendPlainText(f"準備立即下載，共 {len(tasks)} 首")

        self.start_next_download()

    def start_next_download(self):
        if (
            self.download_process
            and self.download_process.state() != QProcess.NotRunning
        ):
            return

        if not self.download_queue:
            self.current_task = None
            self.download_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.log_output.appendPlainText("佇列已完成")
            return

        self.current_task = self.download_queue.pop(0)
        self.stop_requested = False
        item = self.current_task.get("item")
        if item:
            item.setText(f"下載中：{self.current_task['url']}")

        self.command_preview.setPlainText(
            self.command_preview_from_task(self.current_task)
        )

        self.download_process = QProcess(self)
        self.download_process.setProgram(self.current_task["program"])
        self.download_process.setArguments(self.current_task["args"])
        self.download_process.setProcessChannelMode(QProcess.SeparateChannels)

        self.process_buffer = ""
        self.stdout_buffer = b""
        self.stderr_buffer = b""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.download_process.readyReadStandardOutput.connect(self.read_process_stdout)
        self.download_process.readyReadStandardError.connect(self.read_process_stderr)
        self.download_process.finished.connect(self.on_download_finished)
        self.download_process.errorOccurred.connect(self.on_download_error)

        destination_dir = Path(self.current_task["output_dir"])
        if self.current_task.get("batch_folder_name"):
            destination_dir = destination_dir / self.current_task["batch_folder_name"]

        self.log_output.appendPlainText(f"開始下載：{self.current_task['url']}")
        self.log_output.appendPlainText(f"輸出位置：{destination_dir}")
        self.download_process.start()

    def decode_process_bytes(self, raw: bytes) -> str:
        if not raw:
            return ""

        encodings = []
        for encoding in [
            "utf-8",
            locale.getpreferredencoding(False),
            sys.getfilesystemencoding(),
            "cp950" if sys.platform == "win32" else None,
        ]:
            if encoding and encoding not in encodings:
                encodings.append(encoding)

        for encoding in encodings:
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue

        return raw.decode(encodings[0] if encodings else "utf-8", errors="replace")

    def consume_process_line(self, line: str):
        if not line.strip():
            return

        clean_line = self.ansi_escape_re.sub("", line).strip()
        if not clean_line:
            return

        self.update_current_task_output_from_log(clean_line)

        if "[GUI]" in clean_line:
            gui_index = clean_line.find("[GUI]")
            self.parse_progress_template_line(clean_line[gui_index:])
        else:
            self.log_output.appendPlainText(clean_line)

    def consume_process_bytes(self, stream_name: str, raw: bytes):
        if stream_name == "stdout":
            self.stdout_buffer += raw
            buffer = self.stdout_buffer
        else:
            self.stderr_buffer += raw
            buffer = self.stderr_buffer

        while b"\n" in buffer:
            line_bytes, buffer = buffer.split(b"\n", 1)
            line = self.decode_process_bytes(line_bytes.rstrip(b"\r"))
            self.consume_process_line(line)

        if stream_name == "stdout":
            self.stdout_buffer = buffer
        else:
            self.stderr_buffer = buffer

    def read_process_stdout(self):
        if not self.download_process:
            return
        raw = bytes(self.download_process.readAllStandardOutput())
        self.consume_process_bytes("stdout", raw)

    def read_process_stderr(self):
        if not self.download_process:
            return
        raw = bytes(self.download_process.readAllStandardError())
        self.consume_process_bytes("stderr", raw)

    def parse_progress_template_line(self, line: str):
        clean_line = self.ansi_escape_re.sub("", line).strip()

        if "[GUI]" in clean_line:
            clean_line = clean_line[clean_line.find("[GUI]") :]

        if clean_line.startswith("[GUI]"):
            clean_line = clean_line[6:].strip()

        parts = clean_line.split("|")
        if not parts:
            return

        percent_text = parts[0].replace("%", "").strip()
        eta_text = parts[1].strip() if len(parts) > 1 else "?"
        video_id = parts[2].strip() if len(parts) > 2 else ""

        try:
            pct = float(percent_text)
        except ValueError:
            return

        pct_int = max(0, min(100, int(round(pct))))
        self.progress_bar.setValue(pct_int)

        item = self.current_task.get("item") if self.current_task else None
        if item and self.current_task:
            suffix = f" / {video_id}" if video_id else ""
            item.setText(
                f"下載中 {pct:.1f}% / ETA {eta_text}{suffix}：{self.current_task['url']}"
            )

    def on_naming_scheme_changed(self):
        scheme = self.naming_scheme_combo.currentData()
        mapping = {
            "title_only": "%(title)s.%(ext)s",
            "date_title": "%(upload_date)s - %(title)s.%(ext)s",
            "channel_title": "%(uploader)s - %(title)s.%(ext)s",
            "channel_date_title": "%(uploader)s/%(upload_date)s - %(title)s.%(ext)s",
            "playlist_index_title": "%(playlist_index)s - %(title)s.%(ext)s",
        }

        if scheme != "custom":
            self.title_template_input.setText(mapping.get(scheme, "%(title)s.%(ext)s"))
            self.title_template_input.setEnabled(False)
        else:
            self.title_template_input.setEnabled(True)

        self.update_filename_preview()

    def update_filename_preview(self):
        template = self.title_template_input.text().strip()
        if not template:
            self.filename_preview_label.setText("檔名範例：My Video.mp4")
            return

        preview = template
        preview = preview.replace("%(uploader)s", "Channel Name")
        preview = preview.replace("%(upload_date)s", "20260404")
        preview = preview.replace("%(playlist_index)s", "01")
        preview = preview.replace("%(title)s", "My Video")
        preview = preview.replace("%(id)s", "abc123")
        preview = preview.replace("%(ext)s", "mp4")

        note = ""
        if "%(ext)s" not in template:
            preview = f"{preview}.mp4"
            note = "（未放 %(ext)s，預覽先自動補上副檔名）"
        elif not template.rstrip().endswith("%(ext)s"):
            note = "（提醒：%(ext)s 建議放最後，不然會變成像 My Video.mp4-abc123）"

        self.filename_preview_label.setText(f"檔名範例：{preview}{note}")

    def on_download_error(self, _error):
        if self.download_process:
            self.log_output.appendPlainText(
                f"下載程序錯誤：{self.download_process.errorString()}"
            )

    def on_download_finished(self, exit_code, exit_status):
        for raw_buffer in (self.stdout_buffer, self.stderr_buffer):
            if not raw_buffer:
                continue

            remaining = self.decode_process_bytes(raw_buffer).rstrip()
            clean_remaining = self.ansi_escape_re.sub("", remaining).strip()
            if "[GUI]" in clean_remaining:
                self.parse_progress_template_line(clean_remaining)
            elif clean_remaining:
                self.log_output.appendPlainText(clean_remaining)

        self.stdout_buffer = b""
        self.stderr_buffer = b""
        self.process_buffer = ""

        finished_task = self.current_task
        item = finished_task.get("item") if finished_task else None
        was_stopped = self.stop_requested

        success = (
            exit_status == QProcess.NormalExit and exit_code == 0 and not was_stopped
        )

        if success and finished_task:
            self.save_streetvoice_static_lyrics_for_task(finished_task)

        if item and finished_task:
            if success:
                item.setText(f"完成：{finished_task['url']}")
            elif was_stopped:
                item.setText(f"已停止：{finished_task['url']}")
            else:
                item.setText(f"失敗：{finished_task['url']}")

        if finished_task:
            if success:
                self.log_output.appendPlainText(f"下載完成：{finished_task['url']}")
            elif was_stopped:
                self.log_output.appendPlainText(f"下載已停止：{finished_task['url']}")
            else:
                self.log_output.appendPlainText(
                    f"下載失敗：{finished_task['url']} "
                    f"(exit_code={exit_code}, exit_status={exit_status})"
                )

        if self.download_process:
            self.download_process.deleteLater()

        self.download_process = None
        self.current_task = None
        self.stop_requested = False

        self.start_next_download()
    def stop_download(self):
        if not self.download_process:
            return
        self.stop_requested = True
        self.log_output.appendPlainText("已送出停止指令")
        self.download_process.kill()