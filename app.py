#!/usr/bin/env python3
"""中文文字閱讀器 — Flask 後端。

同步設計：/api/speak 會「阻塞到語音引擎讀完」才回 response，
所以「收到 response」≡「這句讀完了」。前端因此不需要 SSE / WebSocket，
進度與高亮都是本地狀態，不會錯位。
"""

import socket
import subprocess
import threading
import time
import webbrowser

from flask import Flask, jsonify, render_template, request

import tts

app = Flask(__name__)

# macOS AirPlay Receiver（ControlCenter）長期霸住 5000 / 7000。
# 用呢啲 port 開 server，瀏覽器有機會收埋 AirTunes 個 403
# （「Access to 127.0.0.1 was denied」），睇落好似自己個 app 出錯。
AIRPLAY_PORTS = (5000, 7000)

# ---------- 繁簡轉換（可選依賴，缺了自動降級為不轉換） ----------

try:
    from opencc import OpenCC

    _CC = {"s2t": OpenCC("s2t"), "t2s": OpenCC("t2s")}
except Exception:  # pragma: no cover
    _CC = {}


def convert(text, mode):
    cc = _CC.get(mode)
    return cc.convert(text) if cc else text


speaker = tts.Speaker()


# ---------- Routes ----------

@app.get("/")
def index():
    engines = tts.engine_list()
    default_engine = tts.DEFAULT_ENGINE
    return render_template(
        "index.html",
        engine_options=[
            {"value": e["id"], "label": e["label"], "selected": e["id"] == default_engine,
             "disabled": not e["available"], "reason": e.get("reason", "")}
            for e in engines
        ],
        opencc_available=bool(_CC),
    )


@app.get("/api/engines")
def api_engines():
    return jsonify({"engines": tts.engine_list(), "default": tts.DEFAULT_ENGINE})


@app.get("/api/voices")
def api_voices():
    engine_id = request.args.get("engine", tts.DEFAULT_ENGINE)
    engine = tts.get_engine(engine_id)
    if engine is None or not engine.available():
        return jsonify({"voices": [], "error": "引擎不可用"})
    try:
        return jsonify({"voices": engine.voices()})
    except Exception as exc:
        return jsonify({"voices": [], "error": str(exc)})


@app.post("/api/split")
def api_split():
    from splitter import split_sentences

    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    mode = data.get("convert")  # "s2t" | "t2s" | None
    if mode:
        text = convert(text, mode)
    return jsonify({"sentences": split_sentences(text)})


@app.post("/api/speak")
def api_speak():
    data = request.get_json(silent=True) or {}
    engine = tts.get_engine(data.get("engine"))
    if engine is None:
        return jsonify({"ok": False, "reason": "no_engine"})
    if not engine.available():
        reason = getattr(engine, "unavailable_reason", lambda: "引擎不可用")()
        return jsonify({"ok": False, "reason": "unavailable", "detail": reason})
    speaker.set_engine(engine)
    return jsonify(speaker.speak(
        data.get("text", ""),
        float(data.get("multiplier", 1.0)),
        str(data.get("voice") or tts.DEFAULT_VOICE),
    ))


@app.post("/api/stop")
def api_stop():
    return jsonify(speaker.stop())


@app.get("/api/health")
def api_health():
    return jsonify(
        {
            "engines": tts.engine_list(),
            "default_engine": tts.DEFAULT_ENGINE,
            "opencc": bool(_CC),
            "say": bool(subprocess.run(["which", "say"], capture_output=True).stdout),
        }
    )


def open_browser_when_ready(url, port, timeout=10.0):
    """等 server 真正開始接受連線才開瀏覽器。

    Flask 要到 app.run() 才 bind port。若用固定 sleep，慢機／首次 uv sync 之後
    可能開出「無法連上」的頁面（同 README 講嘅 AirTunes 403 一樣易誤會）。
    改用 TCP 探測：連得上就代表 server 已在監聽。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.1)
    # 時限內起唔到（例如 port 被佔用）就不開，避免開出錯誤頁


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
    url = f"http://127.0.0.1:{port}"
    print(f"\n  中文文字閱讀器 → {url}")
    if port in AIRPLAY_PORTS:
        print(f"  ⚠️  {port} 係 macOS AirPlay Receiver 常用 port，"
              "瀏覽器可能會收到「Access to 127.0.0.1 was denied」403，建議改用 5050。")
    for e in tts.engine_list():
        mark = "✓" if e["available"] else "✗"
        extra = "" if e["available"] else f"  ({e.get('reason', '')})"
        print(f"    {mark} {e['id']:<6} {e['label']}{extra}")
    print()
    threading.Thread(
        target=open_browser_when_ready, args=(url, port), daemon=True
    ).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
