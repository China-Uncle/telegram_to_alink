import os
import re
import time
import requests
import ffmpeg  # 添加导入
from urllib.parse import quote
from pyrogram import Client, filters

# ========= 配置 =========
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

ALIST_URL = os.environ.get("ALIST_URL")
ALIST_USER = os.environ.get("ALIST_USER")
ALIST_PASS = os.environ.get("ALIST_PASS")
ALIST_PATH = os.environ.get("ALIST_PATH", "/videos/")
# ========================

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

# 转码文件以改变MD5值
def transcode_video(input_path, output_path):
    try:
        # 使用ffmpeg进行转码，只改变MD5值而不显著改变质量
        # 添加一个轻微的视频滤镜来确保MD5值改变
        (
            ffmpeg
            .input(input_path)
            .output(output_path, vcodec='libx264', acodec='aac', 
                   vf='noise=alls=1:allf=t+u', 
                   preset='ultrafast',
                   tune='fastdecode')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print(f"✅ 转码完成: {output_path}")
        return True
    except ffmpeg.Error as e:
        print(f"❌ 转码失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 转码过程中发生未知错误: {e}")
        return False

# 上传文件到 Alist
def alist_upload(local_path, remote_name):
    token = alist_login()
    if not token:
        print(f"❌ 无法获取 Alist token，上传失败: {remote_name}")
        return False
        
    try:
        url = f"{ALIST_URL}/api/fs/put"
        # 使用 URL 编码的完整目标文件路径
        # 对文件路径进行URL编码，确保支持中文等特殊字符
        file_path = quote(ALIST_PATH + remote_name, safe='/')
        
        # 准备请求头部
        headers = {
            "Authorization": token,
            "File-Path": file_path,  # 使用 File-Path 头部
            "Content-Type": "application/octet-stream",
            "As-Task": "true",
        }
        
        # 打开文件并获取文件大小
        with open(local_path, "rb") as f:
            # 获取文件大小并添加到头部
            f.seek(0, 2)  # 移动到文件末尾
            file_size = f.tell()  # 获取文件大小
            f.seek(0)  # 移动回文件开头
            
            headers["Content-Length"] = str(file_size)
            
            # 发送请求
            resp = requests.put(url, headers=headers, data=f, timeout=300)
        
        resp.raise_for_status()
        
        # 解析响应
        try:
            result = resp.json()
            # 输出完整的返回值
            print(f"📤 Alist 上传接口返回值: {result}")
        except ValueError:  # JSON解析失败
            print(f"☁️ 已上传到 Alist (无法解析响应): {ALIST_PATH}{remote_name}")
            print(f"📤 原始响应内容: {resp.text}")
            return True
        
        # 检查响应中的任务状态，添加None检查
        if result and isinstance(result, dict):
            if "data" in result and result["data"] is not None:
                if "task" in result["data"] and result["data"]["task"] is not None:
                    task = result["data"]["task"]
                    task_name = task.get('name', 'Unknown')
                    task_status = task.get('status', 'Unknown')
                    print(f"☁️ 已提交上传任务: {task_name}, 状态: {task_status}")
                else:
                    print(f"☁️ 已上传到 Alist: {ALIST_PATH}{remote_name}")
            else:
                print(f"☁️ 已上传到 Alist: {ALIST_PATH}{remote_name}")
        else:
            print(f"☁️ 已上传到 Alist (响应格式异常): {ALIST_PATH}{remote_name}")
            
        return True
    except Exception as e:
        print(f"❌ 上传到 Alist 失败: {e}")
        return False

# 清理文件名
def safe_filename(name: str, default="video.mp4"):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.replace(" ", "_")
    return name if name else default

# 下载进度显示
def progress(current, total, start, filename):
    try:
        elapsed = time.time() - start
        speed = current / elapsed if elapsed > 0 else 0
        percent = current * 100 / total
        print(f"\r⬇️ {filename} [{percent:.2f}%] {current/1024/1024:.2f}MB / {total/1024/1024:.2f}MB @ {speed/1024:.2f}KB/s", end="")
    except Exception as e:
        print(f"\n⚠️ 进度显示错误: {e}")

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

        print(f"\n📥 收到视频: {file_name}, 开始下载...")

        start_time = time.time()
        path = await message.download(
            file_name=file_name,
            progress=lambda cur, tot: progress(cur, tot, start_time, file_name)
        )
        print(f"\n✅ 下载完成: {path}")

        # 转码文件以改变MD5值
        transcoded_path = path + ".transcoded.mp4"
        if transcode_video(path, transcoded_path):
            # 删除原始文件
            try:
                os.remove(path)
                print(f"🗑 已删除原始文件: {path}")
            except Exception as e:
                print(f"⚠️ 删除原始文件失败: {e}")
            
            # 上传转码后的文件
            if alist_upload(transcoded_path, file_name):
                try:
                    os.remove(transcoded_path)
                    print(f"🗑 已删除转码文件: {transcoded_path}")
                except Exception as e:
                    print(f"⚠️ 删除转码文件失败: {e}")
            else:
                # 即使上传失败也尝试删除转码文件以释放空间
                try:
                    os.remove(transcoded_path)
                    print(f"🗑 已删除转码文件 (上传失败): {transcoded_path}")
                except Exception as e:
                    print(f"⚠️ 删除转码文件失败: {e}")
        else:
            print("❌ 转码失败，将上传原始文件")
            # 转码失败则上传原始文件
            if alist_upload(path, file_name):
                try:
                    os.remove(path)
                    print(f"🗑 已删除本地文件: {path}")
                except Exception as e:
                    print(f"⚠️ 删除本地文件失败: {e}")
            else:
                # 即使上传失败也尝试删除本地文件以释放空间
                try:
                    os.remove(path)
                    print(f"🗑 已删除本地文件 (上传失败): {path}")
                except Exception as e:
                    print(f"⚠️ 删除本地文件失败: {e}")
                
    except Exception as e:
        print(f"❌ 处理消息时发生错误: {e}")

if __name__ == "__main__":
    print("🚀 Bot 已启动，等待接收视频...")
    
    # 打印配置
    print("配置:")
    print(f"API_ID: {API_ID}")
    print(f"API_HASH: {API_HASH}")
    print(f"BOT_TOKEN: {BOT_TOKEN}")
    print(f"ALIST_URL: {ALIST_URL}")
    print(f"ALIST_USER: {ALIST_USER}")
    print(f"ALIST_PASS: {ALIST_PASS}")
    print(f"ALIST_PATH: {ALIST_PATH}")
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n❌ 程序运行时发生错误: {e}")
        # 即使发生错误也不退出，继续运行

