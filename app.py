#!/usr/bin/env python3
"""中文文字閱讀器 — Flask 後端。

同步設計：/api/speak 會「阻塞到語音引擎讀完」才回 response，
所以「收到 response」≡「這句讀完了」。前端因此不需要 SSE / WebSocket，
進度與高亮都是本地狀態，不會錯位。
"""

import subprocess

from flask import Flask, jsonify, render_template, request

import tts

app = Flask(__name__)

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
             "disabled": not e["available"]}
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


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"\n  中文文字閱讀器 → http://127.0.0.1:{port}")
    for e in tts.engine_list():
        mark = "✓" if e["available"] else "✗"
        extra = "" if e["available"] else f"  ({e.get('reason', '')})"
        print(f"    {mark} {e['id']:<6} {e['label']}{extra}")
    print()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
