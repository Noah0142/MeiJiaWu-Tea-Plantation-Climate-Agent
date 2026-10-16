#!/bin/bash
export PATH="/c/Hackthon/AI4Climate/.tools:$PATH"
cd /c/Hackthon/AI4Climate/docs/promo/film3
for i in 0 1 2 3 4 5 6; do
  echo "=== seg $i ==="
  python /tmp/onetake/scripts/render.py "comp3.html?seg=$i" --out "seg$i.mp4" --crf 17 --workers 7 --samples-max 8 2>&1 | tail -2
done
echo "ALL_SEGMENTS_DONE"
