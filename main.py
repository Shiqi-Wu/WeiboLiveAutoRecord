import subprocess
import time
import threading
from requests_html import HTMLSession
from datetime import datetime

uid = '1696708922'  #被监控的微博账号的UID
check_interval = 20  # 检查间隔（秒）

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.140 Safari/537.36 Edge/17.17134',
    'Referer': 'https://weibo.com/'
}

cookies = {
    # 在这里填入你的微博Cookie
    'SUB': '微博Cookie的SUB信息',
    'SUBP': '微博Cookie的SUBP信息',
}

# 获取当前日期
current_date = datetime.now().date()

api_url = f'https://weibo.com/ajax/statuses/mymblog?uid={uid}'

def create_session():
    return HTMLSession()

def check_weibo_live(api_url, cookies):
    response = session.get(api_url, cookies=cookies)
    print(f"被监测的微博账号UID： {uid}")  # 打印被监测的微博账号UID
    print(f"当前微博API状态码: {response.status_code}")  # 打印状态码
    if response.status_code == 200:
        data = response.json()
        if 'data' in data and 'list' in data['data']:
            for weibo in data['data']['list']:
                created_at = weibo.get('created_at', '')
                if is_today(created_at) and 'page_info' in weibo and 'media_info' in weibo['page_info']:
                    media_info = weibo['page_info']['media_info']
                    if 'live_ld' in media_info:
                        live_stream_url = media_info['live_ld']
                        if live_stream_url:
                            live_stream_url = live_stream_url.replace('.m3u8', '.flv')
                            return live_stream_url
    return None

#检测直播微博发起的时间，避免抓取已经结束直播的微博
def is_today(date_str):
    if not date_str:
        return False
    # 解析微博时间字符串
    weibo_date = datetime.strptime(date_str, '%a %b %d %H:%M:%S %z %Y')
    # 转换为本地时间
    weibo_date = weibo_date.astimezone()
    # 获取当前日期
    today = datetime.now().astimezone().date()
    return weibo_date.date() == today

def record_live_stream(stream_url):
    print(f"直播流地址: {stream_url}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{uid}-{timestamp}.mp4"
    
    print(f"开始录制，文件名为: {output_filename}")
    command = f'ffmpeg -i "{stream_url}" -c copy -movflags faststart "{output_filename}"'
    process = subprocess.Popen(command, shell=True, stderr=subprocess.PIPE)

    def monitor_ffmpeg(process):  #检测ffmpeg运行状态
        while True:
            line = process.stderr.readline()
            if not line:
                break
            line_str = line.decode('utf-8')
            print(line_str, end='')
            if "HTTP error 404 Not Found" in line_str:
                print("直播结束，停止录制")
                process.kill()
                break

    monitor_thread = threading.Thread(target=monitor_ffmpeg, args=(process,))
    monitor_thread.start()

    process.wait()
    monitor_thread.join()
    
# 主循环
session = create_session()  # 创建一个新的会话
while True:
    live_stream_url = check_weibo_live(api_url, cookies)
    if live_stream_url:
        print(f'发现直播，流地址: {live_stream_url}')
        record_live_stream(live_stream_url)
        print('回到检测状态...')
        print(f"---------------------------------------")
        session = create_session()  
    else:
        print('没有发现直播，等待中...')
        print(f"---------------------------------------")
    time.sleep(check_interval)