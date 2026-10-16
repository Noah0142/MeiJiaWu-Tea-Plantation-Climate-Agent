#!/bin/bash
export PATH="/c/Hackthon/AI4Climate/.tools:$PATH"
cd /c/Hackthon/AI4Climate/docs/promo/film3
rm -f seg*.mp4
for i in 0 1 2 3 4 5 6; do
  echo "=== seg $i ==="
  python /tmp/onetake/scripts/render.py "comp3.html?seg=$i" --out "seg$i.mp4" --crf 17 --workers 6 --samples-max 8 2>&1 | tail -3
  if [ ! -f "seg$i.mp4" ]; then echo "RETRY seg $i"; python /tmp/onetake/scripts/render.py "comp3.html?seg=$i" --out "seg$i.mp4" --crf 17 --workers 4 --samples-max 8 2>&1 | tail -3; fi
done
printf "file 'seg0.mp4'\nfile 'seg1.mp4'\nfile 'seg2.mp4'\nfile 'seg3.mp4'\nfile 'seg4.mp4'\nfile 'seg5.mp4'\nfile 'seg6.mp4'\n" > list.txt
ffmpeg -v error -y -f concat -safe 0 -i list.txt -i sfx3.wav -c:v copy -c:a aac -b:a 160k -shortest film3.mp4
echo "BUILD_DONE"; ls -la film3.mp4
