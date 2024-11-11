import sys
import threading
from pathlib import Path
from queue import Queue
import logging
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QPushButton, QComboBox, 
                            QTextEdit, QLineEdit, QProgressBar, QFileDialog,
                            QMessageBox, QTabWidget, QRadioButton, QButtonGroup,
                            QStackedWidget, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRect
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon, QScreen
import yt_dlp

class Config:
    WINDOW_WIDTH = 1024
    WINDOW_HEIGHT = 768
    MAX_CONCURRENT_DOWNLOADS = 3
    FORMAT_DICT = {
        'Best Quality': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '1080p': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '720p': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '480p': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'Audio Only': 'bestaudio[ext=m4a]'
    }

class StyleSheet:
    DARK_THEME = """
    QMainWindow, QWidget {
        background-color: #1e1e1e;
        color: #ffffff;
        font-size: 14px;
    }
    QTabWidget::pane {
        border: 1px solid #333333;
        background-color: #1e1e1e;
        border-radius: 5px;
    }
    QTabBar::tab {
        background-color: #2d2d2d;
        color: #ffffff;
        padding: 12px 30px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #007acc;
    }
    QTabBar::tab:hover {
        background-color: #404040;
    }
    QTextEdit, QLineEdit {
        background-color: #2d2d2d;
        border: 2px solid #404040;
        padding: 10px;
        color: #ffffff;
        border-radius: 5px;
        font-size: 13px;
    }
    QTextEdit:focus, QLineEdit:focus {
        border: 2px solid #007acc;
    }
    QPushButton {
        background-color: #007acc;
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 5px;
        font-weight: bold;
        min-height: 20px;
    }
    QPushButton:hover {
        background-color: #0098ff;
    }
    QPushButton:pressed {
        background-color: #005c99;
    }
    QComboBox {
        background-color: #2d2d2d;
        border: 2px solid #404040;
        border-radius: 5px;
        padding: 8px;
        color: white;
        min-height: 20px;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox::down-arrow {
        image: url(down_arrow.png);
        width: 12px;
        height: 12px;
    }
    QProgressBar {
        border: 2px solid #404040;
        border-radius: 5px;
        text-align: center;
        min-height: 25px;
        font-weight: bold;
    }
    QProgressBar::chunk {
        background-color: #007acc;
        border-radius: 3px;
    }
    QScrollArea {
        border: none;
        background-color: transparent;
    }
    QFrame#downloadFrame {
        background-color: #2d2d2d;
        border-radius: 8px;
        padding: 15px;
        margin: 5px;
    }
    QLabel {
        color: #ffffff;
        font-size: 14px;
    }
    QLabel#headerLabel {
        font-size: 18px;
        font-weight: bold;
        color: #ffffff;
    }
    """

class DownloaderSignals(QObject):
    progress = pyqtSignal(str, str, str)  # url, percentage, speed
    status = pyqtSignal(str, str)  # url, status message
    error = pyqtSignal(str, str)  # url, error message
    download_complete = pyqtSignal(str)  # url

class DownloadProgressWidget(QWidget):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.setObjectName("downloadFrame")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        url_text = self.url if len(self.url) < 50 else f"{self.url[:47]}..."
        self.url_label = QLabel(f"URL: {url_text}")
        self.url_label.setWordWrap(True)
        layout.addWidget(self.url_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(25)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Initializing...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

class YouTubeDownloader(QObject):
    def __init__(self):
        super().__init__()
        self.active_downloads = 0
        self.completed_downloads = 0
        self.lock = threading.Lock()
        self.download_queue = Queue()
        self.config = Config()
        self.signals = DownloaderSignals()
        
        logging.basicConfig(
            filename='downloader_errors.log',
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def validate_url(self, url: str) -> bool:
        import re
        youtube_regex = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
        return bool(re.match(youtube_regex, url))

    def progress_hook(self, d):
        url = d.get('info_dict', {}).get('webpage_url', 'Unknown URL')
        if d['status'] == 'downloading':
            percentage = d.get('_percent_str', '0%')
            speed = d.get('_speed_str', '0MiB/s')
            self.signals.progress.emit(url, percentage, speed)
        elif d['status'] == 'finished':
            self.signals.status.emit(url, "Processing video...")

    def download_content(self, url: str, quality_choice: str, download_path: str) -> None:
        try:
            if not self.validate_url(url):
                self.signals.error.emit(url, "Invalid YouTube URL")
                return

            with self.lock:
                self.active_downloads += 1

            output_path = Path(download_path)
            output_path.mkdir(parents=True, exist_ok=True)

            video_format = self.config.FORMAT_DICT[quality_choice]

            ydl_opts = {
                'format': video_format,
                'merge_output_format': 'mp4',
                'outtmpl': str(output_path / '%(title)s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True
            }

            self.signals.status.emit(url, "Starting download...")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        video_title = info.get('title', 'Unnamed Video')
                        self.signals.status.emit(url, f"Downloading: {video_title}")
                        ydl.download([url])
                        self.signals.download_complete.emit(url)
                    else:
                        self.signals.error.emit(url, "Could not fetch video information")
                except Exception as e:
                    self.signals.error.emit(url, str(e))

        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            self.logger.error(error_msg)
            self.signals.error.emit(url, error_msg)

        finally:
            with self.lock:
                self.active_downloads -= 1
                self.completed_downloads += 1

    def download_playlist(self, url: str, quality_choice: str, download_path: str) -> None:
        try:
            if not self.validate_url(url):
                self.signals.error.emit(url, "Invalid YouTube URL")
                return

            ydl_opts = {
                'format': self.config.FORMAT_DICT[quality_choice],
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'extract_flat': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    for entry in info['entries']:
                        video_url = entry['url']
                        self.download_content(video_url, quality_choice, download_path)
                else:
                    self.signals.error.emit(url, "No playlist found at the provided URL")

        except Exception as e:
            error_msg = f"Playlist download failed: {str(e)}"
            self.logger.error(error_msg)
            self.signals.error.emit(url, error_msg)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mistilteinn YTDE")
        self.setFixedSize(Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)
        self.downloader = YouTubeDownloader()
        self.download_widgets = {}
        self.setup_ui()
        self.setup_connections()
        self.setStyleSheet(StyleSheet.DARK_THEME)
        self.center_window()

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        window = self.geometry()
        x = (screen.width() - window.width()) // 2
        y = (screen.height() - window.height()) // 2
        self.move(x, y)

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        header_label = QLabel("Mistilteinn YTDE")
        header_label.setObjectName("headerLabel")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)

        tab_widget = QTabWidget()
        tab_widget.setContentsMargins(0, 20, 0, 20)
        
        single_video_tab = self.create_single_video_tab()
        tab_widget.addTab(single_video_tab, "Single Video")
        
        multiple_videos_tab = self.create_multiple_videos_tab()
        tab_widget.addTab(multiple_videos_tab, "Multiple Videos")
        
        playlist_tab = self.create_playlist_tab()
        tab_widget.addTab(playlist_tab, "Playlist")

        main_layout.addWidget(tab_widget)

        downloads_group = QFrame()
        downloads_group.setObjectName("downloadFrame")
        downloads_layout = QVBoxLayout(downloads_group)
        
        downloads_label = QLabel("Active Downloads")
        downloads_label.setObjectName("headerLabel")
        downloads_layout.addWidget(downloads_label)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        scroll_content = QWidget()
        self.downloads_container = QVBoxLayout(scroll_content)
        self.downloads_container.addStretch()
        
        scroll_area.setWidget(scroll_content)
        downloads_layout.addWidget(scroll_area)
        
        main_layout.addWidget(downloads_group)

    def create_single_video_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        url_layout = QVBoxLayout()
        url_label = QLabel("Video URL:")
        self.single_url_input = QLineEdit()
        self.single_url_input.setPlaceholderText("Enter YouTube URL")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.single_url_input)
        layout.addLayout(url_layout)
        
        self.add_common_download_options(layout)
        
        return widget

    def create_multiple_videos_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        urls_label = QLabel("Video URLs:")
        layout.addWidget(urls_label)
        
        self.multiple_urls_input = QTextEdit()
        self.multiple_urls_input.setPlaceholderText("Enter YouTube URLs - one per line")
        self.multiple_urls_input.setMinimumHeight(100)
        layout.addWidget(self.multiple_urls_input)
        
        self.add_common_download_options(layout)
        
        return widget

    def create_playlist_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        url_layout = QVBoxLayout()
        url_label = QLabel("Playlist URL:")
        self.playlist_url_input = QLineEdit()
        self.playlist_url_input.setPlaceholderText("Enter YouTube Playlist URL")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.playlist_url_input)
        layout.addLayout(url_layout)
        
        self.add_common_download_options(layout)
        
        return widget

    def add_common_download_options(self, layout):
        quality_layout = QVBoxLayout()
        quality_label = QLabel("Quality:")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(Config.FORMAT_DICT.keys())
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.quality_combo)
        layout.addLayout(quality_layout)

        path_layout = QVBoxLayout()
        path_label = QLabel("Save Location:")
        path_input_layout = QHBoxLayout()
        
        self.path_input = QLineEdit()
        self.path_input.setText(str(Path.home() / 'Downloads'))
        
        browse_button = QPushButton("Browse")
        browse_button.setMaximumWidth(100)
        browse_button.clicked.connect(self.browse_path)
        
        path_input_layout.addWidget(self.path_input)
        path_input_layout.addWidget(browse_button)
        
        path_layout.addWidget(path_label)
        path_layout.addLayout(path_input_layout)
        layout.addLayout(path_layout)

        download_button = QPushButton("Download")
        download_button.setMinimumHeight(50)
        download_button.clicked.connect(self.start_download)
        layout.addWidget(download_button)

    def setup_connections(self):
        self.downloader.signals.progress.connect(self.update_progress)
        self.downloader.signals.status.connect(self.update_status)
        self.downloader.signals.error.connect(self.show_error)
        self.downloader.signals.download_complete.connect(self.download_finished)

    def browse_path(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Download Directory",
            str(Path.home() / 'Downloads'),
            QFileDialog.Option.ShowDirsOnly
        )
        if path:
            self.path_input.setText(path)

    def add_download_progress(self, url):
        progress_widget = DownloadProgressWidget(url)
        self.download_widgets[url] = progress_widget
        self.downloads_container.insertWidget(self.downloads_container.count() - 1, progress_widget)
        return progress_widget

    def start_download(self):
        download_path = self.path_input.text()
        if not download_path:
            QMessageBox.warning(self, "Error", "Please select a download location")
            return

        quality_choice = self.quality_combo.currentText()
        current_tab = self.centralWidget().findChild(QTabWidget).currentIndex()
        
        if current_tab == 0:  # Single Video
            url = self.single_url_input.text().strip()
            if url:
                self.add_download_progress(url)
                threading.Thread(
                    target=self.downloader.download_content,
                    args=(url, quality_choice, download_path),
                    daemon=True
                ).start()
                self.single_url_input.clear()
            else:
                QMessageBox.warning(self, "Error", "Please enter a URL")

        elif current_tab == 1:  # Multiple Videos
            urls = self.multiple_urls_input.toPlainText().strip().split('\n')
            urls = [url.strip() for url in urls if url.strip()]
            
            if urls:
                for url in urls:
                    self.add_download_progress(url)
                    threading.Thread(
                        target=self.downloader.download_content,
                        args=(url, quality_choice, download_path),
                        daemon=True
                    ).start()
                self.multiple_urls_input.clear()
            else:
                QMessageBox.warning(self, "Error", "Please enter at least one URL")

        elif current_tab == 2:  # Playlist
            url = self.playlist_url_input.text().strip()
            if url:
                self.add_download_progress(url)
                threading.Thread(
                    target=self.downloader.download_playlist,
                    args=(url, quality_choice, download_path),
                    daemon=True
                ).start()
                self.playlist_url_input.clear()
            else:
                QMessageBox.warning(self, "Error", "Please enter a playlist URL")

    def update_progress(self, url, percentage, speed):
        if url in self.download_widgets:
            widget = self.download_widgets[url]
            percentage = percentage.strip('%')
            try:
                widget.progress_bar.setValue(int(float(percentage)))
                widget.status_label.setText(f"Downloading: {percentage}% at {speed}")
            except ValueError:
                pass

    def update_status(self, url, status):
        if url in self.download_widgets:
            widget = self.download_widgets[url]
            widget.status_label.setText(status)

    def show_error(self, url, error_message):
        if url in self.download_widgets:
            widget = self.download_widgets[url]
            widget.status_label.setText(f"Error: {error_message}")
            widget.progress_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #cc0000;
                }
            """)
        QMessageBox.warning(self, "Download Error", f"Error downloading {url}:\n{error_message}")

    def download_finished(self, url):
        if url in self.download_widgets:
            widget = self.download_widgets[url]
            widget.progress_bar.setValue(100)
            widget.status_label.setText("Download completed!")
            widget.progress_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #00cc00;
                }
            """)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
