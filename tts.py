"""TTS 引擎層。

對上：統一的 Engine 介面（朗讀、列語音、停止）。
對下：處理各平台細節（macOS say / edge-tts + 各系統播放器）。

`Speaker` 負責跨引擎的會話邏輯（停止競態），引擎本身只管「唸出聲、阻塞到完」。
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

# ---------- 共用：子行程管理 ----------

class Engine:
    """引擎介面。speak() 必須阻塞到唸完或被 stop() 打斷。"""

    id = ""
    label = ""
    needs_network = False

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None

    # --- 子行程（供各引擎使用） ---
    def _spawn(self, argv):
        with self._lock:
            self._kill_locked()
            self._proc = subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return self._proc

    def _kill_locked(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

    def stop(self):
        with self._lock:
            self._kill_locked()

    def _wait(self, proc):
        while True:
            try:
                proc.wait(timeout=0.05)
                return
            except subprocess.TimeoutExpired:
                continue

    # --- 引擎要實作的介面 ---
    def voices(self):
        raise NotImplementedError

    def speak(self, text, multiplier, voice):
        raise NotImplementedError


# ---------- 引擎 1：macOS say（離線） ----------

# `say -v ?` 每行格式： "Name (Description) zh_CN    # 範例文字"
# → 語言代碼在行中而非行尾（行尾是範例文字），必須掃描整行。
SAY_LOCALE = re.compile(r"^[a-z]{2,3}[_-][A-Z]{2}$")
# 已下載語言包的檔名： com.apple.voice.enhanced.zh-CN.Tingting.caf
SAY_ASSET = re.compile(r"^com\.apple\.voice\..*?\.([a-z]{2,3}-[A-Z]{2})\.([A-Za-z]+)\.caf$")

SAY_ACCENT = {
    "zh-CN": "普通話・中國大陸",
    "zh-TW": "國語・台灣",
    "zh-HK": "粵語・香港",
}

SAY_BASE_RATE = 200        # say -r 的基準（字/分鐘）
SAY_RATE_MIN, SAY_RATE_MAX = 100, 400


def _scan(path):
    """os.scandir 但吞掉權限錯誤（/System 底下有唔少目錄讀唔到）。"""
    try:
        return list(os.scandir(path))
    except OSError:
        return []


def _say_voice_data():
    """掃描系統實際安裝的語音資料 → {locale: {名稱}}。約 0.01s，無需出聲。"""
    data = {}
    for fw in _scan("/System/Library/PrivateFrameworks"):
        if not fw.name.startswith("TextToSpeechMauiSupport"):
            continue
        for ver in _scan(os.path.join(fw.path, "Versions")):
            for loc in _scan(os.path.join(ver.path, "Resources", "TTSResources")):
                if loc.is_dir():
                    for v in _scan(loc.path):
                        data.setdefault(loc.name, set()).add(v.name)
    for root in ("/System/Library/AssetsV2",
                 "/System/Volumes/Data/System/Library/AssetsV2"):
        for cat in _scan(root):
            if not cat.is_dir(follow_symlinks=False):
                continue
            for asset in _scan(cat.path):
                if not asset.name.endswith(".asset"):
                    continue
                for f in _scan(os.path.join(asset.path, "AssetData", "Contents")):
                    m = SAY_ASSET.match(f.name)
                    if m:
                        data.setdefault(m.group(1), set()).add(m.group(2))
    return data


class MacSayEngine(Engine):
    id = "say"
    label = "macOS 系統語音"
    needs_network = False

    def __init__(self):
        super().__init__()
        self._cache = None

    def available(self):
        return sys.platform == "darwin" and shutil.which("say") is not None

    def voices(self):
        if self._cache is not None:
            return self._cache
        claimed = []  # say 宣稱支援中文的語音
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True,
                                 text=True, timeout=5).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                for token in parts:
                    if SAY_LOCALE.match(token) and token[:2].lower() == "zh":
                        claimed.append((parts[0], token.replace("_", "-")))
                        break
        except Exception:
            pass

        data = _say_voice_data()
        usable = [(n, loc) for n, loc in claimed if n in data.get(loc, ())]
        # 掃不到資料就退回宣稱清單，寧願多列也好過冇聲
        voices = usable or list(dict.fromkeys(claimed))
        voices.sort(key=lambda p: (SAY_ACCENT.get(p[1], p[1]) != "普通話・中國大陸", p[1], p[0]))
        voices = list(dict.fromkeys(voices))
        self._cache = [{"value": n, "label": f"{SAY_ACCENT.get(loc, loc)} · {n}"}
                       for n, loc in voices]
        return self._cache

    def speak(self, text, multiplier, voice):
        rate = max(SAY_RATE_MIN, min(SAY_RATE_MAX, int(SAY_BASE_RATE * multiplier)))
        self._wait(self._spawn(["say", "-v", voice, "-r", str(rate), text]))


# ---------- 引擎 2：edge-tts（全平台，音色最好，需網絡） ----------

EDGE_NAMES = {
    "Xiaoxiao": "曉曉", "Xiaoyi": "曉伊", "Yunjian": "雲健", "Yunxi": "雲希",
    "Yunxia": "雲夏", "Yunyang": "雲揚", "Xiaobei": "曉蓓", "Xiaoni": "曉妮",
    "HsiaoChen": "曉臻", "HsiaoYu": "曉雨", "YunJhe": "雲哲",
    "HiuGaai": "曉佳", "HiuMaan": "曉曼", "WanLung": "雲龍",
}
EDGE_ACCENT = {
    "zh-CN": "普通話",
    "zh-CN-liaoning": "東北官話",
    "zh-CN-shaanxi": "陝西話",
    "zh-TW": "台灣國語",
    "zh-HK": "粵語",
}
EDGE_PREFERRED = ("zh-CN", "zh-CN-liaoning", "zh-CN-shaanxi", "zh-TW", "zh-HK")

# 各系統的 mp3 播放器，依序嘗試
PLAYERS = [
    ["afplay", "{path}"],                              # macOS 內建
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "{path}"],
    ["mpg123", "-q", "{path}"],
    ["paplay", "{path}"],
    ["aplay", "-q", "{path}"],
]


def find_player():
    for tmpl in PLAYERS:
        if shutil.which(tmpl[0]):
            return tmpl
    return None


def edge_installed():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


class EdgeEngine(Engine):
    id = "edge"
    label = "edge-tts（音色較自然，需網絡）"
    needs_network = True

    def available(self):
        return edge_installed() and find_player() is not None

    def unavailable_reason(self):
        if not edge_installed():
            return "未安裝 edge-tts（pip install edge-tts）"
        return "找不到 mp3 播放器（afplay / ffplay / mpg123）"

    def voices(self):
        import asyncio
        import edge_tts

        async def load():
            out = []
            for v in await edge_tts.list_voices():
                loc = v.get("Locale", "")
                if not loc.startswith("zh"):
                    continue
                short = v["ShortName"]
                m = re.search(r"-([A-Za-z]+)Neural$", short)
                key = m.group(1) if m else short
                name = EDGE_NAMES.get(key, short)
                gender = "女聲" if v.get("Gender", "").lower().startswith("f") else "男聲"
                accent = EDGE_ACCENT.get(loc, loc)
                out.append({"value": short, "label": f"{name} · {gender} · {accent}"})
            out.sort(key=lambda d: (EDGE_PREFERRED.index(d["value"][:5])
                                    if d["value"][:5] in EDGE_PREFERRED else 9, d["label"]))
            return out

        return asyncio.run(load())

    def speak(self, text, multiplier, voice):
        import asyncio
        import edge_tts

        # 倍率 → 語速百分比：0.5× = -50%，2.0× = +100%
        pct = round((multiplier - 1) * 100)

        async def synth(path):
            await edge_tts.Communicate(text, voice, rate=f"{pct:+d}%").save(path)

        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        try:
            asyncio.run(synth(path))
            if os.path.getsize(path) < 512:
                raise RuntimeError("edge-tts 沒有產生音訊（可能無網絡）")
            player = find_player()
            if not player:
                raise RuntimeError(self.unavailable_reason())
            self._wait(self._spawn([a.replace("{path}", path) for a in player]))
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


# ---------- 引擎註冊表 ----------

ENGINES = {e.id: e for e in (MacSayEngine(), EdgeEngine())}
DEFAULT_VOICE = "Tingting"          # macOS 預設；其他平台的第一個音色
DEFAULT_ENGINE = "say" if sys.platform == "darwin" else "edge"


def get_engine(eid):
    return ENGINES.get(eid or DEFAULT_ENGINE)


def engine_list():
    out = []
    for e in ENGINES.values():
        ok = e.available()
        item = {"id": e.id, "label": e.label, "available": ok,
                "needs_network": e.needs_network}
        if not ok and hasattr(e, "unavailable_reason"):
            item["reason"] = e.unavailable_reason()
        out.append(item)
    return out


# ---------- 會話層：處理停止競態 ----------

class Speaker:
    """跨引擎的朗讀會話。保證「停止」不會在 start/stop 的競態中遺失。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._engine = None
        self._gen = 0

    def set_engine(self, engine):
        with self._lock:
            if self._engine is not None and self._engine is not engine:
                self._engine.stop()
            self._engine = engine

    def stop(self):
        with self._lock:
            self._gen += 1
            if self._engine is not None:
                self._engine.stop()
        return {"ok": True}

    def speak(self, text, rate, voice):
        if not text:
            return {"ok": False, "reason": "empty"}
        with self._lock:
            engine = self._engine
            if engine is not None:
                engine.stop()          # 殺掉上一句，避免疊音
            my_gen = self._gen
        if engine is None:
            return {"ok": False, "reason": "no_engine"}
        try:
            engine.speak(text, rate, voice)
        except Exception as exc:
            return {"ok": False, "reason": "error", "detail": str(exc)}
        if self._gen != my_gen:
            return {"ok": False, "reason": "stopped"}
        return {"ok": True}
