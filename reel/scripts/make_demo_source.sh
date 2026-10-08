#!/usr/bin/env bash
# 実際の撮影動画が無い場合の動作確認用：スクリーンショット4枚から
# ゆっくりズームする縦型の仮素材（無音・16秒）を作る
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p output
d=assets/demo
ffmpeg -y -loglevel error \
  -framerate 30 -loop 1 -t 4.4 -i $d/frame1.jpg -framerate 30 -loop 1 -t 4.4 -i $d/frame2.jpg \
  -framerate 30 -loop 1 -t 4.4 -i $d/frame3.jpg -framerate 30 -loop 1 -t 4.4 -i $d/frame4.jpg \
  -f lavfi -t 16 -i anullsrc=r=48000:cl=stereo \
  -filter_complex "\
[0]scale=1188:2112,zoompan=z='1+0.0008*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1[a];\
[1]scale=1188:2112,zoompan=z='1.06-0.0008*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1[b];\
[2]scale=1188:2112,zoompan=z='1+0.0008*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1[c];\
[3]scale=1188:2112,zoompan=z='1.06-0.0008*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1[e];\
[a][b]xfade=transition=fade:duration=0.4:offset=4.0[ab];\
[ab][c]xfade=transition=fade:duration=0.4:offset=8.0[abc];\
[abc][e]xfade=transition=fade:duration=0.4:offset=12.0,format=yuv420p[v]" \
  -map "[v]" -map 4:a -t 16 -c:v libx264 -crf 18 -c:a aac -shortest output/demo_source.mp4
echo "output/demo_source.mp4"
