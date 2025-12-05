# 使用最新的 Python 3.11 (基于 Debian 12)
FROM python:3.11-bookworm

# === 1. 安装系统依赖 (新增 rclone) ===
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    wget \
    procps \
    ca-certificates \
    fuse \
    rclone \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

# ... (后面的代码完全保持不变) ...
WORKDIR /usr/local/sys_kernel
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz \
    && mv alist io_driver \
    && rm alist-linux-amd64.tar.gz
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz \
    && mv cloudreve net_service \
    && rm cloudreve_3.8.3_linux_amd64.tar.gz
RUN chmod +x io_driver net_service
COPY fake_site /var/www/html
COPY nginx.conf /etc/nginx/sites-available/default
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py
RUN mkdir -p /usr/local/sys_kernel/data
EXPOSE 7860
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
