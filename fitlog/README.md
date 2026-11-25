# Fitlog PR動画 自動編集テンプレート

YAMLの構成表と検証データから、テロップ・比較表・字幕つきの縦動画（1080×1920 / 30fps / -14 LUFS）を書き出します。

## セットアップ（初回だけ）
```bash
cd fitlog
bash tools/setup.sh      # フォント取得・シャッター音生成
```
必要なもの：ffmpeg、Python 3 + Pillow + PyYAML

## 使い方
```bash
python3 tools/render.py project_a.yaml --preview     # 確認用（速い）
python3 tools/render.py project_a.yaml               # 本番 → out/fitlog_A_v1.mp4
python3 tools/render.py project_a.yaml --only result # 1カットだけ確認
```
素材が無いカットは「素材待ち」の画面になるので、素材がそろう前でも尺やテロップの確認ができます。

## 素材の置き場所とファイル名（input/）
| ファイル | 内容 | 長さの目安 |
|---|---|---|
| `A01_rice_scale.mov` | 白米をはかりに乗せる手元（150.0g表示） | 4〜6秒 |
| `A02_face_intro.mov` | 本人「写真1枚でどこまで合うのか、ガチで検証します」 | 3〜5秒 |
| `A03_manual_weighing.mov` | いつもの計量→入力（4倍速になります） | 20秒〜（実際の作業をそのまま） |
| `A03_vo.m4a` | （任意）早回しにかぶせるナレーション | 5秒 |
| `A04_shoot_hands.mov` | 定食をFitlogで撮る手元（三脚・別アングル） | 5〜10秒 |
| `A05_fitlog_screenrec.mp4` | ★Fitlogの画面録画：撮影→結果表示 | 10〜20秒 |
| `A05_vo.m4a` / `A06_vo.m4a` | （任意）結果画面・比較表にかぶせるナレーション | 6秒 / 8秒 |
| `A07_face_verdict.mov` | 本人の正直な評価 | 6〜8秒 |
| `A08_face_cta.mov` | 本人「プロフィールのリンクから。紹介コードはKANADA」 | 6秒 |
| `assets/bgm/bgm.mp3` | （任意）商用利用OKのBGM | 40秒以上 |

ファイル名を変えたいときは `project_a.yaml` の `src` を書き換えます。各カットの使い始めは `in`（秒）で指定します。

## 数値の差し替え
`data/meal1.yaml` に、実測値（1品ずつ）とFitlogの結果画面の数値を入れてください。比較表・差分・テロップ・字幕に自動で反映されます。
入力が終わったら `sample: false` に変えると、透かし「SAMPLE DATA」が消えます。

## 編集の調整（project_a.yaml）
- テロップの文言・出るタイミング・位置：`telops` の `text` / `start` / `pos`
- 強調表示（黄色）：`*ここ*`　データの差し込み：`${fitlog.kcal}` `${diff.kcal}` `${manual_time}` など
- 演出の種類：`pop`（弾む）`stamp`（押印）`slide`（横から）`type`（1文字ずつ）`countup`（数字が増える）
- 結果画面のズーム：`zoom: {at: 2.0, scale: 1.45, cx: 0.5, cy: 0.35}`（注目させたい数値の位置に `cx`,`cy` を合わせる）
