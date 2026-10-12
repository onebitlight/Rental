#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# ==============================================
# 🎛️ 房源抓取全局开关 (改成 false 即可关闭对应抓取)
# ==============================================
ENABLE_STAN=true   # 是否开启【公寓】抓取与渲染 (与 scraper_stan.py 的 ENABLE_STAN_SCRAPER=True 保持一致)
ENABLE_KUCA=true   # 是否开启【独栋/别墅】抓取与渲染
ENABLE_LOKAL=true  # 是否开启【商铺】抓取与渲染

# 同时也支持命令行参数控制：
# bash run_all.sh stan  -> 仅运行公寓
# bash run_all.sh kuca  -> 仅运行独栋
# bash run_all.sh lokal -> 仅运行商铺
# bash run_all.sh       -> 读取上方 ENABLE 开关配置
MODE="${1:-all}"

echo "=============================================="
echo "🚀 贝尔格莱德房源自动化管线启动 [模式: $MODE]"
echo "=============================================="

# --- 1. 公寓 (Stan) 流程 ---
if [ "$MODE" = "all" ] || [ "$MODE" = "stan" ]; then
    if [ "$ENABLE_STAN" = true ] || [ "$MODE" = "stan" ]; then
        echo "🏠 [1/4] 正在运行【公寓 (Stan)】抓取与渲染..."
        python3 scraper_stan.py
        python3 card_render.py stan
    else
        echo "⏸️ [1/4] 【公寓 (Stan)】抓取已全局关闭 (ENABLE_STAN=false)，跳过。"
    fi
fi

echo ""

# --- 2. 独栋/别墅 (Kuca) 流程 ---
if [ "$MODE" = "all" ] || [ "$MODE" = "kuca" ]; then
    if [ "$ENABLE_KUCA" = true ] || [ "$MODE" = "kuca" ]; then
        if [ -f "scraper_kuca.py" ]; then
            echo "🏡 [2/4] 正在运行【独栋/别墅 (Kuca)】抓取与渲染..."
            python3 scraper_kuca.py
            python3 card_render.py kuca
        else
            echo "⚠️ [2/4] 未找到 scraper_kuca.py，跳过独栋抓取。"
        fi
    else
        echo "⏸️ [2/4] 【独栋/别墅 (Kuca)】抓取已全局关闭 (ENABLE_KUCA=false)，跳过。"
    fi
fi

# --- 3. 商铺 (Lokal) 流程 ---
if [ "$MODE" = "all" ] || [ "$MODE" = "lokal" ]; then
    if [ "$ENABLE_LOKAL" = true ] || [ "$MODE" = "lokal" ]; then
        if [ -f "scraper_lokal.py" ]; then
            echo "🏪 [3/4] 正在运行【商铺 (Lokal)】抓取与渲染..."
            python3 scraper_lokal.py
            python3 card_render.py lokal
        else
            echo "⚠️ [3/4] 未找到 scraper_lokal.py，跳过商铺抓取。"
        fi
    else
        echo "⏸️ [3/4] 【商铺 (Lokal)】抓取已全局关闭 (ENABLE_LOKAL=false)，跳过。"
    fi
fi

echo ""

# --- 4. 统一汇总推送 (单条消息包含公寓+独栋+商铺) ---
echo "📨 [4/4] 检查推送状态..."

KUCA_PENDING="$DIR/data/push_pending.json"
STAN_PENDING="$DIR/data/new_items.json"
LOKAL_PENDING="$DIR/data/lokal_items.json"

python3 -c "
import json, pathlib
from send_wechat import push_daily_summary

def load_items(filepath):
    p = pathlib.Path(filepath)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding='utf-8'))
    # Handle both plain lists and {meta, items} wrapped objects
    if isinstance(data, dict):
        return data.get('items', data)
    return data

stan_items = load_items('${STAN_PENDING}')
kuca_items = load_items('${KUCA_PENDING}')
lokal_items = load_items('${LOKAL_PENDING}')

total = len(stan_items) + len(kuca_items) + len(lokal_items)
print(f'汇总: 公寓 {len(stan_items)} 套 + 独栋 {len(kuca_items)} 套 + 商铺 {len(lokal_items)} 套 = 共 {total} 套')

push_daily_summary(stan_items=stan_items, kuca_items=kuca_items, lokal_items=lokal_items)
"

echo ""
echo "✨ 执行完成！"
