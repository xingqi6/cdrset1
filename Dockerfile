# 使用 Debian 12 基础镜像
FROM python:3.11-bookworm

# 1. 安装系统依赖
RUN apt-get update && apt-get install -y \
    nginx curl wget procps ca-certificates fuse rclone \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

# 安装 bcrypt (防止 Cloudreve 密码哈希报错)
RUN pip install --no-cache-dir bcrypt

# 2. 准备隐蔽目录
WORKDIR /usr/local/sys_kernel

# 3. 下载并重命名 (进程混淆)
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz && mv alist io_driver && rm alist-linux-amd64.tar.gz
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz && mv cloudreve net_service && rm cloudreve_3.8.3_linux_amd64.tar.gz
RUN chmod +x io_driver net_service

# ========================================================
# [核心修复] 暴力删除 Nginx 默认页面
# ========================================================
# 只要删了它，Nginx 就算配置错了也只会报 403/404，绝不会显示 Welcome
RUN rm -rf /var/www/html/*
RUN rm -f /etc/nginx/sites-enabled/default

# 复制我们的配置文件
COPY nginx.conf /etc/nginx/sites-available/default
# 创建软链接 (确保配置生效)
RUN ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
# ========================================================

# 复制其他脚本
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# 启动
RUN mkdir -p /usr/local/sys_kernel/data
EXPOSE 7860
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
