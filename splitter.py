"""中文句子拆分：以中文標點符號為界線。

掃描式切分（非 re.split），因為要處理：
  - 收尾引號/括號黏合：「你好。」然後他走了。  →  「你好。」+「然後他走了。」
  - 小數點保護：圓周率是 3.14，約等於 22/7。 → 不切
  - 單省略號只是語氣停頓：我不知道…他走了。   → 不切
  - 無實質內容的片段（。。。、———）→ 丟棄
"""

import re

# 句末標點：出現即切句
SENT_END = set("。！？!?；;")

# 句末標點之後要一併收進同一句的收尾符號
TRAIL = set("」』”’）)］]｝}》〉】〕›»")

# 片段開頭殘留、需要剝掉的符號（str.strip 只接受字串，故轉成字串）
LEAD_STRIP = "".join(TRAIL) + "、，,～~"

ELLIPSIS = "…"

CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
HAS_CONTENT = re.compile(r"[㐀-䶿一-鿿豈-﫿A-Za-z0-9]")


def _flush(buf, out):
    """把緩衝區收成一句；無實質內容則丟棄。"""
    s = "".join(buf).strip()
    del buf[:]
    s = s.lstrip(LEAD_STRIP).strip()
    if not s or not HAS_CONTENT.search(s):
        return
    out.append(s)


def split_sentences(text):
    """回傳句子串列（不含空白，保留原有標點）。"""
    out, buf = [], []
    n, i = len(text), 0

    while i < n:
        ch = text[i]

        # 換行 = 段落邊界，強制切
        if ch == "\n":
            _flush(buf, out)
            i += 1
            continue

        # 句末標點（連續同字重複壓成 1 個，混用則保留：？！）
        if ch in SENT_END:
            start = i
            while i < n and text[i] in SENT_END:
                i += 1
            run = text[start:i]
            buf.append(run if len(set(run)) > 1 else run[0])
            while i < n and text[i] in TRAIL:
                buf.append(text[i])
                i += 1
            _flush(buf, out)
            continue

        # 省略號：雙「……」是完整停頓 → 切；單「…」接中文字只是語氣停頓 → 不切
        if ch == ELLIPSIS:
            start = i
            while i < n and text[i] == ELLIPSIS:
                i += 1
            run_len = i - start
            buf.append(ELLIPSIS * min(run_len, 2))
            is_boundary = run_len >= 2 or not (i < n and CJK.match(text[i]))
            if is_boundary:
                while i < n and text[i] in TRAIL:
                    buf.append(text[i])
                    i += 1
                _flush(buf, out)
            continue

        # 半形句點：左右都是數字 → 小數點，不切
        if ch == ".":
            prev_digit = i > 0 and text[i - 1].isdigit()
            next_digit = i + 1 < n and text[i + 1].isdigit()
            if not (prev_digit and next_digit):
                buf.append(ch)
                i += 1
                while i < n and (text[i] in SENT_END or text[i] in TRAIL):
                    buf.append(text[i])
                    i += 1
                _flush(buf, out)
                continue

        buf.append(ch)
        i += 1

    _flush(buf, out)
    return out
