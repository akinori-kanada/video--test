#!/usr/bin/env bash
# 初回セットアップ：フォント取得・効果音生成・Pythonライブラリ確認
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p assets/fonts assets/sfx assets/bgm input out

if [ ! -s assets/fonts/NotoSansJP.ttf ]; then
  echo "フォント(Noto Sans JP / OFL)を取得..."
  curl -fsSL -o assets/fonts/NotoSansJP.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
fi

if [ ! -s assets/sfx/shutter.wav ]; then
  echo "シャッター音を生成..."
  ffmpeg -v error -y -f lavfi -i "anoisesrc=d=0.09:c=white:a=0.9" \
    -f lavfi -i "anoisesrc=d=0.07:c=pink:a=0.7" \
    -filter_complex "[0]highpass=f=1800,afade=t=out:st=0.01:d=0.08[a];[1]bandpass=f=900,adelay=70,afade=t=out:st=0.08:d=0.06[b];[a][b]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo" \
    -ar 48000 assets/sfx/shutter.wav
fi

python3 -c "import PIL, yaml" 2>/dev/null || pip install pillow pyyaml
command -v ffmpeg >/dev/null || { echo "ffmpeg をインストールしてください"; exit 1; }
echo "OK"
