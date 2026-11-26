#!/usr/bin/env python3
"""Fitlog PR動画レンダラー：YAMLの構成表 → 1080x1920 の縦動画(mp4)

  python3 tools/render.py project_a.yaml            # 本番画質
  python3 tools/render.py project_a.yaml --preview  # 速い・低画質で確認
  python3 tools/render.py project_a.yaml --only result  # 1カットだけ

素材が無いカットは「素材待ち」プレースホルダーで描画されます。
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- styles
# y は既定の表示位置（ブロック中心）。Reels/TikTokの右側アイコン・下部UIを避けた範囲に収める。
STYLES = {
    "hook":    dict(size=118, weight=900, fill="#FFFFFF", stroke=16, stroke_fill="#000000", accent="#FFE600", y=520),
    "title":   dict(size=76,  weight=900, fill="#FFFFFF", band="#E8322B", pad=(36, 18), accent="#FFE600", y=380),
    "sub":     dict(size=58,  weight=800, fill="#FFFFFF", box=(0, 0, 0, 175), pad=(34, 20), radius=18, accent="#FFE600", y=1020),
    "big":     dict(size=170, weight=900, fill="#FFE600", stroke=16, stroke_fill="#000000", accent="#FFFFFF", y=820),
    "cta":     dict(size=72,  weight=900, fill="#111111", box="#FFE600", pad=(44, 26), radius=24, accent="#E8322B", y=1000),
    "label":   dict(size=42,  weight=800, fill="#FFFFFF", box=(20, 20, 20, 200), pad=(24, 12), radius=12, accent="#FFE600", y=330),
    "caption": dict(size=44,  weight=700, fill="#FFFFFF", stroke=7, stroke_fill="#000000", accent="#FFE600", y=1230),
}
MAX_TEXT_W = 940
ACCENT_RE = re.compile(r"\*(.+?)\*")
VAR_RE = re.compile(r"\$\{([\w.]+)\}")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


class Fonts:
    def __init__(self, path):
        self.path = str(path)
        self.cache = {}

    def get(self, size, weight):
        key = (size, weight)
        if key not in self.cache:
            f = ImageFont.truetype(self.path, size)
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
            self.cache[key] = f
        return self.cache[key]


# ---------------------------------------------------------------- data
def fmt_num(v, key):
    if key == "kcal":
        return f"{round(v):d}"
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def build_context(data):
    ctx = {k: v for k, v in data.items() if not isinstance(v, (list, dict))}
    keys = ["kcal", "P", "F", "C"]
    measured = {k: sum(float(i.get(k, 0)) for i in data.get("items", [])) for k in keys}
    fit = {k: float(data.get("fitlog", {}).get(k, 0)) for k in keys}
    diff = {k: fit[k] - measured[k] for k in keys}
    ctx["measured"] = {k: fmt_num(measured[k], k) for k in keys}
    ctx["fitlog"] = {k: fmt_num(fit[k], k) for k in keys}
    ctx["diff"] = {k: ("+" if diff[k] > 0 else "±" if diff[k] == 0 else "−") + fmt_num(abs(diff[k]), k) for k in keys}
    ctx["verdict"] = data.get("verdict", {})
    ctx["_raw"] = dict(measured=measured, fitlog=fit, diff=diff, thresholds=data.get("thresholds", {}))
    return ctx


def subst(text, ctx):
    def rep(m):
        cur = ctx
        for part in m.group(1).split("."):
            if not isinstance(cur, dict) or part not in cur:
                return "[" + m.group(1) + "]"
            cur = cur[part]
        return str(cur)
    return VAR_RE.sub(rep, str(text))


# ---------------------------------------------------------------- text drawing
def parse_runs(line):
    """'abc*def*g' -> [('abc',False),('def',True),('g',False)]"""
    runs, pos = [], 0
    for m in ACCENT_RE.finditer(line):
        if m.start() > pos:
            runs.append((line[pos:m.start()], False))
        runs.append((m.group(1), True))
        pos = m.end()
    if pos < len(line):
        runs.append((line[pos:], False))
    return runs


def render_text(text, style, fonts, max_chars=None):
    """テキストブロックをRGBA画像に。max_charsで先頭からN文字だけ描く（タイプ演出用）"""
    st = STYLES[style]
    lines = [parse_runs(l) for l in text.split("\n")]
    if max_chars is not None:
        left, cut = max_chars, []
        for runs in lines:
            nl = []
            for s, a in runs:
                if left <= 0:
                    break
                nl.append((s[:left], a))
                left -= len(s)
            cut.append(nl)
        full_lines, lines = lines, cut
    else:
        full_lines = lines

    size = st["size"]
    stroke = st.get("stroke", 0)
    pad_x, pad_y = st.get("pad", (0, 0))
    # 幅に収まるまで縮小（全文基準で決めて、タイプ演出中にサイズが変わらないように）
    while True:
        font = fonts.get(size, st["weight"])
        widths = [sum(font.getlength(s) for s, _ in runs) for runs in full_lines]
        if max(widths + [0]) + 2 * (stroke + pad_x) <= MAX_TEXT_W + 2 * pad_x or size <= 24:
            break
        size -= 4
    asc, desc = font.getmetrics()
    line_h = int((asc + desc) * 1.12)
    block_w = int(max(widths + [1]) + 2 * (stroke + pad_x))
    block_h = int(line_h * len(full_lines) + 2 * (stroke + pad_y))
    img = Image.new("RGBA", (block_w + 8, block_h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if "box" in st or "band" in st:
        color = st.get("box", st.get("band"))
        d.rounded_rectangle([4, 4, block_w + 3, block_h + 3], radius=st.get("radius", 0), fill=color)
    y = 4 + stroke + pad_y
    for runs, w in zip(lines, widths):
        x = 4 + (block_w - w) / 2
        for s, acc in runs:
            if not s:
                continue
            color = st["accent"] if acc else st["fill"]
            if stroke:
                d.text((x, y), s, font=font, fill=color, stroke_width=stroke, stroke_fill=st["stroke_fill"])
            else:
                d.text((x, y), s, font=font, fill=color)
            x += font.getlength(s)
        y += line_h
    return img


def render_table(ctx, fonts):
    """実測 vs Fitlog の比較表。行ごとの画像リストを返す [(img, y_center)]"""
    raw = ctx["_raw"]
    th = raw["thresholds"]
    rows = []
    col_x = [70, 400, 640, 870]  # 項目 / 実測 / Fitlog / 差 の中心x（項目だけ左寄せ）
    hdr_font = fonts.get(40, 800)
    val_font = fonts.get(60, 900)
    lab_font = fonts.get(52, 900)

    def row_img(cells, fonts_, colors, bg):
        img = Image.new("RGBA", (W, 130), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if bg:
            d.rounded_rectangle([50, 8, W - 50, 122], radius=20, fill=bg)
        for i, (txt, f, c) in enumerate(zip(cells, fonts_, colors)):
            tw = f.getlength(txt)
            x = col_x[i] + 20 if i == 0 else col_x[i] - tw / 2
            asc, desc = f.getmetrics()
            d.text((x, 65 - (asc + desc) / 2), txt, font=f, fill=c)
        return img

    rows.append((row_img(["", "実測", "Fitlog", "差"], [hdr_font] * 4,
                         ["#FFFFFF", "#BBBBBB", "#FFE600", "#BBBBBB"], None), 560))
    labels = {"kcal": "カロリー", "P": "P", "F": "F", "C": "C"}
    units = {"kcal": "", "P": "g", "F": "g", "C": "g"}
    for i, k in enumerate(["kcal", "P", "F", "C"]):
        within = abs(raw["diff"][k]) <= float(th.get(k, 1e9))
        diff_color = "#3DDC84" if within else "#FF9F1C"
        cells = [labels[k], ctx["measured"][k] + units[k], ctx["fitlog"][k] + units[k], ctx["diff"][k]]
        rows.append((row_img(cells, [lab_font, val_font, val_font, val_font],
                             ["#FFFFFF", "#FFFFFF", "#FFE600", diff_color], (0, 0, 0, 170)), 690 + i * 140))
    return rows


# ---------------------------------------------------------------- animation
def ease_out_back(x, s=1.70158):
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def anim_state(anim, lt, life):
    """lt=要素のローカル時間。返り値 (scale, alpha, dx, dy)"""
    if lt < 0:
        return None
    s, a, dx, dy = 1.0, 1.0, 0, 0
    if anim == "pop":
        p = min(1, lt / 0.28)
        s = 0.55 + 0.45 * ease_out_back(p)
        a = min(1, lt / 0.1)
    elif anim == "stamp":
        p = smooth(lt / 0.2)
        s = 1.7 - 0.7 * p
        a = min(1, lt / 0.08)
    elif anim == "slide":
        p = smooth(lt / 0.3)
        dx = int(-160 * (1 - p))
        a = p
    elif anim in ("countup", "type"):
        a = min(1, lt / 0.1)
    if life is not None:  # 退場フェード
        rem = life - lt
        if rem < 0:
            return None
        if rem < 0.15:
            a *= rem / 0.15
    return s, a, dx, dy


class Element:
    def __init__(self, img_fn, anim, start, end, cx, cy, dynamic=False):
        self.img_fn, self.anim, self.start, self.end = img_fn, anim, start, end
        self.cx, self.cy, self.dynamic = cx, cy, dynamic
        self._static = None

    def image(self, lt):
        if self.dynamic:
            return self.img_fn(lt)
        if self._static is None:
            self._static = self.img_fn(0)
        return self._static


def countup_text(text, p):
    def rep(m):
        v = float(m.group(0))
        cur = v * smooth(p)
        return f"{cur:.1f}" if "." in m.group(0) else f"{round(cur):d}"
    return NUM_RE.sub(rep, text)


def wrap_caption(text, fonts):
    """字幕が1行に収まらなければ、中央に近い句読点（無ければ中央）で2行に折る"""
    if "\n" in text:
        return text
    st = STYLES["caption"]
    font = fonts.get(st["size"], st["weight"])
    if font.getlength(text) + 2 * st["stroke"] <= MAX_TEXT_W:
        return text
    mid = len(text) / 2
    cands = [i + 1 for i, ch in enumerate(text[:-1]) if ch in "、。！？!?,， "]
    cut = min(cands, key=lambda i: abs(i - mid)) if cands else int(mid)
    if abs(cut - mid) > len(text) * 0.3:
        cut = int(mid)
    return text[:cut].rstrip() + "\n" + text[cut:].lstrip()


def build_elements(seg, ctx, fonts, cfg, sample):
    els = []
    dur = float(seg["dur"])
    for t in seg.get("telops", []) or []:
        start = float(t.get("start", 0))
        end = t.get("end")
        life = (float(end) - start) if end is not None else None
        if t.get("type") == "table":
            for i, (img, cy) in enumerate(render_table(ctx, fonts)):
                els.append(Element(lambda lt, im=img: im, "slide", start + i * 0.35, life, W // 2, cy))
            continue
        style = t.get("style", "sub")
        text = subst(t["text"], ctx).replace("\\n", "\n")
        anim = t.get("anim", "pop")
        pos = t.get("pos") or [W // 2, STYLES[style]["y"]]
        if anim == "countup":
            cache = {}
            def fn(lt, text=text, style=style, cache=cache):
                key = countup_text(text, min(1, lt / 0.7))
                if key not in cache:
                    cache[key] = render_text(key, style, fonts)
                return cache[key]
            els.append(Element(fn, anim, start, life, pos[0], pos[1], dynamic=True))
        elif anim == "type":
            n = len(ACCENT_RE.sub(r"\1", text).replace("\n", ""))
            cache = {}
            def fn(lt, text=text, style=style, n=n, cache=cache):
                k = min(n, int(lt / 0.06) + 1)
                if k not in cache:
                    cache[k] = render_text(text, style, fonts, max_chars=k)
                return cache[k]
            els.append(Element(fn, anim, start, life, pos[0], pos[1], dynamic=True))
        else:
            els.append(Element(lambda lt, tx=text, st=style: render_text(tx, st, fonts),
                               anim, start, life, pos[0], pos[1]))
    if seg.get("caption"):
        cap = wrap_caption(subst(seg["caption"], ctx), fonts)
        els.append(Element(lambda lt, c=cap: render_text(c, "caption", fonts), "none", 0, None, W // 2, STYLES["caption"]["y"]))
    if cfg.get("pr_badge"):
        els.append(Element(lambda lt: render_text("PR", "label", fonts), "none", 0, None, 110, 230))
    if sample:
        def wm(lt):
            img = Image.new("RGBA", (900, 120), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((450, 60), "SAMPLE DATA", font=fonts.get(90, 900),
                                     fill=(255, 60, 60, 140), anchor="mm")
            return img
        els.append(Element(wm, "none", 0, None, W // 2, 1500))
    return els


def frame_at(els, t):
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    key = []
    for e in els:
        st = anim_state(e.anim, t - e.start, e.end)
        if st is None:
            key.append(None)
            continue
        s, a, dx, dy = st
        img = e.image(t - e.start)
        key.append((id(img), round(s, 3), round(a, 3), dx, dy))
        if s != 1.0:
            nw, nh = max(1, int(img.width * s)), max(1, int(img.height * s))
            img = img.resize((nw, nh), Image.BILINEAR)
        if a < 1.0:
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
        x = int(e.cx - img.width / 2 + dx)
        y = int(e.cy - img.height / 2 + dy)
        canvas.alpha_composite(img, (max(0, x), max(0, y)),
                               (max(0, -x), max(0, -y)))
    return canvas, tuple(key)


# ---------------------------------------------------------------- ffmpeg helpers
def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed: {' '.join(map(str, cmd))[:400]}")
    return r


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def is_image(p):
    return p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".heic")


def placeholder(seg, fonts, out):
    img = Image.new("RGB", (W, H), (46, 50, 58))
    d = ImageDraw.Draw(img)
    for yy in range(0, H, 120):
        d.line([(0, yy), (W, yy + 300)], fill=(56, 60, 68), width=40)
    d.text((W // 2, 1340), "素材待ち", font=fonts.get(80, 900), fill="#FF9F1C", anchor="mm")
    d.text((W // 2, 1440), seg.get("src", "(src未指定)"), font=fonts.get(38, 700), fill="#DDDDDD", anchor="mm")
    note = seg.get("note", "")
    for i in range(0, len(note), 20):
        d.text((W // 2, 1520 + (i // 20) * 56), note[i:i + 20], font=fonts.get(40, 500), fill="#AAAAAA", anchor="mm")
    img.save(out)
    return out


def render_segment(seg, idx, cfg, ctx, fonts, tmp, fps, preview, sample):
    dur = float(seg["dur"])
    speed = float(seg.get("speed", 1))
    src = ROOT / seg["src"] if seg.get("src") else None
    use_placeholder = src is None or not src.exists()
    if use_placeholder:
        src = placeholder(seg, fonts, tmp / f"ph_{idx:02d}.png")
    image_src = is_image(src)

    inputs, vf, af = [], [], None
    if image_src:
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}", "-i", str(src)]
    else:
        inputs += ["-ss", f"{float(seg.get('in', 0))}", "-t", f"{dur * speed + 0.1}", "-i", str(src)]
    # 0: 映像素材 / 1: テロップ(rawvideo) / 2: 無音
    inputs += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0"]
    inputs += ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo"]
    n_in = 3

    chain = [f"setpts=(PTS-STARTPTS)/{speed}", f"fps={fps}",
             f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}", "setsar=1"]
    zoom = seg.get("zoom")
    if zoom or (image_src and seg.get("kenburns", use_placeholder is False)):
        f2 = 1 if preview else 2
        chain.append(f"scale={W * f2}:{H * f2}")
        if zoom:
            a, r = float(zoom.get("at", 0)), max(0.05, float(zoom.get("ramp", 0.4)))
            sc = float(zoom.get("scale", 1.4))
            p = f"clip((in/{fps}-{a})/{r},0,1)"
            z = f"1+({sc}-1)*({p})*({p})*(3-2*({p}))"
            cx, cy = float(zoom.get("cx", 0.5)), float(zoom.get("cy", 0.5))
        else:
            z = f"1+0.06*in/{dur * fps}"
            cx = cy = 0.5
        chain.append(f"zoompan=z='{z}':x='(iw-iw/zoom)*{cx}':y='(ih-ih/zoom)*{cy}':d=1:s={W}x{H}:fps={fps}")
    if seg.get("blur"):
        chain.append(f"gblur=sigma={float(seg['blur'])}")
    if seg.get("dim"):
        chain.append(f"colorlevels=romax={1 - seg['dim']}:gomax={1 - seg['dim']}:bomax={1 - seg['dim']}")
    filt = [f"[0:v]{','.join(chain)}[bg]",
            f"[bg][1:v]overlay=0:0:format=auto,format=yuv420p,trim=duration={dur}[v]"]

    # ---- audio
    audio_srcs = []
    has_src_audio = (not image_src) and any(s.get("codec_type") == "audio" for s in probe(src).get("streams", []))
    if seg.get("audio", "keep") == "keep" and speed == 1 and has_src_audio:
        audio_srcs.append("[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS")
    vo = ROOT / seg["vo"] if seg.get("vo") else None
    if vo and vo.exists():
        inputs += ["-ss", f"{float(seg.get('vo_in', 0))}", "-t", f"{dur}", "-i", str(vo)]
        audio_srcs = [f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS"]
        n_in += 1
    for sfx in seg.get("sfx", []) or []:
        p = ROOT / sfx["src"]
        if not p.exists():
            continue
        inputs += ["-i", str(p)]
        ms = int(float(sfx.get("at", 0)) * 1000)
        audio_srcs.append(f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo,"
                          f"volume={sfx.get('volume', 1)},adelay={ms}|{ms}")
        n_in += 1
    labels = []
    for i, a in enumerate(audio_srcs):
        filt.append(f"{a}[a{i}]")
        labels.append(f"[a{i}]")
    labels.append("[2:a]")
    filt.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                f"apad,atrim=0:{dur},asetpts=PTS-STARTPTS[a]")

    out = tmp / f"seg_{idx:02d}.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(filt), "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "veryfast" if preview else "medium",
           "-crf", "26" if preview else "17", "-pix_fmt", "yuv420p", "-r", str(fps),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    els = build_elements(seg, ctx, fonts, cfg, sample)
    n = int(round(dur * fps))
    last_key, last_bytes = None, None
    for f in range(n):
        canvas, key = frame_at(els, f / fps)
        if key != last_key:
            last_bytes, last_key = canvas.tobytes(), key
        proc.stdin.write(last_bytes)
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit(f"segment {seg.get('id')} failed")
    flag = "  (素材待ち)" if use_placeholder else ""
    print(f"  [{idx + 1}] {seg.get('id', '')}  {dur:.1f}s{flag}")
    return out


def finalize(segs, cfg, out, tmp, preview):
    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    joined = tmp / "joined.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(joined)])
    total = float(probe(joined)["format"]["duration"])
    bgm = cfg.get("bgm") or {}
    bgm_path = ROOT / bgm["src"] if bgm.get("src") else None
    lufs = cfg.get("loudness", -14)
    if bgm_path and bgm_path.exists():
        vol = bgm.get("volume", 0.18)
        filt = (f"[1:a]volume={vol},atrim=0:{total},afade=t=out:st={max(0, total - 1.5)}:d=1.5[bgm];"
                "[0:a]asplit=2[voice][sc];")
        if bgm.get("duck", True):
            filt += "[bgm][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bd];"
        else:
            filt += "[bgm]anull[bd];"
        filt += f"[voice][bd]amix=inputs=2:normalize=0:duration=first,loudnorm=I={lufs}:TP=-1.5:LRA=11[a]"
        inputs = ["-i", str(joined), "-stream_loop", "-1", "-i", str(bgm_path)]
    else:
        filt = f"[0:a]loudnorm=I={lufs}:TP=-1.5:LRA=11[a]"
        inputs = ["-i", str(joined)]
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", filt,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(out)])
    return total


def make_cover(cover, ctx, fonts, sample):
    """Reels/TikTok用の表紙 1080x1920。文字はプロフィール一覧(3:4)で切れない中央帯に置く"""
    src = None
    for key in ("src", "fallback"):
        if cover.get(key) and (ROOT / cover[key]).exists():
            src = ROOT / cover[key]
            break
    out = ROOT / cover.get("output", "out/cover.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    if src is None:
        bg = Image.new("RGB", (W, H), (46, 50, 58))
    elif is_image(src):
        bg = Image.open(src).convert("RGB")
    else:
        tmpf = out.with_suffix(".frame.png")
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(float(cover.get("in", 0))), "-i", str(src),
             "-frames:v", "1", str(tmpf)])
        bg = Image.open(tmpf).convert("RGB")
        tmpf.unlink()
    r = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * r + 0.5), int(bg.height * r + 0.5)), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H):  # 中央を暗くして文字を読みやすく
        a = int(150 * max(0.0, 1 - abs(y - 960) / 760))
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    img = Image.alpha_composite(bg.convert("RGBA"), shade)
    blocks = []
    if cover.get("label"):
        blocks.append(render_text(subst(cover["label"], ctx), "title", fonts))
    blocks.append(render_text(subst(cover.get("text", ""), ctx).replace("\\n", "\n"), "hook", fonts))
    gap = 40
    total = sum(b.height for b in blocks) + gap * (len(blocks) - 1)
    y = 960 - total // 2
    for b in blocks:
        img.alpha_composite(b, ((W - b.width) // 2, y))
        y += b.height + gap
    pr = render_text("PR", "label", fonts)
    img.alpha_composite(pr, (60, 380))
    if sample:
        ImageDraw.Draw(img).text((W // 2, 1560), "SAMPLE DATA", font=fonts.get(90, 900),
                                 fill=(255, 60, 60, 160), anchor="mm")
    img.convert("RGB").save(out, quality=92)
    # 一覧表示(3:4)での見え方
    grid = img.convert("RGB").crop((0, (H - 1440) // 2, W, (H - 1440) // 2 + 1440))
    grid.save(out.with_name(out.stem + "_grid.jpg"), quality=88)
    print(f"cover: {out.relative_to(ROOT)}{'' if src else '  (写真待ち)'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--preview", action="store_true", help="低画質・高速")
    ap.add_argument("--only", help="指定IDのカットだけ書き出す")
    ap.add_argument("-o", "--output")
    ap.add_argument("--cover-only", action="store_true", help="表紙だけ作る")
    ap.add_argument("--check", action="store_true", help="レギュレーションチェックだけ")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / args.project).read_text())
    fps = int(cfg.get("fps", 30))
    font = ROOT / cfg.get("font", "assets/fonts/NotoSansJP.ttf")
    if not font.exists():
        sys.exit(f"フォントがありません: {font}\n  bash tools/setup.sh を実行してください")
    fonts = Fonts(font)
    data = yaml.safe_load((ROOT / cfg["data"]).read_text()) if cfg.get("data") else {}
    ctx = build_context(data)
    sample = bool(data.get("sample"))

    from compliance import lint_project, report
    errors = report(lint_project(cfg, lambda t: subst(t, ctx), ROOT))
    if args.check:
        sys.exit(1 if errors else 0)
    if cfg.get("cover"):
        make_cover(cfg["cover"], ctx, fonts, sample)
    if args.cover_only:
        return

    segs = cfg["segments"]
    if args.only:
        segs = [s for s in segs if s.get("id") == args.only]
        if not segs:
            sys.exit(f"id '{args.only}' が見つかりません")
    out = ROOT / (args.output or cfg.get("output", "out/output.mp4"))
    if args.preview and not args.output:
        out = out.with_name(out.stem + "_preview" + out.suffix)
    if args.only and not args.output:
        out = out.with_name(out.stem + f"_{args.only}" + out.suffix)

    tmp = ROOT / "out" / ".work"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    print(f"render: {args.project}  ({len(segs)}カット){'  [preview]' if args.preview else ''}")
    if sample:
        print("  ※ data の sample: true → SAMPLE DATA の透かし入り")
    files = [render_segment(s, i, cfg, ctx, fonts, tmp, fps, args.preview, sample) for i, s in enumerate(segs)]
    total = finalize(files, cfg, out, tmp, args.preview)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"done: {out.relative_to(ROOT)}  ({total:.1f}s)")


if __name__ == "__main__":
    main()
