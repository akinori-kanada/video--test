#!/usr/bin/env python3
"""投稿文（Instagram / YouTubeショート / TikTok）を検証データから生成し、レギュレーションを自動チェック

  python3 tools/captions.py posts_a.yaml
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compliance import lint_post, report  # noqa: E402
from render import ROOT, build_context, subst  # noqa: E402

LIMITS = {"instagram": 2200, "youtube": 5000, "tiktok": 4000, "youtube_title": 100}
LABELS = {"instagram": "Instagram リール", "youtube_title": "YouTube ショート（タイトル）",
          "youtube": "YouTube ショート（説明文）", "tiktok": "TikTok"}
SETTINGS = {
    "instagram": "投稿前に「タイアップ投稿ラベル」でFitlogのアカウントを指定",
    "youtube": "詳細設定の「有料プロモーションを含む」にチェック",
    "tiktok": "「コンテンツの開示設定」→「ブランドコンテンツ」をオン",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("posts")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / args.posts).read_text())
    data = yaml.safe_load((ROOT / cfg["data"]).read_text())
    ctx = build_context(data)
    ctx["result_line"] = subst(cfg.get("result_line", ""), ctx)

    issues, blocks = [], []
    if data.get("sample"):
        blocks.append("！！ data が sample: true のまま（数値はサンプル）。投稿には使わないでください ！！\n")
    for key in ["instagram", "youtube_title", "youtube", "tiktok"]:
        if key not in cfg:
            continue
        text = subst(cfg[key], ctx).strip()
        n = len(text)
        over = f"  ※上限{LIMITS[key]}字を超過" if n > LIMITS[key] else ""
        if key != "youtube_title":
            issues += lint_post(LABELS[key], text)
        else:
            from compliance import lint_text
            issues += lint_text(text, LABELS[key])
        head = f"■ {LABELS[key]}（{n}字）{over}"
        if key in SETTINGS:
            head += f"\n  [設定] {SETTINGS[key]}"
        blocks.append(f"{head}\n{'-' * 40}\n{text}\n")

    out = ROOT / cfg.get("output", "out/posts.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(blocks))
    errors = report(issues, "投稿文チェック")
    print(f"done: {out.relative_to(ROOT)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
