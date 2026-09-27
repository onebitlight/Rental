import sys
import subprocess

def send():
    count = sys.argv[1] if len(sys.argv) > 1 else '7'
    url = sys.argv[2] if len(sys.argv) > 2 else 'https://real-availability-schedule-touch.trycloudflare.com'
    
    msg = f"🏠 贝尔格莱德好房精选 ({count}套)\n\n精选纯独栋/别墅房源已更新！\n点击查看详情：\n{url}"

    cmd = [
        'openclaw', 'agent',
        '--message', f'通过 openclaw-weixin 通道（账号 8c3c0f5ff3e3-im-bot），发送给 o9cq806ozJVWfuJaD2MrQ8sYqFdI@im.wechat 内容如下：\n{msg}'
    ]
    
    print('--- 正在触发 OpenClaw 微信推送 ---')
    res = subprocess.run(cmd, capture_output=True, text=True)
    print('STDOUT:', res.stdout)
    if res.stderr:
        print('STDERR:', res.stderr)

if __name__ == '__main__':
    send()
