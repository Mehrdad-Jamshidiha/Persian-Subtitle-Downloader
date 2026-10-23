#!/usr/bin/env python3
"""
Subtitle Downloader & Movie Renamer - Modern PyQt5 UI
- Step 0: Auto-download & configure FFmpeg, FFprobe, and MKVToolNix if needed
- Step 1: Cleanup movie filenames (title + year)
- Step 2: Strict Dub Check: Detect Persian AUDIO streams only (ignoring Persian subtitles)
- Step 3: Database matching (OT -> PT) with resilient JSON loading
- Fallback: Online IMDb ID search (IMDb Suggestion API + DuckDuckGo)
- Subtitle Downloader: Scrapes subkade.ir
- Auto Encoding Fix: Converts Persian Windows-1256 / Mojibake to UTF-8
- Naming: Movie.ParentFolder 1.srt
- Progress Bar: Movie-based progress bar matching the Mux gradient with adjacent Show/Hide Log button
"""

import sys
import os
import re
import json
import time
import zipfile
import shutil
import subprocess
import threading
import requests
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, 
                             QWidget, QFrame, QFileDialog, QCheckBox, 
                             QProgressBar)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette, QPixmap

# ----------------- CONFIG & CONSTANTS ----------------- #

BASE_URL = "https://subkade.ir"
DOWNLOAD_BASE = "https://dl1.subkade.ir"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
SKIP_EXTENSIONS = {'.zip', '.srt', '.sub', '.nfo', '.txt', '.jpg', '.png'}
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

# Handle paths correctly for both normal Python and PyInstaller .exe
if getattr(sys, 'frozen', False):
    EXE_DIR = Path(sys.executable).resolve().parent   # Folder where your .exe lives
    BUNDLE_DIR = Path(sys._MEIPASS)                   # Temporary folder inside the .exe
else:
    EXE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = EXE_DIR

TOOLS_DIR = EXE_DIR / "tools"  # Keep tools folder persistent next to your .exe

# Add standard & local tool directories to PATH
common_tool_paths = [
    TOOLS_DIR,
    Path("C:/Program Files/MKVToolNix"),
    Path("C:/Program Files (x86)/MKVToolNix"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
]
for p in common_tool_paths:
    if p.exists() and str(p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")

# ----------------- DEPENDENCY INSTALLER ----------------- #

def download_file_with_progress(url, dest_path, log_func, label):
    """Downloads a file with live percentage updates to the UI log"""
    try:
        response = requests.get(url, headers=HEADERS, stream=True, timeout=120)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        last_log = time.time()

        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and time.time() - last_log > 1.2:
                        percent = int((downloaded / total_size) * 100)
                        log_func(f"  ↳ Downloading {label}: {percent}%")
                        last_log = time.time()
        return True
    except Exception as e:
        log_func(f"  ✗ Failed downloading {label}: {e}")
        return False

def ensure_dependencies(log_func, need_mux=True):
    """
    Checks if ffmpeg, ffprobe, and mkvmerge are installed.
    If missing, automatically downloads portable versions into tools/.
    """
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if str(TOOLS_DIR) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(TOOLS_DIR) + os.pathsep + os.environ.get("PATH", "")

    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_ffprobe = shutil.which("ffprobe") is not None
    has_mkvmerge = shutil.which("mkvmerge") is not None

    missing = []
    if not has_ffmpeg: missing.append("ffmpeg")
    if not has_ffprobe: missing.append("ffprobe")
    if need_mux and not has_mkvmerge: missing.append("mkvmerge")

    if not missing:
        return True

    log_func("⏳ [One-Time Setup] Required media tools are missing: " + ", ".join(missing))
    log_func("⏳ Please wait while tools are downloaded into local tools/ directory...\n")

    if not has_ffmpeg:
        log_func("📦 Fetching portable FFmpeg...")
        ffmpeg_zip = TOOLS_DIR / "ffmpeg.zip"
        url_ffmpeg = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffmpeg-6.1-win-64.zip"
        if download_file_with_progress(url_ffmpeg, ffmpeg_zip, log_func, "FFmpeg"):
            try:
                with zipfile.ZipFile(ffmpeg_zip, 'r') as zf:
                    for member in zf.namelist():
                        if member.lower().endswith("ffmpeg.exe"):
                            with zf.open(member) as src, open(TOOLS_DIR / "ffmpeg.exe", "wb") as dst:
                                dst.write(src.read())
                ffmpeg_zip.unlink(missing_ok=True)
                log_func("✓ FFmpeg successfully installed.")
            except Exception as e:
                log_func(f"✗ Failed extracting FFmpeg: {e}")

    if not has_ffprobe:
        log_func("📦 Fetching portable FFprobe...")
        ffprobe_zip = TOOLS_DIR / "ffprobe.zip"
        url_ffprobe = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffprobe-6.1-win-64.zip"
        if download_file_with_progress(url_ffprobe, ffprobe_zip, log_func, "FFprobe"):
            try:
                with zipfile.ZipFile(ffprobe_zip, 'r') as zf:
                    for member in zf.namelist():
                        if member.lower().endswith("ffprobe.exe"):
                            with zf.open(member) as src, open(TOOLS_DIR / "ffprobe.exe", "wb") as dst:
                                dst.write(src.read())
                ffprobe_zip.unlink(missing_ok=True)
                log_func("✓ FFprobe successfully installed.")
            except Exception as e:
                log_func(f"✗ Failed extracting FFprobe: {e}")

    if need_mux and not has_mkvmerge:
        log_func("📦 Fetching portable MKVToolNix (mkvmerge)...")
        mkv_zip = TOOLS_DIR / "mkvtoolnix.zip"
        url_mkv = "https://github.com/Jesseatgao/MKVToolNix-static-builds/releases/download/v58.0.0-mingw-w64-win32v1.8el9/mkvtoolnix-x86_64-win.zip"
        if download_file_with_progress(url_mkv, mkv_zip, log_func, "MKVToolNix"):
            try:
                with zipfile.ZipFile(mkv_zip, 'r') as zf:
                    for member in zf.namelist():
                        if member.lower().endswith("mkvmerge.exe"):
                            with zf.open(member) as src, open(TOOLS_DIR / "mkvmerge.exe", "wb") as dst:
                                dst.write(src.read())
                mkv_zip.unlink(missing_ok=True)
                log_func("✓ MKVToolNix successfully installed.")
            except Exception as e:
                log_func(f"✗ Failed extracting MKVToolNix: {e}")

    os.environ["PATH"] = str(TOOLS_DIR) + os.pathsep + os.environ.get("PATH", "")
    return True

# ----------------- STRICT AUDIO DUBBED CHECK ----------------- #

def is_persian_dubbed(file_path: Path) -> bool:
    """
    Checks if the video file has a Persian/Farsi AUDIO stream.
    Strictly filters out subtitles so files with Persian subtitles are NOT mistaken for dubs.
    """
    persian_langs = {"per", "fa", "fas", "pes", "per-ir", "fa-ir"}
    persian_keywords = ["persian", "farsi", "دوبله"]

    if shutil.which("mkvmerge"):
        try:
            res = subprocess.run(
                ["mkvmerge", "-J", str(file_path)],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for track in data.get("tracks", []):
                    if track.get("type") == "audio":
                        props = track.get("properties", {})
                        lang = str(props.get("language", "")).lower()
                        track_name = str(props.get("track_name", "")).lower()
                        if lang in persian_langs or any(kw in track_name for kw in persian_keywords):
                            return True
                return False
        except Exception:
            pass

    if shutil.which("ffprobe"):
        try:
            res = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=codec_type:stream_tags=language,title",
                    "-of", "json",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        tags = stream.get("tags", {})
                        lang = str(tags.get("language", "")).lower()
                        title = str(tags.get("title", "")).lower()
                        if lang in persian_langs or any(kw in title for kw in persian_keywords):
                            return True
                return False
        except Exception:
            pass

    if shutil.which("ffmpeg"):
        try:
            res = subprocess.run(
                ["ffmpeg", "-i", str(file_path)],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            output = res.stderr or ""
            stream_blocks = re.split(r'^\s*Stream #', output, flags=re.MULTILINE)
            for block in stream_blocks[1:]:
                first_line = block.splitlines()[0].lower() if block.splitlines() else ""
                if "audio:" in first_line:
                    block_lower = block.lower()
                    if any(code in block_lower for code in ["(per)", "(fa)", "(fas)", "language: per", "language: fa", "language: fas", "title: persian", "title: farsi"]):
                        return True
        except Exception:
            pass

    return False

# ----------------- STEP 1: CLEANUP FUNCTIONS ----------------- #

def clean_filename(filename):
    """Clean filename: extracts title and 4-digit year, preserves extension"""
    path = Path(filename)
    ext = path.suffix
    stem = path.stem

    cleaned = re.sub(r'[.\(\)]', lambda m: ' ' if m.group() == '.' else '', stem)
    cleaned = re.sub(r' +', ' ', cleaned).strip()

    match = re.search(r'(\D{3,})(\d{4})', cleaned)
    if match:
        title = match.group(1).strip()
        year = match.group(2)
        return f"{title} {year}{ext}"

    cleaned = re.sub(r' +', ' ', cleaned).strip()
    return f"{cleaned}{ext}"

# ----------------- ENCODING REPAIR (PERSIAN / ARABIC) ----------------- #

def fix_subtitle_encoding(raw_bytes: bytes) -> str:
    """
    Detects Windows-1256 (ANSI), UTF-16, or Mojibake and converts to clean UTF-8 text.
    """
    if raw_bytes.startswith(b'\xff\xfe') or raw_bytes.startswith(b'\xfe\xff'):
        try:
            return raw_bytes.decode('utf-16')
        except Exception:
            pass

    text = None
    try:
        text = raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        pass

    if text is None:
        try:
            text = raw_bytes.decode('windows-1256')
        except UnicodeDecodeError:
            pass

    if text is None:
        for enc in ['cp1256', 'iso-8859-6', 'utf-16', 'cp1252', 'latin-1']:
            try:
                text = raw_bytes.decode(enc)
                break
            except Exception:
                continue

    if text is None:
        text = raw_bytes.decode('utf-8', errors='replace')

    has_persian = any('\u0600' <= ch <= '\u06ff' for ch in text)
    if not has_persian and any(c in text for c in ('Ø', 'Ù', 'Û', 'Ú', 'ª')):
        try:
            fixed = text.encode('cp1252').decode('utf-8')
            if any('\u0600' <= ch <= '\u06ff' for ch in fixed):
                text = fixed
        except Exception:
            pass

    return text

# ----------------- ONLINE IMDB SEARCH (FALLBACK) ----------------- #

def search_imdb_online(query):
    """Search for IMDb ID online if local database lookup fails"""
    try:
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', query.strip().lower()).strip('_')
        if slug:
            first_char = slug[0]
            url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{slug}.json"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("d", [])
                for item in items:
                    mid = item.get("id", "")
                    if mid.startswith("tt"):
                        return mid
    except Exception:
        pass

    try:
        search_query = f"{query} imdb"
        ddg_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(search_query)}"
        resp = requests.get(ddg_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            match = re.search(r'imdb\.com/title/(tt\d+)', resp.text)
            if match:
                return match.group(1)
    except Exception:
        pass

    return None

# ----------------- SCRAPING & SUBTITLE FUNCTIONS ----------------- #

def search_movie(imdb_id):
    """Search subkade.ir for movie by IMDb ID"""
    clean_id = imdb_id[2:] if imdb_id.startswith('tt') else imdb_id
    search_url = f"{BASE_URL}/?s=tt{clean_id}"
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception:
        return None

def find_download_page(html, imdb_id):
    """Find the download page link for the movie"""
    download_pattern = r'href=["\']([^"\s]+)["\']'
    links = re.findall(download_pattern, html)
    
    for link in links:
        if '%d8%af%d8%a7%d9%86%d9%84%d9%88%d8%af' in link and imdb_id.lower() in link.lower():
            return link
    for link in links:
        if '%d8%af%d8%a7%d9%86%d9%84%d9%88%d8%af' in link:
            return link
    return None

def navigate_to_download_page(download_url):
    """Navigate to download page and get the HTML content"""
    try:
        response = requests.get(download_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception:
        return None

def find_zip_download(html):
    """Extract zip download URL"""
    zip_pattern = r'wp-content/uploads/[^"\s]+\.zip'
    zip_links = re.findall(zip_pattern, html)
    if zip_links:
        return f"{DOWNLOAD_BASE}/{zip_links[0]}"
    return None

def download_file(url, output_path):
    """Download the zip file to destination path"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception:
        return False

def extract_subtitles_from_zip(zip_path: Path, movie_file: Path):
    """
    Extracts all .srt files, fixes Persian encoding to UTF-8,
    and names them using: Movie.ParentFolder 1.srt
    """
    extracted_items = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            srt_entries = [
                item for item in zf.namelist() 
                if item.lower().endswith('.srt') and not item.startswith('__MACOSX')
            ]
            
            for index, srt_name in enumerate(srt_entries):
                parent_tag = Path(srt_name).parent.name
                if not parent_tag or parent_tag == '.' or parent_tag.lower() == movie_file.stem.lower():
                    parent_tag = "Persian"

                track_title = f"{parent_tag} {index + 1}"
                out_name = f"{movie_file.stem}.{track_title}.srt"
                out_path = movie_file.parent / out_name
                
                with zf.open(srt_name) as source:
                    raw_bytes = source.read()
                
                fixed_content = fix_subtitle_encoding(raw_bytes)
                with open(out_path, 'w', encoding='utf-8') as target:
                    target.write(fixed_content)
                
                extracted_items.append((out_path, track_title))

        if zip_path.exists():
            zip_path.unlink()

    except Exception as e:
        return None, str(e)

    return extracted_items, None

def mux_subtitles_into_video(movie_file: Path, srt_items: list):
    """
    Embeds subtitles directly into an .mkv file using mkvmerge or ffmpeg.
    Uses stream copy (-c copy) for 0% CPU/GPU overhead.
    """
    has_mkvmerge = shutil.which("mkvmerge") is not None
    has_ffmpeg = shutil.which("ffmpeg") is not None

    if not has_mkvmerge and not has_ffmpeg:
        return False, "Neither 'mkvmerge' nor 'ffmpeg' found. Keeping external .srt files."

    temp_output = movie_file.parent / f"{movie_file.stem}_muxed.mkv"
    final_output = movie_file.parent / f"{movie_file.stem}.mkv"

    try:
        if has_mkvmerge:
            cmd = ["mkvmerge", "-o", str(temp_output), str(movie_file)]
            for srt_path, track_title in srt_items:
                cmd.extend([
                    "--track-name", f"0:{track_title}",
                    "--language", "0:per",
                    str(srt_path)
                ])
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
            if res.returncode != 0:
                return False, f"mkvmerge error: {res.stderr.decode('utf-8', errors='ignore')}"

        else:
            cmd = ["ffmpeg", "-y", "-i", str(movie_file)]
            for srt_path, _ in srt_items:
                cmd.extend(["-i", str(srt_path)])

            cmd.extend(["-map", "0"])
            for i, (_, track_title) in enumerate(srt_items):
                cmd.extend(["-map", str(i + 1)])
                cmd.extend([f"-metadata:s:s:{i}", f"title={track_title}"])
                cmd.extend([f"-metadata:s:s:{i}", "language=per"])

            cmd.extend(["-c", "copy", str(temp_output)])
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
            if res.returncode != 0:
                return False, f"ffmpeg error: {res.stderr.decode('utf-8', errors='ignore')}"

        for srt_path, _ in srt_items:
            if srt_path.exists():
                srt_path.unlink()

        if movie_file.suffix.lower() == ".mkv":
            movie_file.unlink()
            temp_output.rename(final_output)
        else:
            movie_file.unlink()
            temp_output.rename(final_output)

        return True, None

    except Exception as e:
        if temp_output.exists():
            temp_output.unlink()
        return False, str(e)

# ----------------- MAIN UI WINDOW ----------------- #

class ModernWindow(QWidget):
    log_signal = pyqtSignal(str)
    set_busy_signal = pyqtSignal(bool)
    progress_signal = pyqtSignal(int, int)

    def log(self, text):
        """Emits signal safely across threads"""
        self.log_signal.emit(text)

    def update_progress(self, current, total):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_bar.setFormat(f"{current}/{total} (%p%)")
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0/0 (0%)")

    def set_busy(self, is_busy):
        if is_busy:
            self.download_btn.setEnabled(False)
            self.download_btn.setText("Processing...")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background: #555555;
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 10px;
                    padding: 8px 20px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 20px;
                }
            """)
        else:
            self.download_btn.setEnabled(True)
            self.download_btn.setText("Download")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d4ff, stop:1 #7b2cbf);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 10px;
                    padding: 8px 20px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b8e6, stop:1 #6a28b8);
                    border: 1px solid rgba(255, 255, 255, 0.25);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0099cc, stop:1 #581c87);
                }
            """)

    def start_drag(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos()
            self.initial_pos = self.frameGeometry().topLeft()
            event.accept()

    def drag_move(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            dx = event.globalPos().x() - self.drag_pos.x()
            dy = event.globalPos().y() - self.drag_pos.y()
            new_x = self.initial_pos.x() + dx
            new_y = self.initial_pos.y() + dy
            self.move(new_x, new_y)
            event.accept()

    def stop_drag(self, event):
        self.drag_pos = None
        self.initial_pos = None

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.path_entry.setText(folder)

    def toggle_log(self):
        self.log_expanded = not self.log_expanded
        if self.log_expanded:
            self.log_container.show()
            self.log_toggle_btn.setText("▲ Hide Log")
        else:
            self.log_container.hide()
            self.log_toggle_btn.setText("▼ Show Log")

    def load_movie_db(self):
        """Loads imdb_movies_minimal.json with fallback for missing commas"""
        if self.ot_map and self.pt_map:
            return True

        # Check inside the bundled .exe first, then next to the .exe
        json_path = BUNDLE_DIR / "imdb_movies_minimal.json"
        if not json_path.exists():
            json_path = EXE_DIR / "imdb_movies_minimal.json"

        if not json_path.exists():
            self.log(f"✗ Warning: 'imdb_movies_minimal.json' not found. Will search online directly.")
            return True

        self.log("📖 Loading movie database...")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            data = []
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                idx = 0
                length = len(content)
                if content.startswith('['):
                    idx = 1
                while idx < length:
                    while idx < length and content[idx] in ' \t\r\n,]':
                        idx += 1
                    if idx >= length:
                        break
                    obj, end = decoder.raw_decode(content, idx)
                    data.append(obj)
                    idx = end

            for item in data:
                movie_id = item.get("ID", "").strip()
                if not movie_id:
                    continue
                if not movie_id.startswith("tt"):
                    movie_id = "tt" + movie_id

                ot = item.get("OT", "").strip().lower()
                pt = item.get("PT", "").strip().lower()

                if ot and ot not in self.ot_map:
                    self.ot_map[ot] = movie_id
                if pt and pt not in self.pt_map:
                    self.pt_map[pt] = movie_id

            self.log(f"✓ Database ready ({len(data)} movies indexed).")
            return True
        except Exception as e:
            self.log(f"✗ Failed loading database ({e}). Will search online as fallback.")
            return True

    def start_process(self, folder_str):
        folder_str = folder_str.strip()
        if not folder_str:
            self.log("✗ Error: Please select or enter a folder path")
            return
        
        folder = Path(folder_str)
        if not folder.exists() or not folder.is_dir():
            self.log(f"✗ Error: Invalid directory: {folder_str}")
            return
        
        should_mux = self.mux_checkbox.isChecked()
        thread = threading.Thread(target=self.run_process, args=(folder, should_mux), daemon=True)
        thread.start()
    
    def run_process(self, folder: Path, should_mux: bool):
        self.set_busy_signal.emit(True)
        try:
            # ----------------- STEP 0: DEPENDENCY SETUP ----------------- #
            ensure_dependencies(self.log, need_mux=should_mux)

            # ----------------- STEP 1: CLEANUP ----------------- #
            self.log(f"\n📂 [Step 1] Scanning & Cleaning: {folder}")
            files = list(folder.iterdir())
            renamed_count = 0

            for file in files:
                if file.is_file() and file.suffix.lower() not in SKIP_EXTENSIONS:
                    old_name = file.name
                    new_name = clean_filename(file.name)
                    
                    if old_name != new_name:
                        target_path = folder / new_name
                        if target_path.exists():
                            self.log(f"⚠ Skipped (target exists): {new_name}")
                            continue
                        try:
                            file.rename(target_path)
                            self.log(f"✓ Renamed: {old_name} → {new_name}")
                            renamed_count += 1
                        except Exception as e:
                            self.log(f"✗ Renaming failed ({old_name}): {e}")

            if renamed_count == 0:
                self.log("✓ Filenames are already clean.")
            else:
                self.log(f"✓ Cleaned {renamed_count} filenames.")

            # ----------------- STEP 2: STRICT DUBBED CHECK & SUBTITLES ----------------- #
            self.log("\n🎬 [Step 2] Checking Persian Audio Dubs & Subtitles...")
            self.load_movie_db()

            current_files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() not in SKIP_EXTENSIONS]
            total_movies = len(current_files)
            processed_count = 0
            self.progress_signal.emit(0, total_movies)

            for file in current_files:
                try:
                    # STRICT: Checks audio streams only, ignoring Persian subtitles
                    if is_persian_dubbed(file):
                        dubbed_dir = folder / "dubbed"
                        dubbed_dir.mkdir(parents=True, exist_ok=True)
                        target_dubbed = dubbed_dir / file.name

                        try:
                            if target_dubbed.exists():
                                self.log(f"🎙 Persian audio dub detected in '{file.name}', but target in 'dubbed/' already exists.")
                            else:
                                shutil.move(str(file), str(target_dubbed))
                                self.log(f"🎙 Persian dub detected: Moved '{file.name}' → 'dubbed/' (Skipping subtitle download)")
                        except Exception as e:
                            self.log(f"✗ Failed moving dubbed file '{file.name}': {e}")
                        
                        continue

                    stem_cleaned = file.stem.strip().lower()

                    # 1. Local Database Lookup (OT first, then PT)
                    imdb_id = self.ot_map.get(stem_cleaned)
                    matched_field = "Database (OT)"

                    if not imdb_id:
                        imdb_id = self.pt_map.get(stem_cleaned)
                        matched_field = "Database (PT)"

                    # 2. Web Search Fallback if not found locally
                    if not imdb_id:
                        self.log(f"🌐 '{file.name}' not in local DB. Searching web...")
                        imdb_id = search_imdb_online(file.stem)
                        if imdb_id:
                            matched_field = "Web Search"
                            self.ot_map[stem_cleaned] = imdb_id

                    if not imdb_id:
                        self.log(f"⚠ No IMDb match found anywhere for: '{file.name}'")
                        continue

                    self.log(f"\n🎯 '{file.name}' → {imdb_id} (via {matched_field})")

                    # Subkade Scraping
                    self.log(f"🔍 Searching Subkade for {imdb_id}...")
                    html = search_movie(imdb_id)
                    if not html:
                        self.log(f"✗ Search failed on subkade.ir for {imdb_id}")
                        continue

                    download_page = find_download_page(html, imdb_id)
                    if not download_page:
                        self.log(f"✗ No download page found for {imdb_id}")
                        continue

                    download_html = navigate_to_download_page(download_page)
                    if not download_html:
                        self.log(f"✗ Failed navigating to download page for {imdb_id}")
                        continue

                    zip_url = find_zip_download(download_html)
                    if not zip_url:
                        self.log(f"✗ No zip link found on download page for {imdb_id}")
                        continue

                    output_zip = folder / f"{file.stem}.zip"
                    self.log(f"⬇ Downloading: {zip_url.split('/')[-1]}...")
                    if download_file(zip_url, output_zip):
                        self.log(f"✓ Downloaded zip archive.")
                        
                        srt_items, err = extract_subtitles_from_zip(output_zip, file)
                        if srt_items:
                            for srt_path, _ in srt_items:
                                self.log(f"  ↳ Extracted & fixed encoding: {srt_path.name}")
                            
                            if should_mux:
                                self.log("  ⚙ Embedding subtitle tracks directly into video (.mkv)...")
                                muxed, mux_err = mux_subtitles_into_video(file, srt_items)
                                if muxed:
                                    self.log(f"  ✓ Attached! Subtitles embedded into single file: {file.stem}.mkv")
                                else:
                                    self.log(f"  ℹ {mux_err}")
                            else:
                                self.log(f"  ✓ Saved as external subtitles alongside the movie (Muxing off).")
                        elif err:
                            self.log(f"  ✗ Failed to extract subtitles: {err}")
                    else:
                        self.log(f"✗ Failed to download zip for {imdb_id}")

                    time.sleep(1)

                finally:
                    processed_count += 1
                    self.progress_signal.emit(processed_count, total_movies)

            self.log("\n🎉 All operations completed!")

        except Exception as e:
            self.log(f"✗ Unexpected error: {str(e)}")
        finally:
            self.set_busy_signal.emit(False)

    def __init__(self):
        super().__init__()

        self.ot_map = {}
        self.pt_map = {}
        self.log_expanded = False  # Hidden by default
        
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(30, 30, 30, 225))
        palette.setColor(QPalette.Text, QColor("white"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        
        font = QFont("Segoe UI", 10)
        self.setFont(font)
        
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)
        
        # 1. Title / Drag Frame
        close_frame = QFrame()
        close_frame.setObjectName("closeFrame")
        close_frame.setStyleSheet("""
            QFrame#closeFrame {
                background: rgba(37, 37, 37, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 22px;
                padding: 0px;
            }
        """)
        close_height = 45
        close_layout = QHBoxLayout(close_frame)
        close_layout.setContentsMargins(15, 0, 8, 0)

                # --- ICON ---
        icon_label = QLabel()
        icon_path = BUNDLE_DIR / "icon.ico"
        if not icon_path.exists():
            icon_path = EXE_DIR / "icon.ico" # Looks for icon.png in script folder
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path)).scaled(25, 25, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)    
        else:
            icon_label.setText("🎬")  # Fallback emoji if file is missing
            icon_label.setStyleSheet("font-size: 15px;")
            

        icon_label.setStyleSheet("background: transparent;")
        close_layout.addWidget(icon_label, 0, Qt.AlignLeft)
        title_label = QLabel("Subtitle Downloader")
        title_label.setStyleSheet("color: white; font-weight: bold; font-size: 15px; background: transparent;")
        close_layout.addWidget(title_label, 0, Qt.AlignLeft)

        
        close_layout.addStretch(1)
        
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff6b6b,stop:1 #ee5a5a);
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 13px;
                font-weight: bold;
                min-height: 28px;
                min-width: 28px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff5a5a,stop:1 #ee4a4a);
            }
        """)
        close_btn.clicked.connect(self.close)
        close_layout.addWidget(close_btn, 0, Qt.AlignRight)
        close_frame.setFixedHeight(close_height)
        layout.addWidget(close_frame)
        
        close_frame.mousePressEvent = lambda e: self.start_drag(e)
        close_frame.mouseMoveEvent = lambda e: self.drag_move(e)
        close_frame.mouseReleaseEvent = lambda e: self.stop_drag(e)
        
        # 2. Main Unified Control Panel
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_frame.setStyleSheet("""
            QFrame#inputFrame {
                background: rgba(37, 37, 37, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
        """)
        
        frame_layout = QVBoxLayout(input_frame)
        frame_layout.setContentsMargins(16, 12, 16, 12)
        frame_layout.setSpacing(10)
        
        # Row 1: Folder Path, Text Input, Browse, Download
        row_inputs = QHBoxLayout()
        row_inputs.setSpacing(8)
        
        label = QLabel("Folder Path:")
        label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                color: white;
                font-size: 13px;
                font-weight: 600;
            }
        """)
        row_inputs.addWidget(label)
        
        self.path_entry = QLineEdit()
        self.path_entry.setPlaceholderText("Select folder path...")
        self.path_entry.setStyleSheet("""
            QLineEdit {
                background: rgba(26, 26, 26, 0.85);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
            }
        """)
        row_inputs.addWidget(self.path_entry, 1)
        
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background: rgba(75, 85, 99, 0.85);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 10px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background: rgba(107, 114, 128, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
            QPushButton:pressed {
                background: rgba(55, 65, 81, 0.95);
            }
        """)
        self.browse_btn.clicked.connect(self.browse_folder)
        row_inputs.addWidget(self.browse_btn)
        
        self.download_btn = QPushButton("Download")
        self.download_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d4ff, stop:1 #7b2cbf);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 10px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b8e6, stop:1 #6a28b8);
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0099cc, stop:1 #581c87);
            }
        """)
        self.download_btn.clicked.connect(lambda: self.start_process(self.path_entry.text()))
        row_inputs.addWidget(self.download_btn)
        frame_layout.addLayout(row_inputs)
        
        # Row 2: Mux Toggle Checkbox + Recommended Hint
        row_options = QHBoxLayout()
        row_options.setSpacing(10)
        
        self.mux_checkbox = QCheckBox("Mux")
        self.mux_checkbox.setChecked(True)
        self.mux_checkbox.setToolTip(
            "Muxing embeds all subtitles directly into the video file,\n"
            "But it takes more time depending on your SSD/HDD speed."
        )
        self.mux_checkbox.setStyleSheet("""
            QCheckBox {
                color: white;
                font-size: 12px;
                font-weight: 600;
                spacing: 7px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 0.2);
                background: rgba(26, 26, 26, 0.8);
            }
            QCheckBox::indicator:hover {
                border: 1px solid #00d4ff;
            }
            QCheckBox::indicator:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d4ff, stop:1 #7b2cbf);
                border: none;
            }
        """)
        row_options.addWidget(self.mux_checkbox)

        hint_label = QLabel("Recommended | Takes Longer But It's Cleaner.")
        hint_label.setStyleSheet("color: Grey; font-size: 11px; background: transparent;")
        row_options.addWidget(hint_label)
        row_options.addStretch(1)
        frame_layout.addLayout(row_options)

        # Row 3: Progress Bar + Adjacent Show/Hide Log Button
        row_progress = QHBoxLayout()
        row_progress.setSpacing(10)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/0 (0%)")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(26, 26, 26, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 7px;
                text-align: center;
                color: white;
                font-size: 11px;
                font-weight: bold;
                min-height: 22px;
                max-height: 22px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d4ff, stop:1 #7b2cbf);
                border-radius: 6px;
            }
        """)
        row_progress.addWidget(self.progress_bar, 1)

        self.log_toggle_btn = QPushButton("▼ Show Log")
        self.log_toggle_btn.setFixedSize(92, 24)
        self.log_toggle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.25);
                color: #5dade2;
                border: 1px solid rgba(52, 152, 219, 0.45);
                border-radius: 7px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(52, 152, 219, 0.5);
                color: white;
            }
        """)
        self.log_toggle_btn.clicked.connect(self.toggle_log)
        row_progress.addWidget(self.log_toggle_btn, 0)

        frame_layout.addLayout(row_progress)
        layout.addWidget(input_frame)
        
        # 3. Log Console Container (Hidden by default)
        self.log_container = QWidget()
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(140)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: rgba(37, 37, 37, 0.75);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 12px;
                font-family: Consolas;
                font-size: 12px;
            }
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(self.log_container)
        self.log_container.hide()
        
        # Signals
        self.log_signal.connect(self.log_text.append)
        self.set_busy_signal.connect(self.set_busy)
        self.progress_signal.connect(self.update_progress)
        
        # 4. Absorb space at bottom
        layout.addStretch(1)
        
        # 5. Window setup
        self.setMinimumSize(640, 420)
        self.setMaximumSize(640, 420)
        self.resize(640, 420)
        
        self.setLayout(layout)
        self.setWindowTitle("Subtitle Downloader")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.95)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernWindow()
    window.show()
    sys.exit(app.exec_())