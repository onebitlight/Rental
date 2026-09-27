#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# ==============================================
# 🎛️ 房源抓取全局开关 (改成 false 即可关闭对应抓取)
# ==============================================
ENABLE_STAN=true   # 是否开启【公寓】抓取与渲染
ENABLE_KUCA=true   # 是否开启【独栋/别墅】抓取与渲染

# 同时也支持命令行参数控制：
# bash run_all.sh stan  -> 仅运行公寓
# bash run_all.sh kuca  -> 仅运行独栋
# bash run_all.sh       -> 读取上方 ENABLE 开关配置
MODE="${1:-all}"

echo "=============================================="
echo "🚀 贝尔格莱德房源自动化管线启动 [模式: $MODE]"
echo "=============================================="

# --- 1. 公寓 (Stan) 流程 ---
if [ "$MODE" = "all" ] || [ "$MODE" = "stan" ]; then
    if [ "$ENABLE_STAN" = true ] || [ "$MODE" = "stan" ]; then
        echo "🏠 [1/2] 正在运行【公寓 (Stan)】抓取与渲染..."
        python3 scraper_stan.py
        python3 card_render.py stan
    else
        echo "⏸️ [1/2] 【公寓 (Stan)】抓取已全局关闭 (ENABLE_STAN=false)，跳过。"
    fi
fi

echo ""

# --- 2. 独栋/别墅 (Kuca) 流程 ---
if [ "$MODE" = "all" ] || [ "$MODE" = "kuca" ]; then
    if [ "$ENABLE_KUCA" = true ] || [ "$MODE" = "kuca" ]; then
        if [ -f "scraper_kuca.py" ]; then
            echo "🏡 [2/2] 正在运行【独栋/别墅 (Kuca)】抓取与渲染..."
            python3 scraper_kuca.py
            python3 card_render.py kuca
        else
            echo "⚠️ [2/2] 未找到 scraper_kuca.py，跳过独栋抓取。"
        fi
    else
        echo "⏸️ [2/2] 【独栋/别墅 (Kuca)】抓取已全局关闭 (ENABLE_KUCA=false)，跳过。"
    fi
fi

echo ""
echo "✨ 执行完成！"
