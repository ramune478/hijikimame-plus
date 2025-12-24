import tkinter as tk
from PIL import Image, ImageTk
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

# アプリバージョン（リリースタグと一致させてください、例: "v1.2.3"）
VERSION = "v1.0.0"


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


def _check_and_initiate_update():
    """GitHub Releases を確認して、更新があればダウンロード→自己置換フローを開始する。

    環境変数 `GITHUB_OWNER` と `GITHUB_REPO` を必須とし、プライベートの場合は
    `GITHUB_UPDATE_TOKEN` または `GITHUB_TOKEN` を利用してください。
    """
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
        master.overrideredirect(True)
        master.wm_attributes("-transparentcolor", TRANSPARENT_COLOR) 

        self.settings = {
            'edit_enabled': {0: True, 1: True, 2: True, 3: True},
            'nijiki_fps': NIJIKI_DEFAULT_FPS,
            'nijiki_cache_size': NIJIKI_CACHE_SIZE_DEFAULT,
            'nijiki_max_frames': NIJIKI_MAX_FRAMES_DEFAULT,
            'tracking_speed': TRACKING_SPEED,
            'throw_speed_multiplier': 2.5,  
            'max_throw_multiplier': 10,
            'edge_bounce_count': EDGE_BOUNCE_COUNT_DEFAULT,
            'edge_bounce_strength': EDGE_BOUNCE_STRENGTH,
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

        self.original_image_path = resource_path("hijikimame_body.png") 
        self.original_image = self.load_image(self.original_image_path)
        self.takoyaki_image_path = resource_path(TAKOYAKI_IMAGE_PATH)
        self.takoyaki_image = self.load_image(self.takoyaki_image_path)
        
        if self.original_image is None:
            master.destroy()
            return
            
        self.image_width, self.image_height = self.original_image.size
        self.tk_image = ImageTk.PhotoImage(self.original_image)

        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
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

        self.update_position()
        
        self.canvas.bind("<Button-1>", self.start_drag_stop)
        self.canvas.bind("<ButtonRelease-1>", self.stop_drag_stop)
        self.canvas.bind("<Button-3>", self.open_edit_window)
        
        self.master.bind("<Control-h>", lambda e: self.start_exit_animation())
        self.master.bind("<Control-r>", lambda e: self.toggle_mode()) 
        
        self.master.after(100, self._check_ipc_command)
        try:
            self.master.after(200, lambda: self.open_edit_window())
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

    def toggle_mode(self): 
        if self.is_exiting: return
        ef = self.settings.get('edit_enabled', {0: True, 1: True, 2: True, 3: True})
        next_mode = (self.current_mode + 1) % 4
        if isinstance(ef, dict):
            allowed = ef.get(next_mode, True)
        else:
            allowed = bool(ef)
        if not allowed:
            return
        self.current_mode = next_mode
        
        should_update_image = True
        new_image = self.original_image
        new_eye_color = DEFAULT_EYE_COLOR
        self.is_inverted = False 

        if self.current_mode == 0: pass 
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
        self._edit_win.attributes('-topmost', True)

        # 最上部: 操作ボタンフレーム (擬人化ボタンなど)
        try:
            top_btn_frame = tk.Frame(self._edit_win)
            top_btn_frame.pack(fill='x', pady=5)
            tk.Button(top_btn_frame, text="モード切替", command=self.toggle_mode).pack(side='left', padx=5)
        except:
            pass

        # 各モードごとの編集有効フラグ
        mode_names = {0: 'ひじき豆', 1: 'ろず', 2: 'たこ焼き', 3: '虹き豆'}
        edit_vars = {}
        current_flags = self.settings.get('edit_enabled', {0: True, 1: True, 2: True, 3: True})
        for mi in range(4):
            if isinstance(current_flags, dict):
                val = 1 if current_flags.get(mi, True) else 0
            else:
                val = 1 if bool(current_flags) else 0
            iv = tk.IntVar(value=val)
            edit_vars[mi] = iv
            def make_cb(i, v):
                return tk.Checkbutton(self._edit_win, text=f"{mode_names[i]} に変更可能", variable=v)
            cb = make_cb(mi, iv)
            cb.pack(anchor='w', padx=8, pady=2)

        tk.Label(self._edit_win, text="マウスカーソルの追従速度:").pack(anchor='w', padx=8)
        tracking_scale = tk.Scale(self._edit_win, from_=0.001, to=0.1, resolution=0.001, orient='horizontal')
        tracking_scale.set(self.settings.get('tracking_speed', TRACKING_SPEED))
        tracking_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="投げ速度倍率:").pack(anchor='w', padx=8)
        throw_scale = tk.Scale(self._edit_win, from_=0.1, to=10, resolution=0.1, orient='horizontal')
        throw_scale.set(self.settings.get('throw_speed_multiplier', 2.5))
        throw_scale.pack(fill='x', padx=8)

        tk.Label(self._edit_win, text="投げ 最大倍率:").pack(anchor='w', padx=8)
        max_throw_scale = tk.Scale(self._edit_win, from_=1, to=50, orient='horizontal')
        max_throw_scale.set(self.settings.get('max_throw_multiplier', 10))
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
            try:
                edit_dict = {}
                for mi, iv in edit_vars.items():
                    edit_dict[int(mi)] = bool(iv.get())
                self.settings['edit_enabled'] = edit_dict
            except:
                pass
            self.settings['nijiki_fps'] = int(nijiki_scale.get())
            self.settings['tracking_speed'] = float(tracking_scale.get())
            self.settings['throw_speed_multiplier'] = float(throw_scale.get())
            self.settings['max_throw_multiplier'] = float(max_throw_scale.get())
            self.settings['edge_bounce_count'] = int(bounce_scale.get())
            self.settings['edge_bounce_strength'] = float(bounce_strength_scale.get())
            if not self.is_dragging_stop and self.throw_cooldown == 0:
                self.remaining_bounces = self.settings.get('edge_bounce_count', EDGE_BOUNCE_COUNT_DEFAULT)
            try: self.save_settings_file()
            except: pass
            try: self.broadcast_settings()
            except: pass

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
            self.settings['edit_enabled'] = {0: True, 1: True, 2: True, 3: True}
            nijiki_scale.set(NIJIKI_DEFAULT_FPS)
            tracking_scale.set(TRACKING_SPEED)
            throw_scale.set(2.5)
            max_throw_scale.set(10)
            bounce_scale.set(EDGE_BOUNCE_COUNT_DEFAULT)
            bounce_strength_scale.set(EDGE_BOUNCE_STRENGTH)
            for mi, iv in edit_vars.items(): iv.set(1)
            apply_settings()

        # ボタンを下に配置
        tk.Button(bottom_frame, text="初期化", command=reset_settings).pack(side='left', padx=2)
        tk.Button(bottom_frame, text="適用", command=apply_settings).pack(side='left', padx=2)
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
            with open(resource_path(SETTINGS_FILE), 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
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

        char_center_x = self.x + self.image_width // 2
        char_center_y = self.y + self.image_height // 2
        dx_char = mouse_x - char_center_x; dy_char = mouse_y - char_center_y
        distance = math.hypot(dx_char, dy_char)

        # If the user is holding the character, follow cursor as before
        if self.is_dragging_stop:
            self.x = mouse_x - (self.image_width // 2)
            self.y = mouse_y - (self.image_height // 2)
            self.vx = 0; self.vy = 0
        else:
            # Detect sudden cursor acceleration and convert to an impulse throw
            try:
                # only trigger mouse-acceleration throw when cursor is near the character
                current_collision_distance = COLLISION_DISTANCE_BASE + (mouse_speed * COLLISION_EXPANSION_RATE)
                if mouse_a_mag >= MOUSE_ACCELERATION_THROW_THRESHOLD and distance < current_collision_distance:
                    # apply throw impulse from cursor acceleration
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
                current_collision_distance = COLLISION_DISTANCE_BASE + (mouse_speed * COLLISION_EXPANSION_RATE)
                if distance < current_collision_distance:
                    actual_bounce_force = max(10, mouse_speed * BOUNCE_STRENGTH)
                    if distance != 0:
                        self.vx = -(dx_char / distance) * actual_bounce_force
                        self.vy = -(dy_char / distance) * actual_bounce_force
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

        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()
        strg = self.settings.get('edge_bounce_strength', EDGE_BOUNCE_STRENGTH)
        # cap to avoid extremely large velocities after reflection
        max_cap = max(screen_w, screen_h) * 0.6
        # X axis edge handling: when thrown (throw_cooldown>0) always bounce irrespective of remaining_bounces
        if self.x < 0 or self.x > screen_w - self.image_width:
            self.x = max(0, min(self.x, screen_w - self.image_width))
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

        # Y axis edge handling (same rules)
        if self.y < 0 or self.y > screen_h - self.image_height:
            self.y = max(0, min(self.y, screen_h - self.image_height))
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
    try:
        _check_and_initiate_update()
    except Exception:
        pass

    root = tk.Tk()
    app = HijikimameApp(root)
    root.mainloop()