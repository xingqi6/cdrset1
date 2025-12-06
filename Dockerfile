# 使用 Debian 12
FROM python:3.11-bookworm

# 1. 安装基础环境
RUN apt-get update && apt-get install -y \
    nginx curl wget procps ca-certificates fuse rclone \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

# 2. 核心工作目录
WORKDIR /usr/local/sys_kernel

# 3. 下载程序
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz && mv alist io_driver && rm alist-linux-amd64.tar.gz
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz && mv cloudreve net_service && rm cloudreve_3.8.3_linux_amd64.tar.gz
RUN chmod +x io_driver net_service

# =========================================================
# [重点修复] 网页文件处理
# =========================================================
# 1. 先把 Nginx 默认的 html 文件夹清空
RUN rm -rf /var/www/html/*

# 2. 复制 fake_site 文件夹里的“所有内容”到 html 根目录
# 注意：这里 fake_site/ 后面加斜杠，表示复制内容而不是文件夹本身
COPY fake_site/ /var/www/html/

# 3. 复制 Nginx 配置文件 (覆盖默认配置)
COPY nginx.conf /etc/nginx/sites-available/default
# =========================================================

# 5. 其他配置
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# 6. 启动
RUN mkdir -p /usr/local/sys_kernel/data
EXPOSE 7860
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
