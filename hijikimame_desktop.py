import tkinter as tk
from tkinter import messagebox, filedialog
from PIL import Image, ImageTk, ImageGrab, ImageChops
import collections
try:
    Image.MAX_IMAGE_PIXELS = None
except:
    pass

import math
import json
import random
import time 
import sys 
import os 
import atexit 
import socket 
import subprocess
import runpy
import threading
import hashlib
import re
try:
    import requests
except Exception:
    requests = None
import shutil
import tempfile
import stat

# --- IPC設定 (多重起動防止) ---
HOST = '127.0.0.1'
PORT = 31500 
EXIT_COMMAND = b'ANIMATED_EXIT' 
CLIENT_TIMEOUT = 3.0 

# --- PyInstaller対応関数 ---
GITHUB_DEFAULT_OWNER = "ramune478"
GITHUB_DEFAULT_REPO = "hijikimame-plus"

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if os.environ.get('HIJIKI_EMBEDDED_RUNNING') != '1':
    for _a in list(sys.argv[1:]):
        if _a.startswith('--exec-embedded='):
            _fname = _a.split('=', 1)[1]
            try:
                _script_path = resource_path(_fname)
            except Exception:
                _script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _fname)
            if os.path.exists(_script_path):
                try:
                    # remove the flag so the embedded script won't see it
                    sys.argv = [ _script_path ]
                    os.environ['HIJIKI_EMBEDDED_RUNNING'] = '1'
                    runpy.run_path(_script_path, run_name='__main__')
                finally:
                    sys.exit(0)
            else:
                print(f"embedded script not found: {_script_path}")
                sys.exit(1)

# --- 設定パラメータ ---
TRACKING_SPEED = 0.01          
COLLISION_DISTANCE_BASE = 50 
COLLISION_EXPANSION_RATE = 0.3 
BOUNCE_STRENGTH = 1.5          
UPDATE_INTERVAL = 30 
MAX_ACCEL_FORCE = 5            
THROW_MULTIPLIER = 3           
THROW_COOLDOWN_FRAMES = 20     
MOUSE_ACCELERATION_THROW_THRESHOLD = 40.0
MOUSE_ACCELERATION_THROW_MULTIPLIER = 3.0

# --- nijiki (虹き豆) アニメ関連デフォルト ---
NIJIKI_DEFAULT_FPS = 10
NIJIKI_CACHE_SIZE_DEFAULT = 6
NIJIKI_MAX_FRAMES_DEFAULT = 60

# --- 画面端バウンド関連デフォルト ---
EDGE_BOUNCE_STRENGTH = 0.8
EDGE_BOUNCE_COUNT_DEFAULT = 3
SETTINGS_FILE = "hijiki_settings.json"

# --- たこ焼き状態の設定 ---
TAKOYAKI_IMAGE_PATH = "takoyaki.png" 

# --- 目の描画に関する設定 ---
EYE_RADIUS = 3      
EYE_OFFSET_X = 10   
EYE_OFFSET_Y = -3   
EYE_MOVEMENT_LIMIT = 4 

TRANSPARENT_COLOR = '#000001' 
DEFAULT_EYE_COLOR = 'black'
INVERTED_EYE_COLOR = 'white'

# アプリバージョン（リリースタグと一致させてください）
VERSION = "v2.2.0"


def _self_replace_target(target_path, timeout=30):
    """実行中のバイナリ（sys.executable）を target_path にコピーする。
    target_path がロックされている限りリトライし、成功後に target_path を起動する。"""
    src = sys.executable
    try:
        start = time.time()
        while True:
            try:
                shutil.copyfile(src, target_path)
                try:
                    os.chmod(target_path, os.stat(src).st_mode | stat.S_IEXEC)
                except:
                    pass
                break
            except PermissionError:
                if time.time() - start > timeout:
                    return False
                time.sleep(0.5)
            except Exception:
                return False
        try:
            subprocess.Popen([target_path])
        except Exception:
            pass
        return True
    except Exception:
        return False


def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def start_update_check_thread():
    try:
        t = threading.Thread(target=_check_and_initiate_update, daemon=True)
        t.start()
    except:
        pass


def _check_and_initiate_update():
    """GitHub Releases を確認して、更新があればダウンロード→自己置換フローを開始する。

    環境変数 `GITHUB_OWNER` と `GITHUB_REPO` を必須とし、プライベートの場合は
    `GITHUB_UPDATE_TOKEN` または `GITHUB_TOKEN` を利用してください。
    """
    if VERSION.startswith('Snapshot'):
        return
    if not getattr(sys, 'frozen', False):
        return
    if requests is None:
        return
    owner = os.environ.get('GITHUB_OWNER')
    repo = os.environ.get('GITHUB_REPO')
    if not owner or not repo:
        return
    token = os.environ.get('GITHUB_UPDATE_TOKEN') or os.environ.get('GITHUB_TOKEN')
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers=headers, timeout=10)
        if resp.status_code != 200:
            return
        rel = resp.json()
        tag = rel.get('tag_name')
        if not tag or tag == VERSION:
            return
        # try to find accompanying sha256 asset (preferred) for verification
        sha_expected = None
        for a in rel.get('assets', []):
            aname = a.get('name', '').lower()
            if aname.endswith('.sha256') or aname.endswith('.sha256.txt') or aname.endswith('.sha256sum'):
                sha_url = a.get('url')
                if sha_url:
                    try:
                        dl_sha_headers = dict(headers)
                        dl_sha_headers['Accept'] = 'application/octet-stream'
                        rsha = requests.get(sha_url, headers=dl_sha_headers, timeout=20)
                        if rsha.status_code == 200:
                            txt = rsha.text.strip()
                            m = re.search(r'([A-Fa-f0-9]{64})', txt)
                            if m:
                                sha_expected = m.group(1).lower()
                    except:
                        pass
                break
        exe_name = os.path.basename(sys.executable)
        asset = None
        for a in rel.get('assets', []):
            name = a.get('name', '')
            if name == exe_name or name.endswith('.exe'):
                asset = a
                break
        if not asset:
            return
        download_url = asset.get('url')
        if not download_url:
            return
        exe_dir = os.path.dirname(sys.executable)
        new_exe_path = os.path.join(exe_dir, exe_name + ".update.exe")
        tmp_path = new_exe_path + ".download"
        dl_headers = dict(headers)
        dl_headers["Accept"] = "application/octet-stream"
        with requests.get(download_url, headers=dl_headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
        # If we have an expected SHA, verify the download
        try:
            if sha_expected:
                actual = _sha256_of_file(tmp_path)
                if actual.lower() != sha_expected.lower():
                    try:
                        os.remove(tmp_path)
                    except:
                        pass
                    return
        except Exception:
            try:
                os.remove(tmp_path)
            except:
                pass
            return
        try:
            if os.path.exists(new_exe_path):
                os.remove(new_exe_path)
            os.replace(tmp_path, new_exe_path)
        except Exception:
            try:
                os.rename(tmp_path, new_exe_path)
            except Exception:
                return
        try:
            subprocess.Popen([new_exe_path, '--self-replace', sys.executable], close_fds=True)
            sys.exit(0)
        except Exception:
            return
    except Exception:
        return

class HijikimameApp:
    def __init__(self, master):
        self.master = master
        self.server_socket = None 

        # 掴む・投げる機能用の変数
        self.is_dragging_stop = False 
        self.throw_cooldown = 0 
        self.drag_vx = 0
        self.drag_vy = 0 

        # --- 多重起動チェック ---
        if self._is_another_instance_running():
            self.master.destroy()
            sys.exit(0)
        else:
            self._start_ipc_server()
            atexit.register(self._close_ipc_server)
        
        # --- UI初期設定 ---
        master.title("ひじき豆")
        try:
            master.iconbitmap(resource_path('hijikimame_desktop.ico'))
        except:
            pass
        master.overrideredirect(True)
        master.wm_attributes("-transparentcolor", TRANSPARENT_COLOR) 

        self.settings = {
            'selected_mode': 0,
            'nijiki_fps': NIJIKI_DEFAULT_FPS,
            'nijiki_cache_size': NIJIKI_CACHE_SIZE_DEFAULT,
            'nijiki_max_frames': NIJIKI_MAX_FRAMES_DEFAULT,
            'tracking_speed': TRACKING_SPEED,
            'throw_speed_multiplier': 2.5,  
            'max_throw_multiplier': 10,
            'edge_bounce_count': EDGE_BOUNCE_COUNT_DEFAULT,
            'edge_bounce_strength': EDGE_BOUNCE_STRENGTH,
            'mouse_repulsion_enabled': True,
            'screen_boundary_mode': 'bounce',
        }

        try:
            cfg = self.load_settings_file()
            if isinstance(cfg, dict):
                self.settings.update(cfg)
        except:
            pass

        self.nijiki_cache = collections.OrderedDict()
        self.nijiki_frame_index = 0
        self.nijiki_last_frame_time = time.time()
        self._nijiki_loader = None
        self.nijiki_indices = []
        self.nijiki_frames = None

        self.remaining_bounces = self.settings['edge_bounce_count']
        master.wm_attributes("-topmost", True)

        self.current_mode = 0 
        self.is_inverted = False
        self.target_position = None
        self.target_image_path = None
        self.target_image_template = None
        self.target_image_last_search = 0.0
        self._target_image_search_in_progress = False

        self.settings.setdefault('tracking_target_mode', 0)
        self.settings.setdefault('target_position', None)
        self.settings.setdefault('target_image_path', None)
        self.settings.setdefault('selected_mode', 0)
        self.settings.setdefault('screen_boundary_mode', 'bounce')

        if isinstance(self.settings.get('target_position'), list) and len(self.settings.get('target_position')) == 2:
            try:
                self.target_position = (int(self.settings['target_position'][0]), int(self.settings['target_position'][1]))
            except:
                self.target_position = None
        if self.settings.get('target_image_path'):
            self.target_image_path = self.settings.get('target_image_path')
            try:
                self.target_image_template = self.load_image(self.target_image_path)
            except:
                self.target_image_template = None
            if self.target_image_template is None:
                self.target_image_path = None
                self.settings['target_image_path'] = None
                if int(self.settings.get('tracking_target_mode', 0)) == 2:
                    self.settings['tracking_target_mode'] = 0

        self.original_image_path = resource_path("hijikimame_body.png") 
        self.original_image = self.load_image(self.original_image_path)
        self.takoyaki_image_path = resource_path(TAKOYAKI_IMAGE_PATH)
        self.takoyaki_image = self.load_image(self.takoyaki_image_path)
        self.extra_image_path = resource_path('3.png')
        self.extra_image = self.load_image(self.extra_image_path)
        
        if self.original_image is None:
            master.destroy()
            return
            
        self.image_width, self.image_height = self.original_image.size
        self.tk_image = ImageTk.PhotoImage(self.original_image)

        screen_width = master.winfo_vrootwidth()
        screen_height = master.winfo_vrootheight()
        self.x = screen_width // 2 - self.image_width // 2
        self.y = screen_height // 2 - self.image_height // 2
        self.vx = 0
        self.vy = 0
        
        self.is_exiting = False       
        self.exit_frames = self.load_gif_frames(resource_path("exit_animation.gif")) 
        self.current_frame_index = 0  
        
        self.start_time = time.time() 
        self.selective_mask = self._create_selective_mask(self.original_image) 
        
        self.last_mouse_x = master.winfo_pointerx()
        self.last_mouse_y = master.winfo_pointery()

        master.geometry(f'{self.image_width}x{self.image_height}+{int(self.x)}+{int(self.y)}')
        
        self.canvas = tk.Canvas(master, width=self.image_width, height=self.image_height, 
                                bg=TRANSPARENT_COLOR, highlightthickness=0)
        self.canvas.pack()
        
        self.character_id = self.canvas.create_image(self.image_width // 2, self.image_height // 2, 
                                                     image=self.tk_image)

        base_center_x = self.image_width // 2
        base_center_y = self.image_height // 2
        
        self.eye_left_id = self.canvas.create_oval(
            base_center_x - EYE_OFFSET_X - EYE_RADIUS,
            base_center_y + EYE_OFFSET_Y - EYE_RADIUS,
            base_center_x - EYE_OFFSET_X + EYE_RADIUS,
            base_center_y + EYE_OFFSET_Y + EYE_RADIUS,
            fill=DEFAULT_EYE_COLOR, tag='eye' 
        )
        self.eye_right_id = self.canvas.create_oval(
            base_center_x + EYE_OFFSET_X - EYE_RADIUS,
            base_center_y + EYE_OFFSET_Y - EYE_RADIUS,
            base_center_x + EYE_OFFSET_X + EYE_RADIUS,
            base_center_y + EYE_OFFSET_Y + EYE_RADIUS,
            fill=DEFAULT_EYE_COLOR, tag='eye' 
        )
        try:
            self.canvas.tag_raise(self.eye_left_id)
            self.canvas.tag_raise(self.eye_right_id)
        except:
            pass

        self.set_mode(self.settings.get('selected_mode', 0), save=False)
        self.update_position()
        
        self.canvas.bind("<Button-1>", self.start_drag_stop)
        self.canvas.bind("<ButtonRelease-1>", self.stop_drag_stop)
        self.canvas.bind("<Button-3>", self.open_edit_window)
        
        self.master.bind("<Control-h>", lambda e: self.start_exit_animation())
        self.master.bind("<Control-r>", lambda e: self.toggle_mode()) 
        self.master.bind("<Control-e>", lambda e: self.open_edit_window())
        self.master.bind("<Control-E>", lambda e: self.open_edit_window())
        
        self.master.after(100, self._check_ipc_command)
        self._latest_update_tag = None
        self._latest_update_body = None
        self._latest_update_download_url = None
        self._latest_update_sha_expected = None
        self._latest_update_script_url = None
        self._update_available = False
        self._update_button = None
        self.master.after(500, self.start_update_check_thread)
        try:
            self.master.after(200, lambda: self.open_edit_window())
        except:
            pass

    def _show_update_dialog(self, title, text):
        try:
            messagebox.showinfo(title, text)
        except:
            pass

    def _get_local_script_path(self):
        try:
            if getattr(sys, 'frozen', False):
                candidate = os.path.join(os.path.dirname(sys.executable), 'hijikimame_desktop.py')
                if os.path.isfile(candidate):
                    return candidate
                return None
            script_path = os.path.abspath(sys.argv[0])
            if os.path.isfile(script_path) and script_path.lower().endswith('.py'):
                return script_path
            if hasattr(sys, 'file'):
                script_path = os.path.abspath(__file__)
                if os.path.isfile(script_path):
                    return script_path
        except:
            pass
        return None

    def _download_latest_script(self):
        if requests is None or not self._latest_update_script_url:
            return None
        try:
            resp = requests.get(self._latest_update_script_url, timeout=30)
            if resp.status_code == 200:
                return resp.content
        except:
            pass
        return None

    def _refresh_update_button(self):
        try:
            if self._update_button is None:
                return
            if self._update_available:
                if not self._update_button.winfo_ismapped():
                    self._update_button.pack(side='right', padx=2)
            else:
                self._update_button.pack_forget()
        except:
            pass

    def _perform_update(self):
        if not self._update_available:
            try:
                self._show_update_dialog("更新なし", "利用可能なアップデートはありません。")
            except:
                pass
            return
        try:
            release_notes = self._latest_update_body or '更新内容はありません。'
            message = f"{self._latest_update_tag} に揃えます。\n\n変更内容:\n{release_notes}"
            self._show_update_dialog("最新バージョンに揃える", message)
        except:
            pass
        threading.Thread(target=self._download_and_apply_update, daemon=True).start()

    def _download_and_apply_update(self):
        try:
            if requests is None:
                self.master.after(0, lambda: self._show_update_dialog("更新不可", "requests がインストールされていないため更新できません。"))
                return
            token = os.environ.get('GITHUB_UPDATE_TOKEN') or os.environ.get('GITHUB_TOKEN')
            headers = {"Accept": "application/vnd.github.v3+json"}
            if token:
                headers["Authorization"] = f"token {token}"

            script_updated = False
            script_path = self._get_local_script_path()
            script_data = self._download_latest_script()
            if script_data and script_path:
                try:
                    with open(script_path, 'wb') as f:
                        f.write(script_data)
                    script_updated = True
                except:
                    script_updated = False

            exe_downloaded = False
            exe_saved_path = None
            download_url = self._latest_update_download_url
            if download_url:
                dl_headers = dict(headers)
                dl_headers["Accept"] = "application/octet-stream"
                if getattr(sys, 'frozen', False):
                    exe_name = os.path.basename(sys.executable)
                    exe_dir = os.path.dirname(sys.executable)
                    new_exe_path = os.path.join(exe_dir, exe_name + ".update.exe")
                    tmp_path = new_exe_path + ".download"
                else:
                    script_dir = os.path.dirname(script_path) if script_path else os.getcwd()
                    asset_name = getattr(self, '_latest_update_asset_name', None) or os.path.basename(download_url)
                    if not asset_name.lower().endswith('.exe'):
                        asset_name = 'hijikimame-plus-latest.exe'
                    exe_saved_path = os.path.join(script_dir, asset_name)
                    tmp_path = exe_saved_path + ".download"
                try:
                    with requests.get(download_url, headers=dl_headers, stream=True, timeout=60) as r:
                        r.raise_for_status()
                        with open(tmp_path, 'wb') as f:
                            for chunk in r.iter_content(8192):
                                if chunk:
                                    f.write(chunk)
                    if self._latest_update_sha_expected:
                        actual = _sha256_of_file(tmp_path)
                        if actual.lower() != self._latest_update_sha_expected.lower():
                            try:
                                os.remove(tmp_path)
                            except:
                                pass
                            self.master.after(0, lambda: self._show_update_dialog("更新失敗", "ダウンロードファイルの検証に失敗しました。"))
                            return
                    if getattr(sys, 'frozen', False):
                        if os.path.exists(new_exe_path):
                            os.remove(new_exe_path)
                        os.replace(tmp_path, new_exe_path)
                        exe_downloaded = True
                    else:
                        if exe_saved_path and os.path.exists(exe_saved_path):
                            os.remove(exe_saved_path)
                        os.replace(tmp_path, exe_saved_path)
                        exe_downloaded = True
                except Exception:
                    try:
                        if tmp_path and os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except:
                        pass
                    self.master.after(0, lambda: self._show_update_dialog("更新失敗", "更新のダウンロードまたは保存に失敗しました。"))
                    return

            if getattr(sys, 'frozen', False):
                if exe_downloaded:
                    try:
                        subprocess.Popen([new_exe_path, '--self-replace', sys.executable], close_fds=True)
                        self.master.after(0, lambda: self._show_update_dialog("更新中", "更新を適用しています。アプリを再起動します。"))
                        sys.exit(0)
                        return
                    except Exception:
                        pass
                if script_updated:
                    self.master.after(0, lambda: self._show_update_dialog("更新完了", "最新の Python スクリプトを保存しました。次回起動時に最新バージョンになります。"))
                    return
                self.master.after(0, lambda: self._show_update_dialog("更新完了", "最新バージョンの取得が完了しました。"))
                return

            # 非Frozen 実行時: Python スクリプトを更新し、exe がダウンロードできたら保存
            if script_updated and exe_downloaded:
                self.master.after(0, lambda: self._show_update_dialog("更新完了", f"最新バージョンに揃えました。exe を {exe_saved_path} に保存しました。"))
            elif script_updated:
                self.master.after(0, lambda: self._show_update_dialog("更新完了", "最新バージョンの Python スクリプトを保存しました。"))
            elif exe_downloaded:
                self.master.after(0, lambda: self._show_update_dialog("更新完了", f"最新バージョンの exe を {exe_saved_path} に保存しました。"))
            else:
                self.master.after(0, lambda: self._show_update_dialog("更新不可", "最新バージョンの取得に失敗しました。"))
        except Exception:
            pass

    def start_update_check_thread(self):
        try:
            t = threading.Thread(target=self._check_and_initiate_update, daemon=True)
            t.start()
        except:
            pass

    def _check_and_initiate_update(self):
        if VERSION.startswith('Snapshot'):
            return
        if requests is None:
            return
        owner = os.environ.get('GITHUB_OWNER', GITHUB_DEFAULT_OWNER)
        repo = os.environ.get('GITHUB_REPO', GITHUB_DEFAULT_REPO)
        if not owner or not repo:
            return
        token = os.environ.get('GITHUB_UPDATE_TOKEN') or os.environ.get('GITHUB_TOKEN')
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        try:
            resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers=headers, timeout=10)
            if resp.status_code != 200:
                return
            rel = resp.json()
            tag = rel.get('tag_name')
            body = rel.get('body', '') or '更新内容はありません。'
            if not tag or tag == VERSION:
                return
            self._latest_update_tag = tag
            self._latest_update_body = body
            self._latest_update_script_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{tag}/hijikimame_desktop.py"
            sha_expected = None
            for a in rel.get('assets', []):
                aname = a.get('name', '').lower()
                if aname.endswith('.sha256') or aname.endswith('.sha256.txt') or aname.endswith('.sha256sum'):
                    sha_url = a.get('url')
                    if sha_url:
                        try:
                            dl_sha_headers = dict(headers)
                            dl_sha_headers['Accept'] = 'application/octet-stream'
                            rsha = requests.get(sha_url, headers=dl_sha_headers, timeout=20)
                            if rsha.status_code == 200:
                                txt = rsha.text.strip()
                                m = re.search(r'([A-Fa-f0-9]{64})', txt)
                                if m:
                                    sha_expected = m.group(1).lower()
                        except:
                            pass
                    break
            exe_name = os.path.basename(sys.executable)
            asset = None
            for a in rel.get('assets', []):
                name = a.get('name', '')
                if name == exe_name or name.endswith('.exe'):
                    asset = a
                    break
            if asset:
                download_url = asset.get('url')
                if download_url:
                    self._latest_update_download_url = download_url
                    self._latest_update_asset_name = asset.get('name')
                else:
                    self._latest_update_download_url = None
                    self._latest_update_asset_name = None
            else:
                self._latest_update_download_url = None
                self._latest_update_asset_name = None
            self._latest_update_sha_expected = sha_expected
            self._update_available = True
            self.master.after(0, self._refresh_update_button)
            return
        except Exception:
            return

    def _apply_mode(self, mode):
        if self.is_exiting:
            return
        self.current_mode = mode
        should_update_image = True
        new_image = self.original_image
        new_eye_color = DEFAULT_EYE_COLOR
        self.is_inverted = False

        if self.current_mode == 0:
            pass
        elif self.current_mode == 1:
            self.is_inverted = True
            new_eye_color = INVERTED_EYE_COLOR
            img_copy = self.original_image.copy()
            r, g, b, a = img_copy.split()
            r_inverted = r.point(lambda x: 255 - x)
            g_inverted = g.point(lambda x: 255 - x)
            b_inverted = b.point(lambda x: 255 - x)
            new_image = Image.merge("RGBA", (r_inverted, g_inverted, b_inverted, a))
        elif self.current_mode == 2:
            new_eye_color = DEFAULT_EYE_COLOR
            if self.takoyaki_image:
                new_image = self.takoyaki_image
        elif self.current_mode == 3:
            new_eye_color = DEFAULT_EYE_COLOR
            if not self.nijiki_cache and not getattr(self, '_nijiki_loader', None):
                try:
                    seq_dir = resource_path('nijiki')
                    use_sequence = False
                    try:
                        if os.path.isdir(seq_dir):
                            for fn in os.listdir(seq_dir):
                                if fn.lower().endswith('.png') and fn.lower().startswith('nijiki_'):
                                    use_sequence = True
                                    break
                    except:
                        use_sequence = False
                    if use_sequence:
                        try:
                            self._start_nijiki_sequence_loader(seq_dir)
                        except:
                            pass
                except:
                    pass
            if self.nijiki_cache:
                try:
                    if 0 in self.nijiki_cache:
                        first_photo = self.nijiki_cache.get(0)
                    else:
                        first_photo = next(iter(self.nijiki_cache.values()))
                    self.nijiki_frame_index = 0
                    self.nijiki_last_frame_time = time.time()
                    self.tk_image = first_photo
                    self.canvas.itemconfig(self.character_id, image=self.tk_image)
                    should_update_image = False
                except StopIteration:
                    pass
                try:
                    self.canvas.itemconfigure(self.eye_left_id, state='normal')
                    self.canvas.itemconfigure(self.eye_right_id, state='normal')
                    self.canvas.tag_raise(self.eye_left_id)
                    self.canvas.tag_raise(self.eye_right_id)
                except:
                    pass

        if should_update_image:
            self.tk_image = ImageTk.PhotoImage(new_image)
            self.canvas.itemconfig(self.character_id, image=self.tk_image)
        try:
            self.canvas.itemconfig(self.eye_left_id, fill=new_eye_color)
            self.canvas.itemconfig(self.eye_right_id, fill=new_eye_color)
            if self.current_mode != 3:
                self.canvas.itemconfigure(self.eye_left_id, state='normal')
                self.canvas.itemconfigure(self.eye_right_id, state='normal')
        except:
            pass

    def close_all_instances(self):
        """IPC経由で全てのインスタンスに終了コマンドを送り、自身も終了アニメを開始する"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect((HOST, PORT))
                s.sendall(EXIT_COMMAND)
        except:
            pass
        self.start_exit_animation()

    # --- IPC処理メソッド群 ---
    def _is_another_instance_running(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(CLIENT_TIMEOUT) 
                s.connect((HOST, PORT))
                s.sendall(EXIT_COMMAND)
            return True 
        except: 
            return False

    def _start_ipc_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
            self.server_socket.bind((HOST, PORT))
            self.server_socket.listen(1)
            self.server_socket.setblocking(False) 
        except:
            self.master.destroy()
            sys.exit(1)
            
    def _close_ipc_server(self):
        if self.server_socket: self.server_socket.close()

    def _check_ipc_command(self):
        if self.is_exiting or not self.server_socket: return 
        try:
            conn, addr = self.server_socket.accept()
            with conn:
                data = conn.recv(4096)
                if data == EXIT_COMMAND:
                    self.start_exit_animation()
                elif data.startswith(b'SETTINGS:'):
                    try:
                        payload = data[len(b'SETTINGS:'):].decode('utf-8')
                        settings = json.loads(payload)
                        self.apply_remote_settings(settings)
                    except:
                        pass
        except: pass
        self.master.after(100, self._check_ipc_command)

    # --- 画像処理・モード切替 ---
    def _create_selective_mask(self, image):
        img_rgb = image.convert('RGB')
        mask = Image.new('L', image.size, 0)
        R_MIN, G_MIN, B_MAX = 200, 180, 100 
        for x in range(image.width):
            for y in range(image.height):
                R, G, B = img_rgb.getpixel((x, y))
                is_yellow_body = (R >= R_MIN and G >= G_MIN and B <= B_MAX) and (abs(R - G) < 50)
                is_green_stem = (G > R * 1.5) 
                is_red_mouth = (R > G * 1.5 and B < 50) 
                if is_yellow_body and not is_green_stem and not is_red_mouth:
                    mask.putpixel((x, y), 255)
        return mask
        
    def load_image(self, path):
        try:
            im = Image.open(path).convert("RGBA")
        except:
            return None
        return im

    def set_mode(self, mode, save=True):
        if self.is_exiting:
            return
        try:
            mode = int(mode)
        except:
            return
        if mode < 0:
            return
        self.current_mode = mode
        self.settings['selected_mode'] = mode
        if save:
            self.save_settings_file()
        try:
            self._refresh_character_buttons()
        except:
            pass

        should_update_image = True
        new_image = self.original_image
        new_eye_color = DEFAULT_EYE_COLOR
        self.is_inverted = False

        if self.current_mode == 0:
            pass
        elif self.current_mode == 1:
            self.is_inverted = True
            new_eye_color = INVERTED_EYE_COLOR
            img_copy = self.original_image.copy()
            r, g, b, a = img_copy.split()
            r_inverted = r.point(lambda x: 255 - x)
            g_inverted = g.point(lambda x: 255 - x)
            b_inverted = b.point(lambda x: 255 - x)
            new_image = Image.merge("RGBA", (r_inverted, g_inverted, b_inverted, a))
        elif self.current_mode == 2:
            if self.takoyaki_image:
                new_image = self.takoyaki_image
        elif self.current_mode == 3:
            new_eye_color = DEFAULT_EYE_COLOR
            if not self.nijiki_cache and not getattr(self, '_nijiki_loader', None):
                try:
                    seq_dir = resource_path('nijiki')
                    use_sequence = False
                    try:
                        if os.path.isdir(seq_dir):
                            for fn in os.listdir(seq_dir):
                                if fn.lower().endswith('.png') and fn.lower().startswith('nijiki_'):
                                    use_sequence = True
                                    break
                    except:
                        use_sequence = False
                    if use_sequence:
                        try:
                            self._start_nijiki_sequence_loader(seq_dir)
                        except:
                            pass
                except:
                    pass
            if self.nijiki_cache:
                try:
                    if 0 in self.nijiki_cache:
                        first_photo = self.nijiki_cache.get(0)
                    else:
                        first_photo = next(iter(self.nijiki_cache.values()))
                    self.nijiki_frame_index = 0
                    self.nijiki_last_frame_time = time.time()
                    self.tk_image = first_photo
                    self.canvas.itemconfig(self.character_id, image=self.tk_image)
                    should_update_image = False
                except StopIteration:
                    pass
                try:
                    self.canvas.itemconfigure(self.eye_left_id, state='normal')
                    self.canvas.itemconfigure(self.eye_right_id, state='normal')
                    self.canvas.tag_raise(self.eye_left_id)
                    self.canvas.tag_raise(self.eye_right_id)
                except:
                    pass
        elif self.current_mode == 4:
            if self.extra_image:
                new_image = self.extra_image

        if should_update_image:
            self.tk_image = ImageTk.PhotoImage(new_image)
            self.canvas.itemconfig(self.character_id, image=self.tk_image)
        try:
            self.canvas.itemconfig(self.eye_left_id, fill=new_eye_color)
            self.canvas.itemconfig(self.eye_right_id, fill=new_eye_color)
            if self.current_mode != 3:
                self.canvas.itemconfigure(self.eye_left_id, state='normal')
                self.canvas.itemconfigure(self.eye_right_id, state='normal')
        except:
            pass

    def toggle_mode(self):
        if self.is_exiting:
            return
        self.set_mode((self.current_mode + 1) % 5)

    def load_gif_frames(self, path):
        frames = []
        try:
            img = Image.open(path)
            nframes = getattr(img, 'n_frames', 1)
            max_frames = 60
            if nframes <= max_frames:
                indices = list(range(nframes))
            else:
                step = max(1, nframes // max_frames)
                indices = list(range(0, nframes, step))[:max_frames]
            for i in indices:
                img.seek(i)
                part = img.copy().convert('RGBA')
                # 各フレームを個別に扱い、前フレームとの累積合成を行わない。
                # 終了アニメーションでの不要なブレンドを防止するための変更。
                frame = part.copy()
                try:
                    if hasattr(self, 'image_width') and hasattr(self, 'image_height'):
                        target_w, target_h = self.image_width, self.image_height
                        fw, fh = frame.size
                        if fw > target_w or fh > target_h:
                            frame.thumbnail((target_w, target_h), Image.LANCZOS)
                except:
                    pass
                try:
                    data = list(frame.getdata())
                    newdata = []
                    for (r, g, b, a) in data:
                        if r < 16 and g < 16 and b < 16:
                            newdata.append((0, 0, 0, 0))
                        else:
                            newdata.append((r, g, b, a))
                    frame.putdata(newdata)
                except:
                    pass
                frames.append(ImageTk.PhotoImage(frame))
            return frames
        except Exception:
            return []

    def _start_nijiki_sequence_loader(self, dir_path):
        try:
            files = [f for f in os.listdir(dir_path) if f.lower().endswith('.png') and f.lower().startswith('nijiki_')]
            files.sort()
        except:
            return
        if not files:
            return
        self.nijiki_cache.clear()
        for i, fname in enumerate(files):
            try:
                p = os.path.join(dir_path, fname)
                im = Image.open(p).convert('RGBA')
                try:
                    if hasattr(self, 'image_width') and hasattr(self, 'image_height'):
                        target_w, target_h = self.image_width, self.image_height
                        fw, fh = im.size
                        if fw > target_w or fh > target_h:
                            im.thumbnail((target_w, target_h), Image.LANCZOS)
                except:
                    pass
                photo = ImageTk.PhotoImage(im)
                self.nijiki_cache[i] = photo
            except:
                pass
        self.nijiki_indices = list(range(len(self.nijiki_cache)))
        if self.nijiki_cache:
            try:
                first = self.nijiki_cache.get(0, next(iter(self.nijiki_cache.values())))
                self.nijiki_frame_index = 0
                self.nijiki_last_frame_time = time.time()
                self.tk_image = first
                self.canvas.itemconfig(self.character_id, image=self.tk_image)
            except:
                pass

    def _get_tracking_target_mode_display(self):
        mode = int(self.settings.get('tracking_target_mode', 0))
        if mode == 1:
            return '追尾先: 指定位置'
        if mode == 2:
            return '追尾先: 画像'
        return '追尾先: マウス'

    def _get_target_status_text(self):
        mode = int(self.settings.get('tracking_target_mode', 0))
        if mode == 1:
            if self.target_position:
                return f'選択位置: {self.target_position[0]}, {self.target_position[1]}'
            return '選択位置: なし'
        if mode == 2:
            label = f'画像: {os.path.basename(self.target_image_path)}' if self.target_image_path else '画像: なし'
            if self.target_position:
                label += f' (現在: {self.target_position[0]}, {self.target_position[1]})'
            return label
        return 'マウス位置を追尾します'

    def _update_target_status_labels(self):
        try:
            if hasattr(self, '_target_mode_label'):
                self._target_mode_label.config(text=self._get_tracking_target_mode_display())
            if hasattr(self, '_target_status_label'):
                self._target_status_label.config(text=self._get_target_status_text())
        except:
            pass

    def _refresh_character_buttons(self):
        try:
            for mi, btn in getattr(self, '_character_buttons', {}).items():
                if mi == self.current_mode:
                    btn.config(relief='sunken', bg='#d0f0c0')
                else:
                    btn.config(relief='raised', bg='SystemButtonFace')
        except:
            pass

    def request_target_position_selection(self):
        try:
            if hasattr(self, '_target_overlay') and self._target_overlay.winfo_exists():
                return
        except:
            pass
        try:
            screen_w = self.master.winfo_vrootwidth()
            screen_h = self.master.winfo_vrootheight()
            self._target_overlay = tk.Toplevel(self.master)
            self._target_overlay.overrideredirect(True)
            self._target_overlay.attributes('-alpha', 0.2)
            self._target_overlay.attributes('-topmost', True)
            self._target_overlay.geometry(f'{screen_w}x{screen_h}+0+0')
            self._target_overlay.configure(bg='black')
            label = tk.Label(self._target_overlay, text='追跡する場所をクリックしてください\nESCでキャンセル', bg='black', fg='white', font=('Arial', 18))
            label.place(relx=0.5, rely=0.5, anchor='center')
            self._target_overlay.bind('<Button-1>', self._on_target_position_selected)
            label.bind('<Button-1>', self._on_target_position_selected)
            self._target_overlay.bind('<Escape>', lambda e: self._cancel_target_position_selection())
            self._target_overlay.focus_force()
        except:
            pass

    def _on_target_position_selected(self, event):
        try:
            x = event.x_root
            y = event.y_root
            self.target_position = (x, y)
            self.settings['target_position'] = [x, y]
            self.settings['tracking_target_mode'] = 1
            self._update_target_status_labels()
            self.save_settings_file()
            self.broadcast_settings()
        except:
            pass
        self._cancel_target_position_selection()

    def _cancel_target_position_selection(self):
        try:
            if hasattr(self, '_target_overlay') and self._target_overlay.winfo_exists():
                self._target_overlay.destroy()
        except:
            pass

    def choose_target_image(self):
        try:
            filename = filedialog.askopenfilename(parent=self.master, title='追跡する画像を選択', filetypes=[('画像ファイル', '*.png;*.jpg;*.jpeg;*.bmp;*.gif'), ('すべて', '*.*')])
            if not filename:
                return
            template = self.load_image(filename)
            if template is None:
                raise Exception('invalid image')
            self.target_image_template = template
            self.target_image_path = filename
            self.settings['target_image_path'] = filename
            self.settings['tracking_target_mode'] = 2
            self.settings['target_position'] = None
            self.target_position = None
            self.target_image_last_search = 0.0
            self._search_target_image_on_screen(force=True)
            self._update_target_status_labels()
            self.save_settings_file()
            self.broadcast_settings()
        except Exception:
            try:
                messagebox.showerror('画像選択エラー', '指定したファイルを読み込めませんでした。')
            except:
                pass

    def _grab_screen(self):
        try:
            if ImageGrab is None:
                return None
            return ImageGrab.grab()
        except:
            return None

    def _search_target_image_on_screen(self, force=False):
        if self.target_image_template is None:
            return
        now = time.time()
        if not force and now - self.target_image_last_search < 2.0:
            return
        if self._target_image_search_in_progress:
            return
        self._target_image_search_in_progress = True
        self.target_image_last_search = now
        template = self.target_image_template.copy()
        def worker():
            result = None
            try:
                screen = self._grab_screen()
                if screen is not None:
                    result = self._find_template_on_screen(screen, template)
            except:
                result = None
            try:
                self.master.after(0, lambda: self._finish_target_image_search(result))
            except:
                self._target_image_search_in_progress = False
        threading.Thread(target=worker, daemon=True).start()

    def _finish_target_image_search(self, result):
        self._target_image_search_in_progress = False
        if result:
            x, y, score = result
            self.target_position = (x, y)
            self.settings['target_position'] = [x, y]
        else:
            self.target_position = None
            self.settings['target_position'] = None
        self._update_target_status_labels()

    def _find_template_on_screen(self, screen, template):
        try:
            screen_gray_full = screen.convert('L')
            screen_gray = screen_gray_full
            template_gray = template.convert('L')
            sw, sh = screen_gray.size
            tw, th = template_gray.size
            if tw > sw or th > sh:
                return None
            scale = 1.0
            if sw > 800 or sh > 800:
                scale = max(sw / 800.0, sh / 800.0)
                screen_gray = screen_gray.resize((max(1, int(sw / scale)), max(1, int(sh / scale))), Image.LANCZOS)
                template_gray = template_gray.resize((max(1, int(tw / scale)), max(1, int(th / scale))), Image.LANCZOS)
            tw2, th2 = template_gray.size
            if tw2 < 8 or th2 < 8:
                return None
            step = max(1, min(4, max(1, tw2 // 16), max(1, th2 // 16)))
            small_template = template_gray.resize((64, 64), Image.LANCZOS)
            best_score = None
            best_xy = None
            for y in range(0, screen_gray.height - th2 + 1, step):
                for x in range(0, screen_gray.width - tw2 + 1, step):
                    patch = screen_gray.crop((x, y, x + tw2, y + th2)).resize((64, 64), Image.LANCZOS)
                    diff = ImageChops.difference(patch, small_template)
                    score = sum(diff.getdata())
                    if best_score is None or score < best_score:
                        best_score = score
                        best_xy = (x, y)
            if best_xy is None:
                return None

            bx, by = best_xy
            refine_radius = max(8, step * 2)
            refined_score = best_score
            for y in range(max(0, by - refine_radius), min(screen_gray.height - th2, by + refine_radius) + 1):
                for x in range(max(0, bx - refine_radius), min(screen_gray.width - tw2, bx + refine_radius) + 1):
                    patch = screen_gray.crop((x, y, x + tw2, y + th2)).resize((64, 64), Image.LANCZOS)
                    diff = ImageChops.difference(patch, small_template)
                    score = sum(diff.getdata())
                    if score < refined_score:
                        refined_score = score
                        bx, by = x, y

            if scale > 1.0:
                orig_bx = min(sw - tw, int(bx * scale))
                orig_by = min(sh - th, int(by * scale))
                final_score = refined_score
                final_bx = orig_bx
                final_by = orig_by
                full_radius = max(16, int(scale * step * 2), 32)
                step2 = max(1, min(2, full_radius // 4))
                for y in range(max(0, orig_by - full_radius), min(sh - th, orig_by + full_radius) + 1, step2):
                    for x in range(max(0, orig_bx - full_radius), min(sw - tw, orig_bx + full_radius) + 1, step2):
                        patch = screen_gray_full.crop((x, y, x + tw, y + th)).resize((64, 64), Image.LANCZOS)
                        diff = ImageChops.difference(patch, small_template)
                        score = sum(diff.getdata())
                        if score < final_score:
                            final_score = score
                            final_bx = x
                            final_by = y
                bx, by = final_bx, final_by
                refined_score = final_score

            return int(bx + tw / 2), int(by + th / 2), refined_score
        except:
            return None

    def toggle_tracking_target_mode(self):
        try:
            mode = int(self.settings.get('tracking_target_mode', 0))
            for _ in range(3):
                mode = (mode + 1) % 3
                if mode == 1 and self.target_position is None:
                    continue
                if mode == 2 and self.target_image_template is None:
                    continue
                break
            if mode == 2 and self.target_image_template is None:
                mode = 0
            self.settings['tracking_target_mode'] = mode
            if mode == 2:
                self._search_target_image_on_screen(force=True)
            if mode == 0:
                self.settings['target_position'] = None
                self.target_position = None
            self._update_target_status_labels()
            self.save_settings_file()
            self.broadcast_settings()
        except:
            pass

    def clear_target_tracking(self):
        try:
            self.settings['tracking_target_mode'] = 0
            self.settings['target_position'] = None
            self.settings['target_image_path'] = None
            self.target_position = None
            self.target_image_path = None
            self.target_image_template = None
            self._target_image_search_in_progress = False
            self._update_target_status_labels()
            self.save_settings_file()
            self.broadcast_settings()
        except:
            pass

    # --- 編集ウィンドウ ---
    def open_edit_window(self, event=None):
        try:
            if hasattr(self, '_edit_win') and self._edit_win.winfo_exists():
                self._edit_win.lift()
                return
        except:
            pass

        self._edit_win = tk.Toplevel(self.master)
        self._edit_win.title("ひじき豆 - settings")
        try:
            self._edit_win.iconbitmap(resource_path('hijikimame_desktop.ico'))
        except:
            pass
        self._edit_win.attributes('-topmost', True)

        # 最上部: 操作ボタンフレーム (擬人化ボタンなど)
        try:
            top_btn_frame = tk.Frame(self._edit_win)
            top_btn_frame.pack(fill='x', pady=5)
            tk.Button(top_btn_frame, text="キャラ切替", command=self.toggle_mode).pack(side='left', padx=5)
            tk.Button(top_btn_frame, text="場所選択", command=self.request_target_position_selection).pack(side='left', padx=5)
            tk.Button(top_btn_frame, text="画像追跡設定", command=self.choose_target_image).pack(side='left', padx=5)
            tk.Button(top_btn_frame, text="追尾解除", command=self.clear_target_tracking).pack(side='left', padx=5)
        except:
            pass

        self._target_mode_label = tk.Label(self._edit_win, text=self._get_tracking_target_mode_display())
        self._target_mode_label.pack(anchor='w', padx=8, pady=2)
        self._target_status_label = tk.Label(self._edit_win, text=self._get_target_status_text())
        self._target_status_label.pack(anchor='w', padx=8, pady=2)

        # キャラクター選択
        char_frame = tk.LabelFrame(self._edit_win, text='キャラクター選択')
        char_frame.pack(fill='both', padx=8, pady=5, expand=True)
        char_canvas = tk.Canvas(char_frame, borderwidth=0, highlightthickness=0, height=200)
        char_scroll = tk.Scrollbar(char_frame, orient='vertical', command=char_canvas.yview)
        char_container = tk.Frame(char_canvas)
        char_container.bind('<Configure>', lambda e: char_canvas.configure(scrollregion=char_canvas.bbox('all')))
        char_canvas.create_window((0, 0), window=char_container, anchor='nw')
        char_canvas.configure(yscrollcommand=char_scroll.set)
        char_canvas.pack(side='left', fill='both', expand=True)
        char_scroll.pack(side='right', fill='y')

        self._character_buttons = {}
        mode_names = {
            0: '1. ひじき豆',
            1: '2. ろず',
            2: '3. たこ焼き',
            3: '4. 虹き豆',
            4: '5. オーバーローダーひじき豆'

        }
        for mi in range(5):
            btn = tk.Button(char_container, text=mode_names.get(mi, f'{mi+1}'), width=20,
                            command=lambda m=mi: self.set_mode(m))
            btn.pack(anchor='w', padx=4, pady=2)
            self._character_buttons[mi] = btn
        self._refresh_character_buttons()

        repulsion_var = tk.IntVar(value=1 if self.settings.get('mouse_repulsion_enabled', True) else 0)
        repulsion_cb = tk.Checkbutton(self._edit_win, text="ひじき豆の反発", variable=repulsion_var)
        repulsion_cb.pack(anchor='w', padx=8, pady=2)



        tk.Label(self._edit_win, text="追尾速度:").pack(anchor='w', padx=8)
        tracking_scale = tk.Scale(self._edit_win, from_=0.0, to=0.1, resolution=0.001, orient='horizontal')
        tracking_scale.set(self.settings.get('tracking_speed', TRACKING_SPEED))
        tracking_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="投げ速度倍率:").pack(anchor='w', padx=8)
        throw_scale = tk.Scale(self._edit_win, from_=0.1, to=10, resolution=0.1, orient='horizontal')
        throw_scale.set(self.settings.get('throw_speed_multiplier', 3.0))
        throw_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="投げ 最大倍率:").pack(anchor='w', padx=8)
        max_throw_scale = tk.Scale(self._edit_win, from_=1, to=50, orient='horizontal')
        max_throw_scale.set(self.settings.get('max_throw_multiplier', 15))
        max_throw_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="画面端バウンド回数:").pack(anchor='w', padx=8)
        bounce_scale = tk.Scale(self._edit_win, from_=0, to=20, orient='horizontal')
        bounce_scale.set(self.settings.get('edge_bounce_count', EDGE_BOUNCE_COUNT_DEFAULT))
        bounce_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="バウンド強さ:").pack(anchor='w', padx=8)
        bounce_strength_scale = tk.Scale(self._edit_win, from_=0.0, to=1.5, resolution=0.05, orient='horizontal')
        bounce_strength_scale.set(self.settings.get('edge_bounce_strength', EDGE_BOUNCE_STRENGTH))
        bounce_strength_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="虹き豆 再生速度 (FPS):").pack(anchor='w', padx=8)
        nijiki_scale = tk.Scale(self._edit_win, from_=1, to=60, orient='horizontal')
        nijiki_scale.set(self.settings.get('nijiki_fps', NIJIKI_DEFAULT_FPS))
        nijiki_scale.pack(fill='x', padx=8)

        def apply_settings():
            self.settings['nijiki_fps'] = int(nijiki_scale.get())
            self.settings['mouse_repulsion_enabled'] = bool(repulsion_var.get())
            self.settings['tracking_speed'] = float(tracking_scale.get())
            self.settings['throw_speed_multiplier'] = float(throw_scale.get())
            self.settings['max_throw_multiplier'] = float(max_throw_scale.get())
            self.settings['edge_bounce_count'] = int(bounce_scale.get())
            self.settings['edge_bounce_strength'] = float(bounce_strength_scale.get())
            if not self.is_dragging_stop and self.throw_cooldown == 0:
                self.remaining_bounces = self.settings.get('edge_bounce_count', EDGE_BOUNCE_COUNT_DEFAULT)
            try:
                self.save_settings_file()
            except:
                pass
            try:
                self.broadcast_settings()
            except:
                pass

        # 下部ボタンエリア
        bottom_frame = tk.Frame(self._edit_win)
        bottom_frame.pack(fill='x', padx=8, pady=10)

        # 初期化関数
        def reset_settings():
            self.settings['nijiki_fps'] = NIJIKI_DEFAULT_FPS
            self.settings['tracking_speed'] = TRACKING_SPEED
            self.settings['throw_speed_multiplier'] = 2.5
            self.settings['max_throw_multiplier'] = 10
            self.settings['edge_bounce_count'] = EDGE_BOUNCE_COUNT_DEFAULT
            self.settings['edge_bounce_strength'] = EDGE_BOUNCE_STRENGTH
            self.settings['mouse_repulsion_enabled'] = True
            self.settings['screen_boundary_mode'] = 'bounce'
            self.settings['selected_mode'] = 0
            self.settings['tracking_target_mode'] = 0
            self.settings['target_position'] = None
            self.settings['target_image_path'] = None
            self.target_position = None
            self.target_image_path = None
            self.target_image_template = None
            self.target_image_last_search = 0.0
            self._target_image_search_in_progress = False
            self.current_mode = 0
            nijiki_scale.set(NIJIKI_DEFAULT_FPS)
            tracking_scale.set(TRACKING_SPEED)
            throw_scale.set(2.5)
            max_throw_scale.set(10)
            bounce_scale.set(EDGE_BOUNCE_COUNT_DEFAULT)
            bounce_strength_scale.set(EDGE_BOUNCE_STRENGTH)
            repulsion_var.set(1)
            try:
                self._refresh_character_buttons()
            except:
                pass
            self.set_mode(0)
            self._update_target_status_labels()
            apply_settings()

        # ボタンを下に配置
        tk.Button(bottom_frame, text="初期化", command=reset_settings).pack(side='left', padx=2)
        tk.Button(bottom_frame, text="適用", command=apply_settings).pack(side='left', padx=2)
        self._update_button = tk.Button(bottom_frame, text="最新バージョンに揃える", bg="#8fbc8f", command=self._perform_update)
        if self._update_available:
            self._update_button.pack(side='right', padx=2)
        tk.Button(bottom_frame, text="閉じる", command=self._edit_win.destroy).pack(side='right', padx=2)
        tk.Button(bottom_frame, text="全て閉じる", bg="#ffcccb", command=self.close_all_instances).pack(side='right', padx=2)

        self.master.after(1500, self._poll_settings_file)

    def broadcast_settings(self):
        try:
            data = b'SETTINGS:' + json.dumps(self.settings).encode('utf-8')
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5); s.connect((HOST, PORT)); s.sendall(data)
        except:
            pass

    def apply_remote_settings(self, settings_dict):
        try:
            settings_dict = dict(settings_dict)
            if 'edit_enabled' in settings_dict:
                settings_dict.pop('edit_enabled', None)
            for k, v in settings_dict.items():
                self.settings[k] = v
            self.remaining_bounces = int(self.settings.get('edge_bounce_count', EDGE_BOUNCE_COUNT_DEFAULT))
        except:
            pass

    def _poll_settings_file(self):
        try:
            p = resource_path(SETTINGS_FILE)
            if os.path.exists(p):
                m = os.path.getmtime(p)
                if getattr(self, '_settings_mtime', None) is None or m != self._settings_mtime:
                    self._settings_mtime = m
                    cfg = self.load_settings_file()
                    if isinstance(cfg, dict):
                        self.apply_remote_settings(cfg)
        except:
            pass
        if not self.is_exiting:
            self.master.after(1500, self._poll_settings_file)

    def save_settings_file(self):
        try:
            settings_to_save = dict(self.settings)
            if 'edit_enabled' in settings_to_save:
                settings_to_save.pop('edit_enabled', None)
            with open(resource_path(SETTINGS_FILE), 'w', encoding='utf-8') as f:
                json.dump(settings_to_save, f, ensure_ascii=False, indent=2)
        except:
            pass

    def load_settings_file(self):
        try:
            p = resource_path(SETTINGS_FILE)
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            return None
        return None

    def start_drag_stop(self, event):
        if event.num == 1:
            self.is_dragging_stop = True; self.vx = 0; self.vy = 0; self.throw_cooldown = 0 
            self.last_mouse_x = self.master.winfo_pointerx()
            self.last_mouse_y = self.master.winfo_pointery()
            self.drag_vx = 0; self.drag_vy = 0
            self.canvas.bind("<B1-Motion>", self.do_move)

    def stop_drag_stop(self, event):
        if event.num == 1:
            self.is_dragging_stop = False
            mouse_speed = math.hypot(self.drag_vx, self.drag_vy)
            dynamic_multiplier = min(mouse_speed * self.settings.get('throw_speed_multiplier', 2.5), self.settings.get('max_throw_multiplier', 10))
            self.vx = self.drag_vx * dynamic_multiplier
            self.vy = self.drag_vy * dynamic_multiplier
            # 保存: 投擲直後の初速（エッジ衝突時の最小反射力算出に使う）
            try:
                self._last_throw_velocity = (self.vx, self.vy)
            except:
                self._last_throw_velocity = (0, 0)
            self.throw_cooldown = THROW_COOLDOWN_FRAMES
            self.remaining_bounces = self.settings.get('edge_bounce_count', EDGE_BOUNCE_COUNT_DEFAULT)
            self.drag_vx = 0; self.drag_vy = 0
            self.canvas.unbind("<B1-Motion>")

    def do_move(self, event):
        if self.is_dragging_stop:
            current_x = self.master.winfo_pointerx()
            current_y = self.master.winfo_pointery()
            self.drag_vx = current_x - self.last_mouse_x
            self.drag_vy = current_y - self.last_mouse_y
            self.last_mouse_x = current_x; self.last_mouse_y = current_y
            self.update_eyes_only()

    def update_eyes_only(self):
        mouse_x = self.master.winfo_pointerx()
        mouse_y = self.master.winfo_pointery()
        char_center_x = self.x + self.image_width // 2
        char_center_y = self.y + self.image_height // 2
        dx = mouse_x - char_center_x; dy = mouse_y - char_center_y
        dist = math.hypot(dx, dy)
        if dist != 0: dx_u, dy_u = dx / dist, dy / dist
        else: dx_u, dy_u = 0, 0
        move_dist = min(dist * 0.1, EYE_MOVEMENT_LIMIT)
        move_x, move_y = dx_u * move_dist, dy_u * move_dist
        bx, by = self.image_width // 2, self.image_height // 2
        lx, ly = bx - EYE_OFFSET_X + move_x, by + EYE_OFFSET_Y + move_y
        rx, ry = bx + EYE_OFFSET_X + move_x, by + EYE_OFFSET_Y + move_y
        self.canvas.coords(self.eye_left_id, lx-EYE_RADIUS, ly-EYE_RADIUS, lx+EYE_RADIUS, ly+EYE_RADIUS)
        self.canvas.coords(self.eye_right_id, rx-EYE_RADIUS, ry-EYE_RADIUS, rx+EYE_RADIUS, ry+EYE_RADIUS)

    def update_position(self):
        if self.is_exiting: return
        mouse_x = self.master.winfo_pointerx()
        mouse_y = self.master.winfo_pointery()
        mouse_vx = mouse_x - self.last_mouse_x
        mouse_vy = mouse_y - self.last_mouse_y
        mouse_speed = math.hypot(mouse_vx, mouse_vy)
        # compute mouse acceleration using previous frame velocity
        prev_vx = getattr(self, '_last_mouse_vx', 0)
        prev_vy = getattr(self, '_last_mouse_vy', 0)
        mouse_ax = mouse_vx - prev_vx
        mouse_ay = mouse_vy - prev_vy
        mouse_a_mag = math.hypot(mouse_ax, mouse_ay)

        target_mode = int(self.settings.get('tracking_target_mode', 0))
        if target_mode == 2:
            if self.target_image_template:
                self._search_target_image_on_screen()
            else:
                target_mode = 0
                self.settings['tracking_target_mode'] = 0
        if target_mode == 1 and self.target_position:
            target_x, target_y = self.target_position
        elif target_mode == 2 and self.target_position:
            target_x, target_y = self.target_position
        else:
            target_x, target_y = mouse_x, mouse_y

        char_center_x = self.x + self.image_width // 2
        char_center_y = self.y + self.image_height // 2
        dx_char = target_x - char_center_x; dy_char = target_y - char_center_y
        distance = math.hypot(dx_char, dy_char)
        touch_margin = max(16, min(self.image_width, self.image_height) // 6)
        is_mouse_over_char = (self.x - touch_margin <= mouse_x <= self.x + self.image_width + touch_margin and
                               self.y - touch_margin <= mouse_y <= self.y + self.image_height + touch_margin)

        # If the user is holding the character, follow cursor as before
        if self.is_dragging_stop:
            self.x = mouse_x - (self.image_width // 2)
            self.y = mouse_y - (self.image_height // 2)
            self.vx = 0; self.vy = 0
        else:
            repulsion_enabled = self.settings.get('mouse_repulsion_enabled', True)
            # Detect sudden cursor acceleration and convert to an impulse throw
            try:
                if repulsion_enabled and is_mouse_over_char and mouse_a_mag >= MOUSE_ACCELERATION_THROW_THRESHOLD:
                    self.vx = mouse_ax * MOUSE_ACCELERATION_THROW_MULTIPLIER
                    self.vy = mouse_ay * MOUSE_ACCELERATION_THROW_MULTIPLIER
                    self.throw_cooldown = THROW_COOLDOWN_FRAMES
                    self.remaining_bounces = self.settings.get('edge_bounce_count', EDGE_BOUNCE_COUNT_DEFAULT)
                    self._last_throw_velocity = (self.vx, self.vy)
            except Exception:
                pass

            # if in throw cooldown, continue coasting with decay
            if self.throw_cooldown > 0:
                self.throw_cooldown -= 1; self.vx *= 0.92; self.vy *= 0.92
                self.x += self.vx; self.y += self.vy
            else:
                repulsion_enabled = self.settings.get('mouse_repulsion_enabled', True)
                if repulsion_enabled and is_mouse_over_char:
                    actual_bounce_force = max(20, mouse_speed * BOUNCE_STRENGTH, 80.0 / max(distance, 1.0))
                    if distance != 0:
                        nx = dx_char / distance
                        ny = dy_char / distance
                        self.vx = -nx * actual_bounce_force
                        self.vy = -ny * actual_bounce_force
                        push_back = max(self.image_width, self.image_height) * 0.25
                        self.x -= nx * push_back
                        self.y -= ny * push_back
                    else:
                        angle = random.uniform(0, 2 * math.pi)
                        self.vx = math.cos(angle) * actual_bounce_force
                        self.vy = math.sin(angle) * actual_bounce_force
                else:
                    track_speed = float(self.settings.get('tracking_speed', TRACKING_SPEED))
                    self.vx = (self.vx + dx_char * track_speed) * 0.85
                    self.vy = (self.vy + dy_char * track_speed) * 0.85
                self.x += self.vx; self.y += self.vy

        # remember last mouse velocity and position for next-frame accel calculation
        self._last_mouse_vx = mouse_vx
        self._last_mouse_vy = mouse_vy
        self.last_mouse_x = mouse_x; self.last_mouse_y = mouse_y

        screen_w = self.master.winfo_vrootwidth()
        screen_h = self.master.winfo_vrootheight()
        strg = self.settings.get('edge_bounce_strength', EDGE_BOUNCE_STRENGTH)
        # cap to avoid extremely large velocities after reflection
        max_cap = max(screen_w, screen_h) * 0.6
        boundary_mode = self.settings.get('screen_boundary_mode', 'bounce')
        # X axis edge handling
        if self.x < 0 or self.x > screen_w - self.image_width:
            self.x = max(0, min(self.x, screen_w - self.image_width))
            if boundary_mode == 'bounce':
                if self.throw_cooldown > 0:
                    # reflect velocity and apply strength; do not consume remaining_bounces here
                    self.vx = -self.vx * float(strg)
                    # if velocity is very small (damped), use last throw velocity to ensure a noticeable bounce
                    try:
                        lvx = getattr(self, '_last_throw_velocity', (0, 0))[0]
                    except:
                        lvx = 0
                    if abs(self.vx) < 2 and abs(lvx) > 0:
                        self.vx = -math.copysign(max(10, abs(lvx) * float(strg)), lvx)
                    # clamp magnitude
                    if self.vx > max_cap: self.vx = max_cap
                    if self.vx < -max_cap: self.vx = -max_cap
                elif self.remaining_bounces > 0:
                    self.vx *= -float(strg)
                    self.remaining_bounces -= 1
                    if self.vx > max_cap: self.vx = max_cap
                    if self.vx < -max_cap: self.vx = -max_cap
                else:
                    self.vx = 0
            else:  # stop
                self.vx = 0

        # Y axis edge handling (same rules)
        if self.y < 0 or self.y > screen_h - self.image_height:
            self.y = max(0, min(self.y, screen_h - self.image_height))
            if boundary_mode == 'bounce':
                if self.throw_cooldown > 0:
                    self.vy = -self.vy * float(strg)
                    try:
                        lvy = getattr(self, '_last_throw_velocity', (0, 0))[1]
                    except:
                        lvy = 0
                    if abs(self.vy) < 2 and abs(lvy) > 0:
                        self.vy = -math.copysign(max(10, abs(lvy) * float(strg)), lvy)
                    if self.vy > max_cap: self.vy = max_cap
                    if self.vy < -max_cap: self.vy = -max_cap
                elif self.remaining_bounces > 0:
                    self.vy *= -float(strg)
                    self.remaining_bounces -= 1
                    if self.vy > max_cap: self.vy = max_cap
                    if self.vy < -max_cap: self.vy = -max_cap
                else:
                    self.vy = 0
            else:  # stop
                self.vy = 0

        if self.current_mode == 3 and self.nijiki_indices:
            fps = max(1, int(self.settings.get('nijiki_fps', NIJIKI_DEFAULT_FPS)))
            if time.time() - self.nijiki_last_frame_time >= (1.0 / fps):
                self.nijiki_frame_index = (self.nijiki_frame_index + 1) % len(self.nijiki_indices)
                f = self.nijiki_cache.get(self.nijiki_indices[self.nijiki_frame_index])
                if f: self.canvas.itemconfig(self.character_id, image=f)
                self.nijiki_last_frame_time = time.time()

        self.master.geometry(f"+{int(self.x)}+{int(self.y)}"); self.update_eyes_only()
        if not self.is_exiting:
            self.master.after(UPDATE_INTERVAL, self.update_position)

    def start_exit_animation(self):
        if self.is_exiting: return 
        if not self.exit_frames:
            self.master.destroy(); return
        self.is_exiting = True
        self.canvas.itemconfigure(self.eye_left_id, state='hidden')
        self.canvas.itemconfigure(self.eye_right_id, state='hidden')
        # prepare a fully transparent final frame to avoid residual-pixel artifacts
        try:
            self._transparent_frame = ImageTk.PhotoImage(Image.new('RGBA', (self.image_width, self.image_height), (0,0,0,0)))
        except Exception:
            self._transparent_frame = None
        self.play_exit_frame()

    def play_exit_frame(self):
        if self.current_frame_index < len(self.exit_frames):
            self.canvas.itemconfig(self.character_id, image=self.exit_frames[self.current_frame_index])
            self.current_frame_index += 1; self.master.after(20, self.play_exit_frame)
        else:
            # Try an aggressive clear: set window alpha to fully transparent and delete the canvas item
            try:
                try:
                    self.master.wm_attributes('-alpha', 0.0)
                except:
                    pass
                try:
                    self.canvas.delete(self.character_id)
                except:
                    pass
                try:
                    self.master.update_idletasks()
                except:
                    pass
            except:
                pass
            # Short delay to ensure the GUI updates before destroying
            try:
                self.master.after(10, lambda: self.master.destroy())
            except:
                self.master.destroy()

if __name__ == "__main__":
    # 自己置換フロー（ダウンロードした新しい exe が起動されたときの処理）
    if '--self-replace' in sys.argv:
        try:
            idx = sys.argv.index('--self-replace')
            target_path = sys.argv[idx+1] if len(sys.argv) > idx+1 else None
            if target_path:
                _self_replace_target(target_path)
        except Exception:
            pass
        sys.exit(0)

    # 通常起動時は更新チェックを実行（フロー開始 -> 必要ならダウンロードして置換プロセスを起動し、現在プロセスは終了する）
    root = tk.Tk()
    app = HijikimameApp(root)
    root.mainloop()
