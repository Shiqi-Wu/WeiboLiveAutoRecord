import subprocess
import time
import threading
import json
import os
from requests_html import HTMLSession
from datetime import datetime, timezone, timedelta
import sys

# 解决 Unicode 输出问题
sys.stdout.reconfigure(encoding='utf-8')

# 读取配置文件
CONFIG_FILE = "config.json"

def load_config():
    """从 config.json 读取配置"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# 从配置文件加载参数
uid = config["uid"]
cookies = config["cookies"]
check_interval = config["check_interval"]
save_dir = config["save_dir"]

# 确保保存目录存在
os.makedirs(save_dir, exist_ok=True)

# 微博 API 地址
api_url = f'https://weibo.com/ajax/statuses/mymblog?uid={uid}'

def create_session():
    """创建 HTMLSession 以访问微博 API"""
    return HTMLSession()

def check_weibo_live(api_url, cookies):
    """检查微博是否有最近 10 分钟内的新直播，并返回直播流 URL"""
    global session  
    try:
        response = session.get(api_url, cookies=cookies)
        response.encoding = 'utf-8'
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API 状态码: {response.status_code}")

        if response.status_code != 200:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API 请求失败，尝试重新创建 session...")
            session = create_session()
            return None

        # **手动解析 JSON，避免编码错误**
        data = response.content.decode('utf-8')  # 这里手动用 UTF-8 解析
        data = json.loads(data)  # 解析 JSON

        weibo_list = data.get('data', {}).get('list', [])

        for weibo in weibo_list:
            created_at = weibo.get('created_at', '')
            media_info = weibo.get('page_info', {}).get('media_info', {})

            if not (is_recent(created_at) and 'live_ld' in media_info):
                continue

            live_stream_url = media_info['live_ld'].replace('.m3u8', '.flv')
            return live_stream_url

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 访问 API 出错: {e}")
        session = create_session()  # 重新创建 session，避免请求失败后死循环

    return None

def is_recent(date_str):
    """判断微博发布时间是否在最近 10 分钟内"""
    if not date_str:
        return False
    try:
        weibo_time = datetime.strptime(date_str, '%a %b %d %H:%M:%S %z %Y')
        weibo_time = weibo_time.astimezone(timezone.utc)  # 转换为 UTC 时间
        now = datetime.now(timezone.utc)
        return (now - weibo_time) <= timedelta(minutes=10)
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 日期解析出错: {e}")
        return False

def record_live_stream(stream_url):
    """使用 Streamlink 录制直播流"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = os.path.join(save_dir, f"{uid}-{timestamp}.mp4")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始录制: {output_filename}")

    command = ["streamlink", stream_url, "best", "-o", output_filename]
    
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def monitor_streamlink(process):
            """监控 streamlink 进程，确保不会卡住"""
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                line_str = line.decode("utf-8")
                print(line_str, end="")

                # 监测错误信息
                if "No playable streams found" in line_str or "error" in line_str.lower():
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 直播结束或出错，停止录制")
                    process.kill()
                    break

        monitor_thread = threading.Thread(target=monitor_streamlink, args=(process,))
        monitor_thread.start()

        process.wait()
        monitor_thread.join()

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 录制出错: {e}")

# 运行主循环
session = create_session()

while True:
    live_stream_url = check_weibo_live(api_url, cookies)

    if live_stream_url:
        record_live_stream(live_stream_url)
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 没有发现直播，等待 {check_interval} 秒后重新检测...")

    time.sleep(check_interval)