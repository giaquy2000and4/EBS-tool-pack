import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import random
import re
import subprocess
import sys
import threading
import time
import json
from typing import Optional, List, Dict, Any, Callable


os.environ.pop("SSLKEYLOGFILE", None)

try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

# Check for yt-dlp availability
YTDLP_AVAILABLE = False
try:
    import yt_dlp

    YTDLP_AVAILABLE = True
except ImportError:
    pass


# ====== Helper Functions ======
def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/v\/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def download_subtitle_content(url):
    """Download subtitle content from URL"""
    try:
        import urllib.request
        with urllib.request.urlopen(url) as resp:
            raw = resp.read().decode('utf-8')
            s = raw.strip()
            if s.startswith('{') or s.startswith('['):
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict) and "events" in data:
                        lines = []
                        for ev in data["events"]:
                            if "segs" in ev:
                                line = ''.join(seg.get("utf8", "") for seg in ev["segs"]).strip()
                                if line:
                                    lines.append(line)
                        return "\n".join(lines)
                    if isinstance(data, list):
                        lines = [it.get("text", "") for it in data if it.get("text", "")]
                        return "\n".join(lines)
                    return raw
                except Exception:
                    return raw
            return raw
    except Exception:
        return ""


def clean_subtitles(subtitle_content):
    """Clean subtitle content"""
    if not subtitle_content:
        return "No subtitle content available"
    out = []
    for line in subtitle_content.splitlines():
        line = line.strip()
        if (not re.match(r'^\d+$', line)
                and not re.match(r'^\d{2}:\d{2}:\d{2}', line)
                and not re.match(r'^(WEBVTT|NOTE)', line)
                and line and line != '--'):
            line = re.sub(r'<[^>]+>', '', line)
            line = re.sub(r'&[a-zA-Z]+;', '', line)
            if line and (not out or out[-1] != line):
                out.append(line)
    return "\n".join(out) or "Unable to extract subtitle content"



def get_subtitles(info: Dict[str, Any], lang_code: str):
    """Get subtitles for a specific language from video info"""
    try:
        subs = info.get('subtitles', {}) or {}
        auto = info.get('automatic_captions', {}) or {}

        # Prioritize manual subtitles for the specified language
        if lang_code in subs:
            url = subs[lang_code][0]['url']
            text = download_subtitle_content(url)
            if text:
                return clean_subtitles(text)

        # Then try automatic captions for the specified language
        # Include common variants for English, otherwise use exact code
        lang_codes_to_try = [lang_code]
        if lang_code.lower() == 'en':
            lang_codes_to_try = ['en', 'en-US', 'en-GB']
        # Add other common variants if needed, e.g., for Portuguese: ['pt', 'pt-BR', 'pt-PT']

        for lc in lang_codes_to_try:
            if lc in auto:
                url = auto[lc][0]['url']
                text = download_subtitle_content(url)
                if text:
                    return clean_subtitles(text)

        return f"No {lang_code} subtitles available"
    except Exception as e:
        return f"Error downloading subtitles for {lang_code}: {e}"


# MODIFIED: get_video_info to accept selected_lang and cookie_file_path
def get_video_info(url: str, log_func: Callable[[str, Optional[str]], None],
                   selected_lang: str = 'en', cookie_file_path: Optional[str] = None):
    """Get video information and subtitles"""
    if not YTDLP_AVAILABLE:
        return {'url': url, 'status': 'error', 'error': 'yt-dlp is not available.'}
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractaudio': False,
            'extract_flat': False,
            # Removed sleep_interval and max_sleep_interval here as they are now handled by the GUI logic
            'retries': 5,
            # Ensure yt-dlp extracts subtitle metadata, even if we download content ourselves
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': [selected_lang],  # Hint yt-dlp to look for this language
        }
        if cookie_file_path and os.path.exists(cookie_file_path):
            ydl_opts['cookiefile'] = cookie_file_path
            log_func(f"Using cookie file: {os.path.basename(cookie_file_path)}", "blue")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'No title'),
                'video_id': info.get('id', 'unknown'),
                'url': url,
                'subtitles': get_subtitles(info, selected_lang),  # Call the modified function
                'status': 'success'
            }
    except Exception as e:
        log_func(f"Error getting info for {url}: {e}", "red")
        return {'url': url, 'status': 'error', 'error': f'Error: {e}'}


def load_existing_index(results_path='youtube_results.json'):
    """Load existing results from JSON file"""
    if not os.path.exists(results_path):
        return {}, []
    try:
        with open(results_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        idx, ordered = {}, []
        for item in data:
            vid = item.get('video_id') or extract_video_id(item.get('url', '')) or ''
            if vid and vid not in idx:
                idx[vid] = item
                ordered.append(item)
        return idx, ordered
    except Exception:
        return {}, []


def save_results_merge(new_results: List[Dict[str, Any]], log_func: Callable[[str, Optional[str]], None],
                       output_file='youtube_results.json'):
    """Save results to JSON file"""
    existing_index, ordered = load_existing_index(output_file)
    appended = 0
    for item in new_results:
        vid = item.get('video_id') or extract_video_id(item.get('url', '')) or item.get('url')
        if not vid:
            if item not in ordered:
                ordered.append(item)
                appended += 1
            continue
        if vid in existing_index:
            continue
        existing_index[vid] = item
        ordered.append(item)
        appended += 1
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
    log_func(f"✓ Merged results (added {appended}) into youtube_results.json", "green")


def read_urls_from_file(file_path: str, log_func: Callable[[str, Optional[str]], None]) -> Optional[List[str]]:
    """Read URLs from text file"""
    urls = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for ln, line in enumerate(f, 1):
                s = line.strip()
                if s and not s.startswith('#'):
                    if extract_video_id(s):
                        urls.append(s)
                    else:
                        log_func(f"Line {ln}: Invalid URL - {s}", "yellow")
    except Exception as e:
        log_func(f"Error reading file: {e}", "red")
        return None
    return urls


def sanitize_filename(title: str) -> str:
    """Sanitizes a string to be used as a filename."""
    # Remove characters that are illegal in Windows/Unix filenames
    # This pattern covers: \ / : * ? " < > |
    cleaned_title = re.sub(r'[\\/:*?"<>|]', '', title)
    # Replace multiple spaces with a single underscore, and leading/trailing spaces
    cleaned_title = re.sub(r'\s+', '_', cleaned_title).strip('_')
    # Limit length to avoid extremely long filenames, common limit is 255 but 100-150 is safer
    if len(cleaned_title) > 100:
        cleaned_title = cleaned_title[:100]
    return cleaned_title


# ====== GUI Class ======
class EBSToolPackGUI:
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("EBS-Tool-Pack")
        self.root.geometry("900x750")
        self.root.minsize(850, 650)

        # Colors (YouTube Red theme)
        self.colors = {
            'bg': '#0a0e14',
            'card': '#151b24',
            'accent': '#FF0000',
            'accent_hover': '#CC0000',
            'text': '#ffffff',
            'text_dim': '#7a8896',
            'success': '#00ff9f',
            'warning': '#ffa500',
            'error': '#ff4757',
        }
        self.root.configure(fg_color=self.colors['bg'])

        # State variables
        self.urls_to_process: List[str] = []
        self.pipeline_running = False
        self.stop_pipeline_flag = False
        self.use_title_for_subtitle_filename = ctk.BooleanVar(value=False)  # New state variable

        # NEW: Rate Limit State Variables
        self.rate_limit_enabled = ctk.BooleanVar(value=True)  # Default: Rate limit is ON
        self.min_wait_entry: Optional[ctk.CTkEntry] = None
        self.max_wait_entry: Optional[ctk.CTkEntry] = None

        # Main container
        self.main_container = ctk.CTkFrame(self.root, fg_color=self.colors['bg'])
        self.main_container.pack(fill="both", expand=True, padx=20, pady=20)

        self._setup_ui()

    def _setup_ui(self):
        self.clear_screen()

        # Header
        header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            header_frame,
            text="EBS Pipeline (YouTube Sub)",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=self.colors['accent']
        ).pack(pady=5)
        ctk.CTkLabel(
            header_frame,
            text="Extract YouTube subtitles",
            font=ctk.CTkFont(size=12),
            text_color=self.colors['text_dim']
        ).pack(pady=(0, 15))

        # Main content area
        content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        content_frame.pack(fill="both", expand=True)
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)

        # Left Panel: Inputs
        input_panel = ctk.CTkScrollableFrame(content_frame, fg_color=self.colors['card'], corner_radius=10)
        input_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)

        # NEW SECTION: Rate Limit Configuration (Moved to top)
        self._add_input_section(input_panel, "Rate Limit Configuration")

        rate_limit_frame = ctk.CTkFrame(input_panel, fg_color="transparent")
        rate_limit_frame.pack(fill="x", padx=15, pady=(5, 10))

        self.rate_limit_checkbox = ctk.CTkCheckBox(
            rate_limit_frame,
            text="Enable Rate Limit (delay between video processing)",
            variable=self.rate_limit_enabled,
            command=self._toggle_rate_limit_inputs,
            text_color=self.colors['text'],
            hover_color=self.colors['accent_hover'],
            fg_color=self.colors['accent']
        )
        self.rate_limit_checkbox.pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(rate_limit_frame, text="Min wait time (seconds):", text_color=self.colors['text']).pack(
            anchor="w", pady=(0, 0))
        self.min_wait_entry = ctk.CTkEntry(
            rate_limit_frame,
            placeholder_text="20",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.min_wait_entry.insert(0, "20") # Default min wait time
        self.min_wait_entry.pack(fill="x", pady=(0, 5))

        ctk.CTkLabel(rate_limit_frame, text="Max wait time (seconds):", text_color=self.colors['text']).pack(
            anchor="w", pady=(0, 0))
        self.max_wait_entry = ctk.CTkEntry(
            rate_limit_frame,
            placeholder_text="25",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.max_wait_entry.insert(0, "25") # Default max wait time
        self.max_wait_entry.pack(fill="x", pady=(0, 10))
        self._toggle_rate_limit_inputs() # Set initial state based on checkbox

        # URL Input Section
        self._add_input_section(input_panel, "YouTube URLs")

        ctk.CTkLabel(input_panel, text="Single YouTube URL:", text_color=self.colors['text']).pack(
            anchor="w", padx=15, pady=(10, 0))
        url_input_frame = ctk.CTkFrame(input_panel, fg_color="transparent")
        url_input_frame.pack(fill="x", padx=15, pady=5)
        self.single_url_entry = ctk.CTkEntry(
            url_input_frame,
            placeholder_text="Enter YouTube URL",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.single_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.add_url_button = ctk.CTkButton(
            url_input_frame,
            text="Add URL",
            command=self._add_single_url,
            fg_color=self.colors['accent'],
            hover_color=self.colors['accent_hover'],
            width=80
        )
        self.add_url_button.pack(side="left")

        ctk.CTkLabel(input_panel, text="Or upload .txt file with multiple URLs (one per line):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        self.browse_url_file_button = ctk.CTkButton(
            input_panel,
            text="Browse .txt file",
            command=self._browse_urls_file,
            fg_color=self.colors['card'],
            border_width=1,
            border_color=self.colors['accent'],
            hover_color=self.colors['accent_hover'],
            width=200
        )
        self.browse_url_file_button.pack(anchor="w", padx=15, pady=5)

        ctk.CTkLabel(input_panel, text="URLs to process:", text_color=self.colors['text']).pack(
            anchor="w", padx=15, pady=(10, 0))
        self.url_list_textbox = ctk.CTkTextbox(
            input_panel,
            height=100,
            fg_color=self.colors['bg'],
            text_color=self.colors['text_dim'],
            wrap="word",
            state="disabled"
        )
        self.url_list_textbox.pack(fill="x", padx=15, pady=(0, 10))

        url_list_buttons_frame = ctk.CTkFrame(input_panel, fg_color="transparent")
        url_list_buttons_frame.pack(fill="x", padx=15, pady=(0, 10))
        self.clear_urls_button = ctk.CTkButton(
            url_list_buttons_frame,
            text="Clear URLs",
            command=self._clear_urls,
            fg_color=self.colors['error'],
            hover_color="#cc3a47",
            width=80
        )
        self.clear_urls_button.pack(side="left", padx=(0, 5))

        self.url_count_label = ctk.CTkLabel(
            url_list_buttons_frame,
            text="Total URLs: 0",
            text_color=self.colors['text_dim']
        )
        self.url_count_label.pack(side="right")

        # Numbering Section
        self._add_input_section(input_panel, "Numbering Configuration")

        ctk.CTkLabel(input_panel, text="Start number:", text_color=self.colors['text']).pack(
            anchor="w", padx=15, pady=(10, 0))
        self.start_num_entry = ctk.CTkEntry(
            input_panel,
            placeholder_text="1",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.start_num_entry.insert(0, "1")
        self.start_num_entry.pack(fill="x", padx=15, pady=(0, 10))
        self.start_num_entry.bind("<KeyRelease>", self._update_end_num_label)

        ctk.CTkLabel(input_panel, text="Padding width (e.g., 3 for 001):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        self.pad_width_entry = ctk.CTkEntry(
            input_panel,
            placeholder_text="Auto-calculated",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.pad_width_entry.pack(fill="x", padx=15, pady=(0, 10))
        self.pad_width_entry.bind("<KeyRelease>", self._update_end_num_label)

        self.end_num_label = ctk.CTkLabel(
            input_panel,
            text="End number: (auto-calculated)",
            text_color=self.colors['text_dim'],
            font=ctk.CTkFont(size=11)
        )
        self.end_num_label.pack(anchor="w", padx=15, pady=(0, 10))

        # Output Directory and File Naming
        self._add_input_section(input_panel, "Output Configuration")

        ctk.CTkLabel(input_panel, text="Output root folder (leave empty for auto-create):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        dir_input_frame = ctk.CTkFrame(input_panel, fg_color="transparent")
        dir_input_frame.pack(fill="x", padx=15, pady=5)
        self.dest_dir_entry = ctk.CTkEntry(
            dir_input_frame,
            placeholder_text="Auto: ./Downloaded-Sub",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.dest_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.browse_dest_dir_button = ctk.CTkButton(
            dir_input_frame,
            text="Browse",
            command=self._browse_destination_directory,
            fg_color=self.colors['card'],
            border_width=1,
            border_color=self.colors['accent'],
            hover_color=self.colors['accent_hover'],
            width=80
        )
        self.browse_dest_dir_button.pack(side="left")

        ctk.CTkLabel(input_panel, text="Folder Prefix (e.g., 'Ebs-'):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        self.folder_prefix_entry = ctk.CTkEntry(
            input_panel,
            placeholder_text="Ebs-",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.folder_prefix_entry.insert(0, "Ebs-")
        self.folder_prefix_entry.pack(fill="x", padx=15, pady=(0, 10))

        # Subtitle File Prefix with Checkbox
        subtitle_file_prefix_frame = ctk.CTkFrame(input_panel, fg_color="transparent")
        subtitle_file_prefix_frame.pack(fill="x", padx=15, pady=(10, 0))

        ctk.CTkLabel(subtitle_file_prefix_frame, text="Subtitle File Prefix (e.g., 'bcl-'):",
                     text_color=self.colors['text']).pack(side="left", anchor="w")
        self.use_title_checkbox = ctk.CTkCheckBox(
            subtitle_file_prefix_frame,
            text="Use Video Title",
            variable=self.use_title_for_subtitle_filename,
            command=self._toggle_subtitle_filename_source,
            text_color=self.colors['text_dim'],
            hover_color=self.colors['accent_hover'],
            fg_color=self.colors['accent']
        )
        self.use_title_checkbox.pack(side="right", anchor="e", padx=(10, 0))

        self.subtitle_file_prefix_entry = ctk.CTkEntry(
            input_panel,
            placeholder_text="bcl-",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.subtitle_file_prefix_entry.insert(0, "bcl-")
        self.subtitle_file_prefix_entry.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(input_panel, text="Content File Prefix (e.g., 'Content-', no extension):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        self.content_file_prefix_entry = ctk.CTkEntry(
            input_panel,
            placeholder_text="Content-",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.content_file_prefix_entry.insert(0, "Content-")
        self.content_file_prefix_entry.pack(fill="x", padx=15, pady=(0, 10))

        # NEW: Subtitle Language and Cookie Options
        self._add_input_section(input_panel, "Extraction Options")

        ctk.CTkLabel(input_panel, text="Subtitle Language (e.g., 'en', 'vi', 'ko'):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        self.subtitle_lang_entry = ctk.CTkEntry(
            input_panel,
            placeholder_text="en",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.subtitle_lang_entry.insert(0, "en")  # Default to English
        self.subtitle_lang_entry.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(input_panel, text="Cookie File (.txt, optional, for age-restricted/private videos):",
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))
        cookie_file_frame = ctk.CTkFrame(input_panel, fg_color="transparent")
        cookie_file_frame.pack(fill="x", padx=15, pady=5)
        self.cookie_file_entry = ctk.CTkEntry(
            cookie_file_frame,
            placeholder_text="Path to www.youtube.com_cookies.txt",
            fg_color=self.colors['bg'],
            border_color=self.colors['accent']
        )
        self.cookie_file_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.browse_cookie_file_button = ctk.CTkButton(
            cookie_file_frame,
            text="Browse",
            command=self._browse_cookie_file,
            fg_color=self.colors['card'],
            border_width=1,
            border_color=self.colors['accent'],
            hover_color=self.colors['accent_hover'],
            width=80
        )
        self.browse_cookie_file_button.pack(side="left")

        # Start Button
        self.start_button = ctk.CTkButton(
            input_panel,
            text="Start Extraction",
            command=self._start_pipeline_thread,
            height=40,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=self.colors['accent'],
            hover_color=self.colors['accent_hover']
        )
        self.start_button.pack(fill="x", padx=15, pady=20)

        # Right Panel: Log and Progress
        log_panel = ctk.CTkFrame(content_frame, fg_color=self.colors['card'], corner_radius=10)
        log_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=0)
        log_panel.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(log_panel, text="Progress", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=self.colors['text']).pack(pady=(15, 10))

        self.current_task_label = ctk.CTkLabel(
            log_panel,
            text="Ready.",
            text_color=self.colors['text_dim'],
            font=ctk.CTkFont(size=12)
        )
        self.current_task_label.pack(anchor="w", padx=15, pady=(0, 5))

        self.pipeline_progress_bar = ctk.CTkProgressBar(log_panel, height=20, progress_color=self.colors['accent'])
        self.pipeline_progress_bar.pack(fill="x", padx=15, pady=(0, 10))
        self.pipeline_progress_bar.set(0)

        ctk.CTkLabel(log_panel, text="Detailed Log:", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=self.colors['text']).pack(anchor="w", padx=15, pady=(10, 0))

        self.log_textbox = ctk.CTkTextbox(
            log_panel,
            fg_color=self.colors['bg'],
            text_color=self.colors['text_dim'],
            wrap="word",
            state="disabled",
            height=300
        )
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # Cancel button
        self.cancel_button = ctk.CTkButton(
            log_panel,
            text="Cancel",
            command=self._cancel_pipeline,
            fg_color=self.colors['error'],
            hover_color="#cc3a47",
            state="disabled"
        )
        self.cancel_button.pack(fill="x", padx=15, pady=(0, 15))

        self._update_url_list_display()
        self._update_end_num_label()
        self._toggle_subtitle_filename_source()  # Set initial state of subtitle_file_prefix_entry

    def _add_input_section(self, parent: ctk.CTkFrame, title: str):
        """Helper to create a visually separated input section"""
        section_frame = ctk.CTkFrame(parent, fg_color="transparent")
        section_frame.pack(fill="x", pady=(10, 5))
        ctk.CTkLabel(
            section_frame,
            text=title.upper(),
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.colors['text']
        ).pack(anchor="w", padx=10, pady=(0, 5))
        ctk.CTkFrame(section_frame, height=2, fg_color=self.colors['accent']).pack(fill="x", padx=10)

    def clear_screen(self):
        """Clears all widgets in the main container"""
        for widget in self.main_container.winfo_children():
            widget.destroy()

    def gui_log_output(self, message: str, color_tag: Optional[str] = None):
        """Thread-safe logging to the GUI textbox"""
        self.root.after(0, lambda: self._append_log(message, color_tag))

    def _append_log(self, message: str, color: Optional[str] = None):
        """Appends a message to the log textbox"""
        self.log_textbox.configure(state="normal")
        if color == "red":
            self.log_textbox.insert("end", f"{message}\n", "red_tag")
            self.log_textbox.tag_config("red_tag", foreground=self.colors['error'])
        elif color == "yellow":
            self.log_textbox.insert("end", f"{message}\n", "yellow_tag")
            self.log_textbox.tag_config("yellow_tag", foreground=self.colors['warning'])
        elif color == "green":
            self.log_textbox.insert("end", f"{message}\n", "green_tag")
            self.log_textbox.tag_config("green_tag", foreground=self.colors['success'])
        elif color == "blue":
            self.log_textbox.insert("end", f"{message}\n", "blue_tag")
            self.log_textbox.tag_config("blue_tag", foreground=self.colors['accent'])
        else:
            self.log_textbox.insert("end", f"{message}\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _update_url_list_display(self):
        """Updates the URL list textbox and count label"""
        self.url_list_textbox.configure(state="normal")
        self.url_list_textbox.delete("1.0", "end")
        for url in self.urls_to_process:
            self.url_list_textbox.insert("end", f"{url}\n")
        self.url_list_textbox.configure(state="disabled")
        self.url_count_label.configure(text=f"Total URLs: {len(self.urls_to_process)}")
        self._update_end_num_label()

    def _add_single_url(self):
        url = self.single_url_entry.get().strip()
        if url:
            if extract_video_id(url):
                if url not in self.urls_to_process:
                    self.urls_to_process.append(url)
                    self.single_url_entry.delete(0, "end")
                    self.gui_log_output(f"Added URL: {url}", "blue")
                    self._update_url_list_display()
                else:
                    messagebox.showinfo("Duplicate URL", "This URL is already in the list.")
            else:
                messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
        else:
            messagebox.showwarning("Empty URL", "Please enter a URL before clicking 'Add URL'.")

    def _browse_urls_file(self):
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Select .txt file with YouTube URLs",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=os.path.expanduser("~")
        )
        if file_path:
            urls = read_urls_from_file(file_path, self.gui_log_output)
            if urls:
                new_urls_added = 0
                for url in urls:
                    if url not in self.urls_to_process:
                        self.urls_to_process.append(url)
                        new_urls_added += 1
                self.gui_log_output(
                    f"Loaded {len(urls)} URLs from '{os.path.basename(file_path)}'. Added {new_urls_added} new URLs.",
                    "green")
                self.root.after(0, self._update_url_list_display)
            else:
                messagebox.showwarning("No valid URLs",
                                       f"No valid YouTube URLs found in '{os.path.basename(file_path)}'.")

    def _clear_urls(self):
        if messagebox.askyesno("Clear URLs", "Are you sure you want to clear all URLs from the list?"):
            self.urls_to_process = []
            self.gui_log_output("All URLs cleared.", "yellow")
            self._update_url_list_display()

    def _browse_destination_directory(self):
        directory = filedialog.askdirectory(
            parent=self.root,
            title="Select output directory",
            mustexist=True,
            initialdir=os.path.expanduser("~")
        )
        if directory:
            self.dest_dir_entry.delete(0, "end")
            self.dest_dir_entry.insert(0, directory)

    # NEW: Browse cookie file method
    def _browse_cookie_file(self):
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Select YouTube cookie file (.txt)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=os.path.expanduser("~")
        )
        if file_path:
            self.cookie_file_entry.delete(0, "end")
            self.cookie_file_entry.insert(0, file_path)
            self.gui_log_output(f"Cookie file selected: {os.path.basename(file_path)}", "blue")

    def _toggle_subtitle_filename_source(self):
        """Enables/disables subtitle file prefix entry based on checkbox state."""
        if self.use_title_for_subtitle_filename.get():
            self.subtitle_file_prefix_entry.configure(state="disabled")
            # Clear the entry text when using video title
            self.subtitle_file_prefix_entry.delete(0, ctk.END)
            self.gui_log_output("Subtitle filename will use video title. Prefix entry disabled.", "blue")
        else:
            self.subtitle_file_prefix_entry.configure(state="normal")
            # Re-insert default prefix if entry is empty
            if not self.subtitle_file_prefix_entry.get().strip():
                self.subtitle_file_prefix_entry.insert(0, "bcl-")
            self.gui_log_output("Subtitle filename will use custom prefix. Prefix entry enabled.", "blue")

    # NEW: Toggle Rate Limit Input Fields
    def _toggle_rate_limit_inputs(self):
        state = "normal" if self.rate_limit_enabled.get() else "disabled"
        if self.min_wait_entry:
            self.min_wait_entry.configure(state=state)
        if self.max_wait_entry:
            self.max_wait_entry.configure(state=state)

    def _update_end_num_label(self, event=None):
        try:
            start_num = int(self.start_num_entry.get() or "1")
            num_urls = len(self.urls_to_process)
            end_num = start_num + num_urls - 1
            if num_urls == 0:
                self.end_num_label.configure(text="End number: (0 URLs selected)")
            else:
                raw_pad_width = self.pad_width_entry.get().strip()
                try:
                    pad_width = int(raw_pad_width) if raw_pad_width else 0
                except ValueError:
                    pad_width = 0

                if pad_width <= 0:
                    # Auto-calculate pad_width if not specified or invalid
                    # It should be at least 1, and enough to fit the largest number
                    pad_width = max(1, len(str(max(start_num, end_num))))

                formatted_end = f"{end_num:0{pad_width}d}"
                self.end_num_label.configure(text=f"End number: {formatted_end}")
        except ValueError:
            self.end_num_label.configure(text="End number: Invalid start number")
        except Exception as e:
            self.end_num_label.configure(text=f"End number: Error - {e}")

    def _start_pipeline_thread(self):
        if self.pipeline_running:
            messagebox.showwarning("Pipeline running", "Another pipeline is in progress.")
            return

        try:
            start_num = int(self.start_num_entry.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Start number must be an integer.")
            return

        raw_pad_width = self.pad_width_entry.get().strip()
        try:
            pad_width = int(raw_pad_width) if raw_pad_width else 0
            if pad_width <= 0:
                pad_width = max(1, len(str(start_num + len(self.urls_to_process) - 1)))
        except ValueError:
            pad_width = max(1, len(str(start_num + len(self.urls_to_process) - 1)))

        dest_dir = self.dest_dir_entry.get().strip()
        if not dest_dir:
            dest_dir = os.path.join(os.getcwd(), "Downloaded-Sub")
            self.gui_log_output(f"No output directory specified. Using: {dest_dir}", "yellow")

        # Get new prefix values
        folder_prefix = self.folder_prefix_entry.get().strip()
        # Subtitle file prefix is only used if 'Use Video Title' is NOT checked
        subtitle_file_prefix = self.subtitle_file_prefix_entry.get().strip() if not self.use_title_for_subtitle_filename.get() else ""
        content_file_prefix = self.content_file_prefix_entry.get().strip()

        # NEW: Get subtitle language and cookie file path
        selected_lang = self.subtitle_lang_entry.get().strip()
        if not selected_lang:
            selected_lang = "en"
            self.gui_log_output(f"No subtitle language specified. Defaulting to '{selected_lang}'.", "yellow")

        cookie_file_path = self.cookie_file_entry.get().strip()
        if cookie_file_path and not os.path.exists(cookie_file_path):
            messagebox.showerror("Cookie File Error", f"Cookie file not found at: {cookie_file_path}")
            return
        elif not cookie_file_path:
            self.gui_log_output("No cookie file specified. Proceeding without it.", "yellow")

        # NEW: Get Rate Limit Configuration
        rate_limit_enabled = self.rate_limit_enabled.get()
        min_wait_time = 0
        max_wait_time = 0
        if rate_limit_enabled:
            try:
                min_wait_time = int(self.min_wait_entry.get())
                max_wait_time = int(self.max_wait_entry.get())
                if min_wait_time < 0 or max_wait_time < 0:
                    messagebox.showerror("Invalid Rate Limit", "Min/Max wait times cannot be negative.")
                    return
                if min_wait_time > max_wait_time:
                    messagebox.showerror("Invalid Rate Limit", "Min wait time cannot be greater than Max wait time.")
                    return
            except ValueError:
                messagebox.showerror("Invalid Rate Limit", "Min/Max wait times must be integers.")
                return

        if not os.path.exists(dest_dir):
            try:
                os.makedirs(dest_dir, exist_ok=True)
                self.gui_log_output(f"Created output root directory: {dest_dir}", "green")
            except Exception as e:
                messagebox.showerror("Directory error", f"Cannot create root directory: {e}")
                return

        if not self.urls_to_process:
            messagebox.showwarning("No URLs", "Please add at least one YouTube URL to process.")
            return

        if not YTDLP_AVAILABLE:
            if not messagebox.askyesno("yt-dlp missing",
                                       "yt-dlp is not installed. Subtitle extraction will fail. Continue anyway?"):
                return
            self.gui_log_output("yt-dlp not available. Extraction will be skipped.", "yellow")

        self._toggle_ui_state(False)
        self.stop_pipeline_flag = False
        self.pipeline_running = True
        self.gui_log_output("Pipeline started!", "blue")

        threading.Thread(target=self._run_pipeline,
                         args=(start_num, pad_width, dest_dir, folder_prefix, subtitle_file_prefix,
                               content_file_prefix, selected_lang, cookie_file_path,
                               rate_limit_enabled, min_wait_time, max_wait_time),  # Pass new args
                         daemon=True).start()

    def _toggle_ui_state(self, enable: bool):
        """Enable/disable input widgets and buttons"""
        state = "normal" if enable else "disabled"
        self.single_url_entry.configure(state=state)
        self.start_num_entry.configure(state=state)
        self.pad_width_entry.configure(state=state)
        self.dest_dir_entry.configure(state=state)
        self.folder_prefix_entry.configure(state=state)

        # Only toggle subtitle_file_prefix_entry if 'Use Video Title' is OFF or if enabling everything
        if enable or not self.use_title_for_subtitle_filename.get():
            self.subtitle_file_prefix_entry.configure(state=state)
        else:  # If 'use title' is ON and master switch is OFF, keep it disabled
            self.subtitle_file_prefix_entry.configure(state="disabled")

        self.content_file_prefix_entry.configure(state=state)
        # NEW: toggle new widgets
        self.subtitle_lang_entry.configure(state=state)
        self.cookie_file_entry.configure(state=state)

        self.start_button.configure(state=state)
        self.add_url_button.configure(state=state)
        self.browse_url_file_button.configure(state=state)
        self.clear_urls_button.configure(state=state)
        self.browse_dest_dir_button.configure(state=state)
        # NEW: toggle new buttons
        self.browse_cookie_file_button.configure(state=state)
        self.use_title_checkbox.configure(state=state)  # Toggle the new checkbox

        # NEW: Toggle Rate Limit Widgets
        self.rate_limit_checkbox.configure(state=state)
        # The min/max wait entries depend on both the global state AND the checkbox state
        if enable and self.rate_limit_enabled.get():
            self.min_wait_entry.configure(state="normal")
            self.max_wait_entry.configure(state="normal")
        else:
            self.min_wait_entry.configure(state="disabled")
            self.max_wait_entry.configure(state="disabled")


        self.cancel_button.configure(state="normal" if not enable else "disabled")
        if not enable:
            self.cancel_button.configure(text="Stopping...")

    def _cancel_pipeline(self):
        if messagebox.askyesno("Cancel Pipeline", "Are you sure you want to stop the current pipeline?"):
            self.stop_pipeline_flag = True
            self.gui_log_output("Cancel requested. Waiting for current step to complete...", "yellow")
            self.cancel_button.configure(state="disabled", text="Stopping...")

    def _update_progress_gui(self, current: int, total: int, description: str):
        """Updates GUI progress bar and label from background thread"""
        self.root.after(0, lambda: self.current_task_label.configure(text=description))
        if total > 0:
            self.root.after(0, lambda: self.pipeline_progress_bar.set(current / total))
        else:
            self.root.after(0, lambda: self.pipeline_progress_bar.set(0))

    # MODIFIED: _run_pipeline to accept rate_limit_enabled, min_wait_time, max_wait_time
    def _run_pipeline(self, start_num: int, pad_width: int, dest_dir: str,
                      folder_prefix: str, subtitle_file_prefix: str, content_file_prefix: str,
                      selected_lang: str, cookie_file_path: Optional[str],
                      rate_limit_enabled: bool, min_wait_time: int, max_wait_time: int):
        try:
            self.gui_log_output("\n--- Starting YouTube Subtitle Extraction ---", "blue")
            self._update_progress_gui(0, len(self.urls_to_process), "Preparing...")

            results: List[Dict[str, Any]] = []
            total_urls = len(self.urls_to_process)

            # Process each URL
            for i, url in enumerate(self.urls_to_process):
                if self.stop_pipeline_flag:
                    self.gui_log_output("Pipeline cancelled during extraction.", "red")
                    return

                self._update_progress_gui(i, total_urls, f"Processing video {i + 1}/{total_urls}: {url}")
                self.gui_log_output(f"Processing URL: {url}")

                vid = extract_video_id(url)
                existing_index, _ = load_existing_index('youtube_results.json')

                r = None  # Initialize r
                if vid and vid in existing_index:
                    cached_item = existing_index[vid]
                    # If cached result looks like it has content and was successful, use it.
                    # Otherwise, re-extract for the current selected_lang.
                    # We also re-extract if the current language doesn't match the cached one,
                    # or if the user wants to use title for filename and we don't have title.
                    if cached_item.get('status') == 'success' and \
                            not cached_item.get('subtitles', '').startswith("No ") and \
                            not cached_item.get('subtitles', '').startswith("Error downloading") and \
                            cached_item.get('extracted_lang') == selected_lang and \
                            (not self.use_title_for_subtitle_filename.get() or cached_item.get('title')):
                        r = cached_item
                        r.setdefault('url', url)  # Ensure url is present
                        self.gui_log_output(f"↷ Using cached result for: {url}", "blue")
                    else:
                        self.gui_log_output(
                            f"Cached result for {url} needs re-extraction (lang/title mismatch or error).", "yellow")
                        r = get_video_info(url, self.gui_log_output, selected_lang, cookie_file_path)
                        r['extracted_lang'] = selected_lang  # Store the language used for extraction
                        r.setdefault('url', url)  # Ensure url is present
                        status_msg = f"{'✓ OK' if r.get('status') == 'success' else '✗ Error'} - {url}"
                        self.gui_log_output(status_msg, "green" if r.get('status') == 'success' else "red")
                else:
                    r = get_video_info(url, self.gui_log_output, selected_lang, cookie_file_path)  # Pass new args
                    r['extracted_lang'] = selected_lang  # Store the language used for extraction
                    status_msg = f"{'✓ OK' if r.get('status') == 'success' else '✗ Error'} - {url}"
                    self.gui_log_output(status_msg, "green" if r.get('status') == 'success' else "red")

                if r:  # Make sure r is not None before appending
                    results.append(r)

                # NEW: Apply Rate Limit if enabled
                if rate_limit_enabled and i < total_urls - 1 and not self.stop_pipeline_flag:
                    wait_time = random.randint(min_wait_time, max_wait_time)
                    self.gui_log_output(f"⏳ Waiting {wait_time} seconds before next video.", "yellow")
                    time.sleep(wait_time)
                elif not rate_limit_enabled and i < total_urls - 1:
                    self.gui_log_output("Rate limit is disabled. Proceeding to next video without delay.", "blue")


            self._update_progress_gui(total_urls, total_urls, "Completed extraction.")
            save_results_merge(results, self.gui_log_output)
            self.gui_log_output("✓ Completed subtitle extraction.", "green")

            # Save subtitle files
            self.gui_log_output("\n--- Saving Subtitle Files ---", "blue")
            saved_count = 0

            for idx, r in enumerate(results):
                if self.stop_pipeline_flag:
                    self.gui_log_output("Pipeline cancelled during file saving.", "red")
                    return

                file_num = start_num + idx
                numbered_suffix = f"{file_num:0{pad_width}d}"

                current_video_folder = os.path.join(dest_dir, f"{folder_prefix}{numbered_suffix}")
                os.makedirs(current_video_folder, exist_ok=True)
                self.gui_log_output(f"Created folder: {current_video_folder}", "blue")

                # Determine subtitle filename based on checkbox state
                if self.use_title_for_subtitle_filename.get():
                    video_title = r.get('title', 'Unknown_Video_Title')
                    cleaned_title = sanitize_filename(video_title)
                    subtitle_filename = f"{numbered_suffix}. {cleaned_title}.txt"
                else:
                    subtitle_filename = f"{subtitle_file_prefix}{numbered_suffix}.txt"

                subtitle_filepath = os.path.join(current_video_folder, subtitle_filename)

                # Content file (empty)
                content_filename = f"{content_file_prefix}{numbered_suffix}.txt"
                content_filepath = os.path.join(current_video_folder, content_filename)

                if r.get('status') != 'success':
                    error_msg = r.get('error', 'Unknown error')
                    with open(subtitle_filepath, 'w', encoding='utf-8') as f:
                        f.write(f"ERROR: {error_msg}\n")
                        f.write(f"URL: {r.get('url', 'N/A')}\n")
                    self.gui_log_output(
                        f"⚠ Saved error note for {subtitle_filename} in {os.path.basename(current_video_folder)}",
                        "yellow")
                else:
                    subtitle_content = r.get('subtitles',
                                             f'No {selected_lang} subtitles available')  # Use selected_lang in default message
                    try:
                        with open(subtitle_filepath, 'w', encoding='utf-8') as f:
                            f.write(subtitle_content)
                        saved_count += 1
                        self.gui_log_output(f"✓ Saved subtitle: {subtitle_filename} - {r.get('title', 'Unknown')}",
                                            "green")
                    except Exception as e:
                        self.gui_log_output(f"✗ Error saving subtitle {subtitle_filename}: {e}", "red")

                try:
                    with open(content_filepath, 'w', encoding='utf-8') as f:
                        f.write("")
                    self.gui_log_output(f"✓ Created empty content file: {content_filename}", "green")
                except Exception as e:
                    self.gui_log_output(f"✗ Error creating content file {content_filename}: {e}", "red")

                self._update_progress_gui(idx + 1, len(results), f"Saving files for video {idx + 1}/{len(results)}")

            self.gui_log_output(
                f"\n→ Successfully processed {saved_count}/{len(results)} videos with files saved to subfolders under: {dest_dir}",
                "green")
            messagebox.showinfo("Pipeline Complete",
                                f"Successfully processed {saved_count} videos!\n\nOutput root: {dest_dir}")

        except Exception as e:
            error_msg = f"Critical error occurred: {e}"
            self.gui_log_output(error_msg, "red")
            messagebox.showerror("Pipeline Error", error_msg)
        finally:
            self.root.after(0, lambda: self.current_task_label.configure(text="Ready."))
            self.root.after(0, lambda: self.pipeline_progress_bar.set(0))
            self.pipeline_running = False
            self.stop_pipeline_flag = False
            self.root.after(0, lambda: self._toggle_ui_state(True))
            self.root.after(0, lambda: self.cancel_button.configure(text="Cancel"))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = EBSToolPackGUI()
    app.run()
