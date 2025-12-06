# 使用 Debian 12 基础镜像
FROM python:3.11-bookworm

# === 1. 安装系统依赖 ===
# 去掉了 python3-bcrypt，因为我们要用 pip 安装
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    wget \
    procps \
    ca-certificates \
    fuse \
    rclone \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

# === 2. [关键修复] 安装 Python 依赖库 ===
# 这行代码解决了 "No module named 'bcrypt'" 错误
RUN pip install --no-cache-dir bcrypt

# === 3. 创建目录 ===
WORKDIR /usr/local/sys_kernel

# === 4. 下载程序 ===
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz && mv alist io_driver && rm alist-linux-amd64.tar.gz
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz && mv cloudreve net_service && rm cloudreve_3.8.3_linux_amd64.tar.gz
RUN chmod +x io_driver net_service

# === 5. 配置文件 ===
COPY fake_site /var/www/html
COPY nginx.conf /etc/nginx/sites-available/default
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# === 6. 启动 ===
RUN mkdir -p /usr/local/sys_kernel/data
EXPOSE 7860
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
