import os
import re
import time
import requests
import threading
import queue
import subprocess
import ffmpeg
from urllib.parse import quote
from pyrogram import Client, filters
from datetime import datetime

# ========= 配置 =========
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

ALIST_URL = os.environ.get("ALIST_URL")
ALIST_USER = os.environ.get("ALIST_USER")
ALIST_PASS = os.environ.get("ALIST_PASS")
ALIST_PATH = os.environ.get("ALIST_PATH", "/videos/")
# ========================

# 全局转码队列和线程
transcode_queue = queue.Queue()
transcode_thread = None
transcode_lock = threading.Lock()

# 登录 Alist 获取 token
def alist_login():
    try:
        url = f"{ALIST_URL}/api/auth/login"
        resp = requests.post(url, json={"username": ALIST_USER, "password": ALIST_PASS}, timeout=30)
        resp.raise_for_status()
        return resp.json()["data"]["token"]
    except Exception as e:
        print(f"❌ Alist 登录失败: {e}")
        return None

# 转码工作线程
def transcode_worker():
    """转码工作线程，从队列中获取任务并执行"""
    while True:
        try:
            # 从队列获取转码任务
            task_data = transcode_queue.get()
            if task_data is None:  # 停止信号
                break
                
            input_path, output_path, task_id = task_data
            
            print(f"[{task_id}] 🔄 开始转码任务...")
            
            # 执行转码
            success = transcode_video(input_path, output_path, task_id)
            
            if success:
                # 转码成功后，继续后续处理
                print(f"[{task_id}] ✅ 转码完成，准备上传...")
                
                # 删除原始文件
                try:
                    os.remove(input_path)
                    print(f"[{task_id}] 🗑 已删除原始文件: {input_path}")
                except Exception as e:
                    print(f"[{task_id}] ⚠️ 删除原始文件失败: {e}")
                
                # 上传到Alist
                file_name = os.path.basename(input_path)
                if alist_upload(output_path, file_name, task_id):
                    # 上传成功后删除转码文件
                    try:
                        os.remove(output_path)
                        print(f"[{task_id}] 🗑 已删除转码文件: {output_path}")
                    except Exception as e:
                        print(f"[{task_id}] ⚠️ 删除转码文件失败: {e}")
                else:
                    # 上传失败也删除转码文件
                    try:
                        os.remove(output_path)
                        print(f"[{task_id}] 🗑 已删除转码文件 (上传失败): {output_path}")
                    except Exception as e:
                        print(f"[{task_id}] ⚠️ 删除转码文件失败: {e}")
            else:
                print(f"[{task_id}] ❌ 转码失败，跳过上传")
                # 转码失败时删除原始文件
                try:
                    os.remove(input_path)
                    print(f"[{task_id}] 🗑 已删除原始文件 (转码失败): {input_path}")
                except Exception as e:
                    print(f"[{task_id}] ⚠️ 删除原始文件失败: {e}")
            
            # 标记任务完成
            transcode_queue.task_done()
            
        except Exception as e:
            print(f"❌ 转码工作线程错误: {e}")

# 启动转码工作线程
def start_transcode_worker():
    """启动转码工作线程"""
    global transcode_thread
    with transcode_lock:
        if transcode_thread is None or not transcode_thread.is_alive():
            transcode_thread = threading.Thread(target=transcode_worker, daemon=True)
            transcode_thread.start()
            print("🔄 转码工作线程已启动")

# 转码文件（使用队列）
def queue_transcode_task(input_path, output_path, task_id):
    """将转码任务加入队列"""
    start_transcode_worker()
    transcode_queue.put((input_path, output_path, task_id))
    print(f"[{task_id}] 📋 转码任务已加入队列，当前队列长度: {transcode_queue.qsize()}")

# 转码文件（实际执行）
def transcode_video(input_path, output_path, task_id=""):
    try:
        # 获取转码前的文件大小
        original_size = os.path.getsize(input_path)
        
        # 获取输入文件的信息
        probe = ffmpeg.probe(input_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        
        if not video_stream:
            print(f"[{task_id}] ❌ 无法获取视频流信息")
            return False
            
        # 获取视频时长
        total_duration = float(video_stream.get('duration', 0))
        
        # 获取视频分辨率
        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        
        # 判断是否为4K视频
        is_4k = False
        if width >= 3840 and height >= 2160:
            is_4k = True
            print(f"[{task_id}] 📺 检测到4K视频 ({width}x{height})，将自动降至1080P")
        
        # 构建视频滤镜参数
        if is_4k:
            # 4K视频降至1080P，保持宽高比
            vf_param = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,noise=alls=1:allf=t+u'
        else:
            # 普通视频保持原分辨率
            vf_param = 'noise=alls=1:allf=t+u'
        
        # 使用优化的转码参数，针对1核1G服务器
        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264', '-c:a', 'aac',
            '-vf', vf_param,                 # 视频滤镜
            '-preset', 'ultrafast',          # 最快预设，适合低配置
            '-tune', 'zerolatency',          # 低延迟优化
            '-threads', '1',                 # 限制为单线程
            '-crf', '28',                    # 平衡质量和文件大小
            '-y', output_path
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # 正则表达式匹配进度信息
        time_pattern = re.compile(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})')
        
        # 实时读取进度
        while True:
            line = process.stderr.readline()
            if not line:
                break
            
            # 查找时间进度
            match = time_pattern.search(line)
            if match and total_duration > 0:
                hours = float(match.group(1))
                minutes = float(match.group(2))
                seconds = float(match.group(3))
                current_time = hours * 3600 + minutes * 60 + seconds
                
                progress = min((current_time / total_duration) * 100, 100)
                if is_4k:
                    print(f"\r[{task_id}] 🔄 转码进度 (4K→1080P): [{progress:5.1f}%] {current_time:.1f}s/{total_duration:.1f}s", end="")
                else:
                    print(f"\r[{task_id}] 🔄 转码进度: [{progress:5.1f}%] {current_time:.1f}s/{total_duration:.1f}s", end="")
        
        process.wait()
        
        if process.returncode == 0:
            transcoded_size = os.path.getsize(output_path)
            if is_4k:
                print(f"\n[{task_id}] ✅ 4K转码完成 (降至1080P): {output_path} ({transcoded_size/1024/1024:.1f}MB)")
            else:
                print(f"\n[{task_id}] ✅ 转码完成: {output_path} ({transcoded_size/1024/1024:.1f}MB)")
            return True
        else:
            if is_4k:
                print(f"\n[{task_id}] ❌ 4K转码失败，返回码: {process.returncode}")
            else:
                print(f"\n[{task_id}] ❌ 转码失败，返回码: {process.returncode}")
            return False
            
    except Exception as e:
        print(f"[{task_id}] ❌ 转码过程中发生错误: {e}")
        return False

# 上传文件到 Alist
def alist_upload(local_path, remote_name, task_id=""):
    token = alist_login()
    if not token:
        print(f"[{task_id}] ❌ 无法获取 Alist token，上传失败: {remote_name}")
        return False
        
    try:
        url = f"{ALIST_URL}/api/fs/put"
        file_path = quote(ALIST_PATH + remote_name, safe='/')
        
        # 获取文件大小
        file_size = os.path.getsize(local_path)
        
        headers = {
            "Authorization": token,
            "File-Path": file_path,
            "Content-Type": "application/octet-stream",
            "As-Task": "true",
            "Content-Length": str(file_size),
        }
        
        print(f"[{task_id}] ☁️ 开始上传: {remote_name} ({file_size/1024/1024:.1f}MB)")
        
        with open(local_path, "rb") as f:
            resp = requests.put(url, headers=headers, data=f, timeout=300)
        
        resp.raise_for_status()
        print(f"[{task_id}] ✅ 上传完成: {remote_name}")
        return True
        
    except Exception as e:
        print(f"[{task_id}] ❌ 上传到 Alist 失败: {e}")
        return False

# 清理文件名
def safe_filename(name: str, default="video.mp4"):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.replace(" ", "_")
    return name if name else default

# 生成唯一任务ID
def generate_task_id():
    return f"{datetime.now().strftime('%H%M%S')}_{threading.current_thread().ident % 1000}"

# Telegram Bot
app = Client("downloader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.video | filters.document)
async def handle_video(client, message):
    try:
        media = message.video or message.document
        if not media:
            return
        if message.document and not message.document.mime_type.startswith("video/"):
            return

        # 文件名处理
        caption = message.caption.strip() if message.caption else ""
        if caption:
            ext = os.path.splitext(media.file_name or "video.mp4")[1]
            file_name = safe_filename(caption) + ext
        else:
            file_name = media.file_name or "video.mp4"

        # 生成唯一任务ID
        task_id = generate_task_id()
        
        # 检查本地是否已存在同名文件
        local_path = os.path.join(os.getcwd(), file_name)
        if os.path.exists(local_path):
            print(f"\n[{task_id}] 📁 发现本地文件: {file_name}")
            file_size = os.path.getsize(local_path)
            print(f"[{task_id}] 📊 文件大小: {file_size/1024/1024:.1f}MB")
            path = local_path
        else:
            print(f"\n[{task_id}] 📥 开始下载: {file_name}")
            # 下载文件（允许并发）
            start_time = time.time()
            path = await message.download(
                file_name=file_name,
                progress=lambda cur, tot, *_: print(f"\r[{task_id}] ⬇️ {file_name} [{cur*100/tot:5.1f}%] {cur/1024/1024:.1f}MB/{tot/1024/1024:.1f}MB", end="" if cur < tot else "\n")
            )
            print(f"[{task_id}] ✅ 下载完成: {path}")

        # 转码文件（使用队列，确保单线程）
        transcoded_path = path + ".transcoded.mp4"
        queue_transcode_task(path, transcoded_path, task_id)
        
    except Exception as e:
        print(f"❌ 处理消息时发生错误: {e}")

if __name__ == "__main__":
    print("🚀 Bot 已启动，等待接收视频...")
    print("📋 转码队列系统已启用，同一时间只处理一个转码任务")
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n❌ 程序运行时发生错误: {e}")

