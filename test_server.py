"""後端整合測試 — 驗證「阻塞至讀完」這個核心同步假設是否真的成立。

前置：先起 server →  uv run python app.py 5000
跑法：uv run python test_server.py
"""

import json
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:5000"

results = []


def call(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def speak(text, multiplier=1.0, voice="Tingting", engine="say"):
    t0 = time.time()
    res = call("/api/speak", {"text": text, "multiplier": multiplier,
                              "voice": voice, "engine": engine})
    return res, time.time() - t0


# --- 1. health / engines ----------------------------------------------
h = call("/api/health")
engines = {e["id"]: e for e in h["engines"]}
check("列出兩個引擎", set(engines) == {"say", "edge"}, str(sorted(engines)))
check("macOS say 引擎可用", engines["say"]["available"] is True)
check("edge-tts 引擎已安裝並可用", engines["edge"]["available"] is True,
      engines["edge"].get("reason", ""))
check("opencc 已載入", h["opencc"] is True)
check("macOS 預設引擎為 say", h["default_engine"] == "say")

# --- 1b. 語音清單：只列真係有中文語音資料的 ----------------------------
say_voices = call("/api/voices?engine=say")["voices"]
say_names = {v["value"] for v in say_voices}
check("say 只列出確實有中文語音資料的語音", say_names <= {"Tingting", "Meijia", "Sinji"},
      str(sorted(say_names)))
check("say 預設普通話 Tingting 有列出", "Tingting" in say_names, str(sorted(say_names)))
check("say 語音有可讀標籤", all(v["label"] and "·" in v["label"] for v in say_voices),
      str([v["label"] for v in say_voices]))

# --- 1c. 回歸測試：say 列出嘅語音必須真係讀到中文 ------------------------
# 清單來自掃描語音資料檔，但萬一系統改變，用實測把關。
# 量測基準：無中文資料的語音讀中文 ≈ 0.5s（純 process 開銷）；有中文 ≈ 2.4s。
PROBE = "這是一個中文測試句子用來確認語音"
for v in say_voices:
    _, dt = speak(PROBE, 2.0, v["value"])
    check(f'say/{v["value"]} 真的讀得出中文（{dt:.2f}s）', dt > 1.2, f"耗時 {dt:.2f}s")

# --- 1d. edge-tts 語音清單 --------------------------------------------
edge = call("/api/voices?engine=edge")
edge_voices = edge["voices"]
check("edge 引擎列出多個普通話音色", len(edge_voices) >= 8, f"{len(edge_voices)} 個")
check("edge 音色全是 zh- 開頭", all(v["value"].startswith("zh-") for v in edge_voices))
check("edge 音色有標註性別", all("女聲" in v["label"] or "男聲" in v["label"] for v in edge_voices),
      str([v["label"] for v in edge_voices][:3]))

# edge 引擎實測：真的能出聲嗎
_, d_edge = speak(PROBE, 2.0, edge_voices[0]["value"], engine="edge")
check(f'edge/{edge_voices[0]["value"]} 真的讀得出普通話（{d_edge:.2f}s）', d_edge > 1.2,
      f"耗時 {d_edge:.2f}s")

# --- 2. split --------------------------------------------------------
MIXED = "「你好。」圓周率是 3.14。這個苹果很甜！\n第二段開始。真的嗎？！"
s = call("/api/split", {"text": MIXED})["sentences"]
check("混合文本拆句", len(s) == 5, f"{len(s)} 句 → {s}")
check("收尾引號黏合", s[0] == "「你好。」", repr(s[0]))
check("小數點未誤切", s[1] == "圓周率是 3.14。", repr(s[1]))

# --- 3. 繁簡轉換 ------------------------------------------------------
simp = call("/api/split", {"text": "这个苹果很甜。", "convert": "s2t"})["sentences"]
check("簡→繁轉換", simp == ["這個蘋果很甜。"], str(simp))
trad = call("/api/split", {"text": "這個蘋果很甜。", "convert": "t2s"})["sentences"]
check("繁→簡轉換", trad == ["这个苹果很甜。"], str(trad))
check("轉換後句數不變", len(simp) == 1)

# --- 4. 核心假設：speak 阻塞到讀完 ------------------------------------
SHORT = "今天天氣很好。"
LONG = "春天的午後陽光溫暖，孩子們在草地上奔跑嬉戲，笑聲隨風飄散在空氣裡。"
r_s, d_s = speak(SHORT, 2.0)
r_l, d_l = speak(LONG, 2.0)
check("短句朗讀成功", r_s.get("ok") is True, f"耗時 {d_s:.2f}s")
check("長句比短句耗時長（證明確實等讀完，非即時返回）", d_l > d_s + 0.3, f"短 {d_s:.2f}s / 長 {d_l:.2f}s")

# --- 5. 變速：倍率越高越快 --------------------------------------------
_, d_slow = speak(SHORT, 0.5)
_, d_fast = speak(SHORT, 2.0)
check("0.5× 比 2.0× 慢", d_slow > d_fast * 1.5, f"0.5×={d_slow:.2f}s vs 2.0×={d_fast:.2f}s")

# --- 6. 停止：朗讀途中打斷 --------------------------------------------
box = {}


def bg():
    box["res"], box["t"] = speak(LONG, 0.5)   # 慢速，確保有時間打斷


th = threading.Thread(target=bg)
th.start()
time.sleep(0.4)
t0 = time.time()
call("/api/stop", {})
stop_latency = time.time() - t0
th.join(timeout=5)
check("停止回應快速", stop_latency < 0.5, f"{stop_latency:.2f}s")
check("被停止的朗讀回傳 stopped", box.get("res", {}).get("reason") == "stopped", str(box.get("res")))

# --- 7. 停止後仍可再次朗讀（無卡死）-----------------------------------
r2, d2 = speak(SHORT, 2.0)
check("停止後可再次朗讀", r2.get("ok") is True, f"耗時 {d2:.2f}s")

# --- 8. 前端腳本語法（測「真正渲染出來的頁面」，不是模板檔）-------------
# 之前用模板檔 + 字串取代去測，等於沒測到 Jinja 實際輸出，曾漏掉一次
# `const DEFAULT_VOICE = Tingting;`（漏引號 → 整個 script 掛掉 → 按鈕全死）。
import os
import re
import subprocess
import tempfile

with urllib.request.urlopen(BASE + "/", timeout=10) as r:
    page = r.read().decode()

check("頁面無殘留模板變數", "{{" not in page and "{%" not in page)
check("頁面無未渲染的 Jinja 敘述", "selectattr" not in page)

script = re.search(r"<script>(.*?)</script>", page, re.S)
check("頁面含 script 區塊", script is not None)
if script:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(script.group(1))
        tmp = f.name
    proc = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    os.unlink(tmp)
    check("渲染後的 JS 語法有效（node --check）", proc.returncode == 0,
          proc.stderr.strip()[:200])
    # 常數必須是合法字面值
    for name in ("VOICES", "OPENCC", "DEFAULT_VOICE"):
        m = re.search(rf"^const {name} = (.+);$", script.group(1), re.M)
        ok = bool(m) and (m.group(1).startswith('"') or m.group(1).startswith("[")
                          or m.group(1) in ("true", "false", "null"))
        check(f"const {name} 是合法字面值", ok, m.group(1) if m else "找不到")

print(f"\n{sum(results)}/{len(results)} 通過")
raise SystemExit(0 if all(results) else 1)
