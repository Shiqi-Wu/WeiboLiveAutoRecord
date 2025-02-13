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
        return (now - weibo_time) <= timedelta(minutes=500)
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 日期解析出错: {e}")
        return False

def record_live_stream(stream_url):
    """使用 FFmpeg 录制直播流，每 1800 秒自动分段，文件命名格式为 {name}_时间戳_000.ts"""
    global current_process  # 记录 ffmpeg 进程

    # 从 config.json 读取 name
    name = config.get("name", "weibo_live")

    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 文件命名格式：{name}_{时间戳}_000.ts
    ts_filename_pattern = os.path.join(save_dir, f"{name}_{timestamp}_%03d.ts")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始录制，每 1800 秒分段: {ts_filename_pattern}")

    # FFmpeg 命令（分段录制）
    command = [
        "ffmpeg",
        "-i", stream_url,       # 输入直播流 URL
        "-c", "copy",           # 直接复制视频流，不重新编码
        "-f", "segment",        # 采用分段模式
        "-segment_time", "1800",  # 每 1800 秒（30 分钟）分段
        "-reset_timestamps", "1",  # 重置时间戳，防止时间轴错误
        "-segment_format", "mpegts",  # 保存为 .ts 文件
        ts_filename_pattern     # 输出文件路径
    ]

    try:
        # 启动 FFmpeg 进程
        current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def monitor_ffmpeg(process):
            """监控 FFmpeg 进程，确保不会卡住"""
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                line_str = line.decode("utf-8")
                print(line_str, end="")

                # 监测错误信息
                if "Error" in line_str or "failed" in line_str.lower():
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 直播结束或出错，停止录制")
                    process.terminate()
                    break

        # 启动监控线程
        monitor_thread = threading.Thread(target=monitor_ffmpeg, args=(current_process,))
        monitor_thread.start()

        # 等待 FFmpeg 进程完成
        current_process.wait()
        monitor_thread.join()

        # 录制完成后，自动转换 .ts → .mp4
        convert_ts_to_mp4(name, timestamp)

    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 录制出错: {e}")

def convert_ts_to_mp4(name, timestamp):
    """将分段 .ts 文件合并并转换为 .mp4"""
    ts_files = sorted([f for f in os.listdir(save_dir) if f.startswith(f"{name}_{timestamp}_") and f.endswith(".ts")])

    if not ts_files:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 没有找到 .ts 片段，跳过转换")
        return

    # 创建文件列表，供 FFmpeg 使用
    file_list_path = os.path.join(save_dir, f"{name}_{timestamp}_file_list.txt")
    with open(file_list_path, "w") as f:
        for ts in ts_files:
            f.write(f"file '{os.path.join(save_dir, ts)}'\n")

    # 目标 .mp4 文件名
    output_mp4 = os.path.join(save_dir, f"{name}_{timestamp}.mp4")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始合并 .ts 片段，转换为 {output_mp4}")

    # FFmpeg 合并 .ts 片段
    command = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", file_list_path,
        "-c", "copy",
        output_mp4
    ]

    try:
        subprocess.run(command, check=True)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 成功转换 {output_mp4}")

        # 删除临时 .ts 片段
        for ts in ts_files:
            os.remove(os.path.join(save_dir, ts))
        os.remove(file_list_path)

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 删除 .ts 片段，完成转换")
    
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] .ts 转换 .mp4 失败: {e}")
        
def handle_exit(signum, frame):
    """处理 Ctrl + C (SIGINT) 以确保已录制的 .ts 文件不会损坏"""
    global current_process
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 手动终止，正在安全退出...")

    # 如果正在录制，先终止 FFmpeg 进程
    if current_process is not None:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 停止录制...")
        current_process.terminate()
        current_process.wait()
        time.sleep(2)  # 给 FFmpeg 时间写入数据
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 录制已安全终止.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 退出程序")
    sys.exit(0)

# 捕获 Ctrl + C
signal.signal(signal.SIGINT, handle_exit)

# 运行主循环
session = create_session()

while True:
    live_stream_url = check_weibo_live(api_url, cookies)

    if live_stream_url:
        record_live_stream(live_stream_url)
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 没有发现直播，等待 {check_interval} 秒后重新检测...")

    time.sleep(check_interval)