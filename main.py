import subprocess
import time
import threading
import json
import os
import signal
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

# 变量用于存储当前录制进程
current_process = None

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
        session = create_session()  

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
    """使用 FFmpeg 录制直播流，每 1800 秒自动分段"""
    global current_process  

    name = config.get("name", "weibo_live")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_filename_pattern = os.path.join(save_dir, f"{name}_{timestamp}_%03d.ts")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始录制，每 1800 秒分段: {ts_filename_pattern}")

    command = [
        "ffmpeg",
        "-i", stream_url,      
        "-c:v", "copy",        
        "-c:a", "aac",        
        "-b:a", "320k",        
        "-ar", "48000",        
        "-ac", "2",            
        "-f", "segment",
        "-segment_time", "1800", 
        "-reset_timestamps", "1",  
        "-segment_format", "mpegts",  
        "-avoid_negative_ts", "make_zero",
        ts_filename_pattern
    ]

    try:
        current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def monitor_ffmpeg(process):
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                line_str = line.decode("utf-8")
                print(line_str, end="")

                if "Error" in line_str or "failed" in line_str.lower():
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 直播结束或出错，停止录制")
                    process.terminate()
                    break

        monitor_thread = threading.Thread(target=monitor_ffmpeg, args=(current_process,))
        monitor_thread.start()

        current_process.wait()
        monitor_thread.join()

        convert_ts_to_mp4(name, timestamp)

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 录制出错: {e}")

def handle_exit(signum, frame):
    global current_process
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 手动终止，正在安全退出...")

    if current_process is not None:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 停止录制...")
        current_process.terminate()
        current_process.wait()
        time.sleep(2)  
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 录制已安全终止.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 退出程序")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)

session = create_session()

while True:
    live_stream_url = check_weibo_live(api_url, cookies)

    if live_stream_url:
        record_live_stream(live_stream_url)
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 没有发现直播，等待 {check_interval} 秒后重新检测...")

    time.sleep(check_interval)