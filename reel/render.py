#!/usr/bin/env python3
"""Instagram リール / TikTok 向け 9:16 縦型動画レンダラー。

レイヤー構成（奥 → 手前）:
  1. 元動画（9:16 にカバー切り抜き）
  2. 巨大な半透明ボールド文字（人物の背面）
  3. 人物の切り抜き（MediaPipe selfie segmentation）
  4. キネティックタイポグラフィのテロップ（1文字ずつ跳ねる）
  5. ラストの CTA バナー（パルス表示）

使い方:
  python3 render.py --input 撮影動画.mp4 --script scripts/example.json --output output/reel.mp4
  --guides を付けると UI 被り禁止ゾーン（上下20%・右10%）を赤く表示する。
"""
import argparse
import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
FPS = 30

# UI 被り禁止ゾーン：上下 20%、右端 10%
SAFE_TOP = int(H * 0.20)
SAFE_BOTTOM = int(H * 0.80)
SAFE_RIGHT = int(W * 0.90)
SAFE_LEFT = int(W * 0.05)
SAFE_CX = (SAFE_LEFT + SAFE_RIGHT) // 2
SAFE_W = SAFE_RIGHT - SAFE_LEFT

FONT_BLACK = ROOT / "fonts" / "NotoSansJP-Black.ttf"
FONT_XBOLD = ROOT / "fonts" / "NotoSansJP-ExtraBold.ttf"
MODEL = ROOT / "models" / "selfie_multiclass.tflite"

WHITE = (255, 255, 255)
GOLD = (255, 200, 40)
GOLD_DEEP = (214, 150, 20)
INK = (28, 20, 10)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_back(u, s=1.9):
    u = clamp(u) - 1
    return 1 + (s + 1) * u ** 3 + s * u ** 2


def ease_out_cubic(u):
    return 1 - (1 - clamp(u)) ** 3


def lerp_color(c1, c2, u):
    return tuple(int(a + (b - a) * u) for a, b in zip(c1, c2))


@lru_cache(maxsize=None)
def font(path, size):
    return ImageFont.truetype(str(path), size)


# ---------------------------------------------------------------- 人物切り抜き
class PersonMasker:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import vision, BaseOptions

        self.mp = mp
        opts = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            output_confidence_masks=True,
        )
        self.seg = vision.ImageSegmenter.create_from_options(opts)
        self.prev = None

    def __call__(self, frame, t_ms):
        small = np.ascontiguousarray(frame[::2, ::2])
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=small)
        res = self.seg.segment_for_video(img, int(t_ms))
        person = 1.0 - np.squeeze(res.confidence_masks[0].numpy_view())  # 0 = 背景クラス
        # 時間方向の平滑化でチラつきを抑える
        self.prev = person if self.prev is None else self.prev * 0.45 + person * 0.55
        m = Image.fromarray((clamp_arr(self.prev) * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
        m = m.filter(ImageFilter.GaussianBlur(2.2))
        a = np.asarray(m, dtype=np.float32) / 255.0
        # エッジを少し締める
        return np.clip((a - 0.35) / 0.4, 0, 1)[..., None]


def clamp_arr(a):
    return np.clip(a, 0, 1)


# ---------------------------------------------------------------- 背面の巨大文字
class BigBackText:
    def __init__(self, cfg):
        self.lines = cfg["lines"]
        self.start = cfg.get("start", 0.0)
        self.end = cfg.get("end", 4.0)
        self.opacity = cfg.get("opacity", 0.78)
        self.y = cfg.get("y", 0.33)
        self.dim = cfg.get("dim_background", 0.45)
        self.layer = self._render()

    def _render(self):
        n = max(len(l) for l in self.lines)
        size = int(min(W * 0.98 / n, 320))
        f = font(FONT_BLACK, size)
        lh = int(size * 1.02)
        img = Image.new("RGBA", (W, lh * len(self.lines) + 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i, line in enumerate(self.lines):
            tw = d.textlength(line, font=f)
            d.text(((W - tw) / 2, 10 + i * lh), line, font=f, fill=WHITE + (255,),
                   stroke_width=max(6, size // 28), stroke_fill=GOLD + (255,))
        # 明るい背景でも読めるよう、ぼかした影を敷く
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow.putalpha(img.getchannel("A").point(lambda v: int(v * 0.55)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        shadow.alpha_composite(img)
        return shadow

    def active(self, t):
        return self.start <= t <= self.end + 0.6

    def draw(self, canvas, t):
        """canvas: RGBA PIL 画像（背景レイヤー）に描画。背景の暗さ係数を返す。"""
        if not self.active(t):
            return 0.0
        u = t - self.start
        fade_in = ease_out_cubic(u / 0.6)
        fade_out = 1 - clamp((t - self.end) / 0.6)
        a = self.opacity * fade_in * fade_out
        scale = 1.35 - 0.35 * ease_out_cubic(u / 0.8) - 0.02 * u  # 迫ってくる→ゆっくりズームアウト
        lw, lh = self.layer.size
        img = self.layer.resize((int(lw * scale), int(lh * scale)), Image.BICUBIC)
        alpha = img.getchannel("A").point(lambda v: int(v * a))
        img.putalpha(alpha)
        canvas.alpha_composite(img, (int((W - img.width) / 2), int(H * self.y - img.height / 2)))
        return self.dim * fade_in * fade_out


# ---------------------------------------------------------------- テロップ
STAGGER = 0.045   # 1文字ごとの遅れ
LAND = 0.55       # 着地までの時間
EXIT = 0.2


def parse_segments(text):
    """'原因は{頭皮の乾燥}' → [('原因は', False), ('頭皮の乾燥', True)]"""
    segs, buf, emph = [], "", False
    for ch in text:
        if ch in "{}":
            if buf:
                segs.append((buf, emph))
            buf, emph = "", ch == "{"
        else:
            buf += ch
    if buf:
        segs.append((buf, emph))
    return segs


@lru_cache(maxsize=4096)
def glyph(ch, size, color, stroke):
    f = font(FONT_BLACK, size)
    pad = stroke + 16
    w = int(f.getlength(ch)) + pad * 2
    h = int(size * 1.45) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 影
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((pad + 4, pad + 8), ch, font=f, fill=(0, 0, 0, 150),
                                stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    d.text((pad, pad), ch, font=f, fill=color + (255,), stroke_width=stroke, stroke_fill=INK + (255,))
    return img, pad


class Telop:
    def __init__(self, cfg):
        self.start, self.end = cfg["start"], cfg["end"]
        self.base = cfg.get("size", 100)
        self.y = int(H * cfg.get("y", 0.64))
        self.lines = [self._layout(line) for line in cfg["text"].split("\n")]

    def _layout(self, line):
        chars = []
        for seg, emph in parse_segments(line):
            size = int(self.base * (1.45 if emph else 1.0))
            for ch in seg:
                chars.append([ch, size, emph])
        width = sum(font(FONT_BLACK, s).getlength(c) for c, s, _ in chars)
        k = min(1.0, SAFE_W / max(width, 1))  # 安全エリアに収まるよう自動縮小
        for c in chars:
            c[1] = int(c[1] * k)
        return chars

    def draw(self, canvas, t):
        if not (self.start <= t <= self.end):
            return
        out = clamp((t - (self.end - EXIT)) / EXIT)
        heights = [max(s for _, s, _ in l) for l in self.lines]
        total_h = sum(int(h * 1.18) for h in heights)
        y = self.y - total_h / 2
        idx = 0
        for line, lh in zip(self.lines, heights):
            widths = [font(FONT_BLACK, s).getlength(c) for c, s, _ in line]
            x = SAFE_CX - sum(widths) / 2
            baseline = y + lh  # 文字下端を揃える
            for (ch, size, emph), cw in zip(line, widths):
                self._char(canvas, t, idx, ch, size, emph, x + cw / 2, baseline, out)
                x += cw
                idx += 1
            y += int(lh * 1.18)

    def _char(self, canvas, t, i, ch, size, emph, cx, baseline, out):
        u = (t - self.start - i * STAGGER) / LAND
        if u <= 0 or ch == " ":
            return
        # 下から飛び出して、行き過ぎてから跳ねて着地（減衰バネ）
        k = u * LAND
        dy = 110 * math.exp(-7 * k) * math.cos(13 * k)
        scale = 1 - 0.75 * math.exp(-7 * k) * math.cos(12 * k)
        if emph:
            scale *= 1 + 0.12 * math.exp(-5 * max(0, k - 0.25)) * (k > 0.25)
        alpha = clamp(u * 4) * (1 - out)
        scale *= 1 - 0.15 * out
        dy -= 40 * ease_out_cubic(out)
        color = lerp_color(WHITE, GOLD, clamp((u - 0.35) / 0.4)) if emph else WHITE
        stroke = max(5, size // 11)
        g, pad = glyph(ch, size, color, stroke)
        sw, sh = max(1, int(g.width * scale)), max(1, int(g.height * scale))
        if scale != 1:
            g = g.resize((sw, sh), Image.BILINEAR)
        if alpha < 1:
            g = g.copy()
            g.putalpha(g.getchannel("A").point(lambda v: int(v * alpha)))
        top = baseline - (size * 1.3 + pad) * scale + dy
        canvas.alpha_composite(g, (int(cx - sw / 2), int(top)))


# ---------------------------------------------------------------- CTA
class CTA:
    def __init__(self, cfg, duration):
        s = cfg.get("start", -3.5)
        self.start = duration + s if s < 0 else s
        self.text = cfg.get("text", "保存してカウンセリングで見せてね")
        self.y = int(H * cfg.get("y", 0.70))
        self.banner = self._render()

    def _render(self):
        lines = self.text.split("\n")
        f = font(FONT_XBOLD, 70)
        tw = max(f.getlength(l) for l in lines)
        while tw > SAFE_W - 150:
            f = font(FONT_XBOLD, f.size - 2)
            tw = max(f.getlength(l) for l in lines)
        lh = int(f.size * 1.22)
        bw, bh = int(tw + 150), max(150, lh * len(lines) + 60)
        pad = 40
        img = Image.new("RGBA", (bw + pad * 2, bh + pad * 2), (0, 0, 0, 0))
        # 影
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 10, pad + bw, pad + bh + 10), 75, fill=(0, 0, 0, 140))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
        # ゴールドのグラデーション
        grad = Image.new("RGBA", (bw, bh))
        gd = ImageDraw.Draw(grad)
        for yy in range(bh):
            gd.line([(0, yy), (bw, yy)], fill=lerp_color((255, 222, 110), GOLD_DEEP, yy / bh) + (255,))
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), 75, fill=255)
        img.paste(grad, (pad, pad), mask)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((pad, pad, pad + bw, pad + bh), 75, outline=(255, 255, 255, 255), width=5)
        # 保存（ブックマーク）アイコン
        ix, iy = pad + 58, pad + bh // 2
        d.polygon([(ix - 24, iy - 36), (ix + 24, iy - 36), (ix + 24, iy + 36), (ix, iy + 16), (ix - 24, iy + 36)],
                  fill=INK + (255,))
        tx = pad + 110
        for i, l in enumerate(lines):
            ly = pad + bh / 2 + (i - (len(lines) - 1) / 2) * lh
            d.text((tx + (tw - f.getlength(l)) / 2, ly), l, font=f, fill=INK + (255,), anchor="lm")
        return img

    def _arrow_frame(self, w, h, phase):
        """バナーを囲む矢印枠（下向き矢印つき）。phase 0..1 で波紋のように広がる"""
        img = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, cy = W // 2, 160
        grow = 14 + 36 * phase
        a = int(255 * (1 - phase))
        d.rounded_rectangle((cx - w / 2 - grow, cy - h / 2 - grow, cx + w / 2 + grow, cy + h / 2 + grow),
                            int(h / 2 + grow), outline=(255, 255, 255, a), width=6)
        return img

    def draw(self, canvas, t):
        if t < self.start:
            return
        u = t - self.start
        appear = ease_out_back(u / 0.6, 2.2)
        alpha = clamp(u / 0.35)
        pulse = 1 + 0.055 * math.sin(2 * math.pi * 1.4 * max(0, u - 0.6))
        scale = (0.4 + 0.6 * appear) * pulse
        b = self.banner
        bw, bh = int(b.width * scale), int(b.height * scale)
        img = b.resize((bw, bh), Image.BICUBIC)
        if alpha < 1:
            img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
        cx = SAFE_CX
        # 波紋の枠
        if u > 0.5:
            for k in range(2):
                ph = ((u - 0.5) * 0.9 + k * 0.5) % 1.0
                fr = self._arrow_frame(self.banner.width - 80, self.banner.height - 80, ph)
                canvas.alpha_composite(fr, (cx - W // 2, self.y - 160))
        canvas.alpha_composite(img, (int(cx - bw / 2), int(self.y - bh / 2)))
        # 跳ねる下向き矢印（保存ボタンへ誘導）
        if u > 0.35:
            bounce = abs(math.sin(2 * math.pi * 1.4 * u)) * 22
            ay = self.y + self.banner.height / 2 - 34 + bounce
            d = ImageDraw.Draw(canvas)
            for j, ax in enumerate((cx - 80, cx, cx + 80)):
                aa = int(255 * clamp((u - 0.35) / 0.3) * (0.55 + 0.45 * (j == 1)))
                pts = [(ax - 34, ay), (ax + 34, ay), (ax, ay + 38)]
                d.polygon(pts, fill=(255, 255, 255, aa), outline=INK + (aa,))


# ---------------------------------------------------------------- 本体
def probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def has_audio(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a",
                                   "-show_entries", "stream=index", "-of", "csv=p=0", str(path)])
    return bool(out.strip())


def guides(canvas):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    red = (255, 0, 0, 70)
    d.rectangle((0, 0, W, SAFE_TOP), fill=red)
    d.rectangle((0, SAFE_BOTTOM, W, H), fill=red)
    d.rectangle((SAFE_RIGHT, SAFE_TOP, W, SAFE_BOTTOM), fill=red)
    canvas.alpha_composite(ov)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--guides", action="store_true", help="UI 被り禁止ゾーンを表示")
    ap.add_argument("--no-cutout", action="store_true", help="人物切り抜きを使わない")
    ap.add_argument("--stills", help="指定秒のフレームを PNG 書き出し（例: 1,3,8）")
    args = ap.parse_args()

    cfg = json.loads(Path(args.script).read_text(encoding="utf-8"))
    duration = cfg.get("duration") or probe_duration(args.input)
    bg = BigBackText(cfg["background_text"]) if cfg.get("background_text") else None
    telops = [Telop(c) for c in cfg.get("telops", [])]
    cta = CTA(cfg.get("cta", {}), duration) if cfg.get("cta", {}) is not None else None
    masker = None if args.no_cutout else PersonMasker()
    stills = {round(float(s) * FPS) for s in args.stills.split(",")} if args.stills else set()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", args.input, "-t", str(duration),
         "-vf", f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc_cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if has_audio(args.input):
        enc_cmd += ["-i", args.input, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    enc_cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out_path)]
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

    n = 0
    fsize = W * H * 3
    while True:
        raw = dec.stdout.read(fsize)
        if len(raw) < fsize:
            break
        t = n / FPS
        frame = np.frombuffer(raw, np.uint8).reshape(H, W, 3)

        # 背景レイヤー：元映像 + 背面巨大文字
        back = Image.fromarray(frame).convert("RGBA")
        dim = bg.draw(back, t) if bg else 0.0
        if masker is not None:
            mask = masker(frame, t * 1000)
            b = np.asarray(back, dtype=np.float32)[..., :3]
            if dim:
                # 背面文字を目立たせるため、背景だけ少し暗くする
                b *= 1 - dim * (1 - mask)
            comp = b * (1 - mask) + frame.astype(np.float32) * mask
            canvas = Image.fromarray(comp.clip(0, 255).astype(np.uint8)).convert("RGBA")
        else:
            canvas = back

        for tp in telops:
            tp.draw(canvas, t)
        if cta:
            cta.draw(canvas, t)
        if args.guides:
            guides(canvas)

        rgb = canvas.convert("RGB")
        if n in stills:
            rgb.save(out_path.with_name(f"{out_path.stem}_{t:05.2f}s.png"))
        enc.stdin.write(rgb.tobytes())
        n += 1
        if n % 60 == 0:
            print(f"\r{t:6.1f}s / {duration:.1f}s", end="", flush=True)

    enc.stdin.close()
    enc.wait()
    dec.wait()
    if masker is not None:
        masker.seg.close()
    print(f"\n書き出し完了: {out_path} ({n} frames)")


if __name__ == "__main__":
    main()
