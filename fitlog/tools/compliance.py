"""案件レギュレーションの自動チェック（render.py / captions.py から呼ぶ）

- NG表現（効果・効能の断定）の検出
- 必須シーン（Fitlogの結果画面）の有無
- 投稿文：先頭の #PR / 専用URL / 紹介コード
"""
import re

REF_URL = "y7technology.com/fitlog/go/kanada"
REF_CODE = "KANADA"

# (パターン, レベル, 理由)  error=使わない / warn=裏付けや言い回しを確認
NG_RULES = [
    (r"痩せ|やせ[るたら]|ヤセ", "error", "「痩せる」系は効果の約束になる（案件NG）"),
    (r"ダイエット効果|減量効果|脂肪が(落ち|減)|燃焼|絞れ", "error", "体の変化を約束する表現"),
    (r"必ず|絶対|確実|誰でも|100\s*%|100％", "error", "断定表現"),
    (r"治る|改善する|健康にな", "error", "効能表現"),
    (r"正確|完璧|ピッタリ|誤差ゼロ", "warn", "精度の断定。検証結果で裏付けがある範囲だけに"),
    (r"最強|No\.?1|ナンバーワン|一番(正確|いい|良い)", "warn", "最上級表現。根拠がなければ避ける"),
    (r"\[[\w.]+\]|\$\{", "error", "未入力の差し込み（データが足りない）"),
]


def lint_text(text, where):
    out = []
    for pat, level, why in NG_RULES:
        for m in re.finditer(pat, text):
            out.append((level, where, m.group(0), why))
    return out


def lint_project(cfg, subst, root):
    """構成表のテロップ・字幕を検査。subst=差し込み関数"""
    issues = []
    total = 0.0
    has_result = False
    for seg in cfg.get("segments", []):
        sid = seg.get("id", "?")
        total += float(seg.get("dur", 0))
        texts = [t.get("text", "") for t in seg.get("telops", []) or [] if t.get("text")]
        if seg.get("caption"):
            texts.append(seg["caption"])
        for tx in texts:
            issues += lint_text(subst(tx).replace("*", ""), f"カット[{sid}]")
        if seg.get("must") == "fitlog_result":
            has_result = True
            if not seg.get("src") or not (root / seg["src"]).exists():
                issues.append(("warn", f"カット[{sid}]", seg.get("src", ""), "必須シーンの画面録画がまだ無い"))
    if not has_result:
        issues.append(("error", "構成", "", "Fitlogの結果画面（カロリー・PFC）のカットが無い（must: fitlog_result）"))
    if not 15 <= total <= 60:
        issues.append(("error", "構成", f"{total:.1f}秒", "尺は15〜60秒"))
    return issues


def lint_post(platform, text):
    issues = lint_text(text, f"投稿[{platform}]")
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    if not first.startswith("#PR"):
        issues.append(("error", f"投稿[{platform}]", first[:20], "説明文の一番最初は「#PR」"))
    if REF_URL not in text:
        issues.append(("warn", f"投稿[{platform}]", "", f"専用URLが無い（プロフィールに置くならOK）: {REF_URL}"))
    if f"紹介コード：{REF_CODE}" not in text and f"紹介コード:{REF_CODE}" not in text:
        issues.append(("warn", f"投稿[{platform}]", "", "「紹介コード：KANADA」が無い（動画内にあればOK）"))
    if "無料" in text and not ("はじめて" in text or "初めて" in text):
        issues.append(("warn", f"投稿[{platform}]", "無料", "特典の条件（はじめての方1回・カード不要・自動課金なし）も併記"))
    return issues


def report(issues, title="レギュレーションチェック"):
    errs = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warn"]
    print(f"── {title}: エラー {len(errs)} / 注意 {len(warns)}")
    for level, where, hit, why in errs + warns:
        mark = "✖" if level == "error" else "△"
        hit_s = f"「{hit}」" if hit else ""
        print(f"  {mark} {where} {hit_s} {why}")
    return len(errs)
