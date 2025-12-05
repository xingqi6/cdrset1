# 使用最新的 Python 3.11 (基于 Debian 12)
FROM python:3.11-bookworm

# === 1. 安装系统依赖 (含证书和工具) ===
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    wget \
    procps \
    ca-certificates \
    fuse \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

# === 2. 创建核心隐蔽目录 ===
WORKDIR /usr/local/sys_kernel

# === 3. 下载并深度伪装核心程序 ===
# Alist -> io_driver (IO 驱动)
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz \
    && mv alist io_driver \
    && rm alist-linux-amd64.tar.gz

# Cloudreve -> net_service (网络服务)
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz \
    && mv cloudreve net_service \
    && rm cloudreve_3.8.3_linux_amd64.tar.gz

# 赋予执行权限
RUN chmod +x io_driver net_service

# === 4. 植入配置文件 ===
COPY fake_site /var/www/html
COPY nginx.conf /etc/nginx/sites-available/default
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# === 5. 准备数据目录 ===
RUN mkdir -p /usr/local/sys_kernel/data

# === 6. 暴露端口 ===
EXPOSE 7860

# === 7. 启动引导 ===
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
