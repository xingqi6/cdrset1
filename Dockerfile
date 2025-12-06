# 使用 Debian 12 基础镜像
FROM python:3.11-bookworm

# 1. 安装环境
RUN apt-get update && apt-get install -y \
    nginx curl wget procps ca-certificates fuse rclone \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

RUN pip install --no-cache-dir bcrypt

# 2. 准备目录
WORKDIR /usr/local/sys_kernel

# 3. 下载程序
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz && mv alist io_driver && rm alist-linux-amd64.tar.gz
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz && mv cloudreve net_service && rm cloudreve_3.8.3_linux_amd64.tar.gz
RUN chmod +x io_driver net_service

# ========================================================
# [暴力修复] 解决 Nginx 欢迎页问题
# ========================================================
# 1. 删除 Nginx 默认的首页文件
RUN rm -f /var/www/html/index.nginx-debian.html
RUN rm -rf /var/www/html/*

# 2. 复制我们的伪装页 (确保 fake_site 文件夹里有 index.html)
COPY fake_site/ /var/www/html/

# 3. 赋予权限确保 Nginx 能读取
RUN chmod -R 755 /var/www/html
# ========================================================

# 配置文件
COPY nginx.conf /etc/nginx/sites-available/default
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# 启动
RUN mkdir -p /usr/local/sys_kernel/data
EXPOSE 7860
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
