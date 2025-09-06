FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装FFmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 拷贝依赖文件并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目代码
COPY . /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动 Bot
CMD ["python", "bot.py"]
