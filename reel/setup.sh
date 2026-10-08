#!/usr/bin/env bash
# 依存パッケージ・フォント・人物切り抜きモデルを取得する
set -euo pipefail
cd "$(dirname "$0")"
command -v apt-get >/dev/null && ! ldconfig -p | grep -q libEGL.so.1 && apt-get install -y -q libegl1 libgles2 || true
pip install -q mediapipe opencv-python-headless pillow numpy
mkdir -p fonts models
if [ ! -f fonts/NotoSansJP-Black.ttf ]; then
  tmp=$(mktemp -d)
  (cd "$tmp" && npm pack -q @expo-google-fonts/noto-sans-jp@0.4.4 >/dev/null && tar xzf ./*.tgz)
  cp "$tmp/package/900Black/NotoSansJP_900Black.ttf" fonts/NotoSansJP-Black.ttf
  cp "$tmp/package/800ExtraBold/NotoSansJP_800ExtraBold.ttf" fonts/NotoSansJP-ExtraBold.ttf
  cp "$tmp/package/LICENSE_FONT" fonts/OFL.txt
  rm -rf "$tmp"
fi
if [ ! -f models/selfie_multiclass.tflite ]; then
  curl -sSL -o models/selfie_multiclass.tflite \
    https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite
fi
echo "setup done"
