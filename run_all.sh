#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================="
echo "🚀 [1/2] 开始运行公寓 (Stan) 抓取与渲染..."
echo "=========================================="
python3 scraper_stan.py
python3 card_render.py stan

echo ""
echo "=========================================="
echo "🚀 [2/2] 开始运行独栋 (Kuca) 抓取与渲染..."
echo "=========================================="
if [ -f "scraper_kuca.py" ]; then
    python3 scraper_kuca.py
    python3 card_render.py kuca
fi

echo ""
echo "✨ 所有任务顺利完成！目录已完全隔离。"
