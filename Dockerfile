FROM python:3.11-bookworm

# 1. 安装基础工具、证书、Rclone (关键)
RUN apt-get update && apt-get install -y \
    nginx curl wget procps ca-certificates fuse rclone \
    && rm -rf /var/lib/apt/lists/* && update-ca-certificates

# 2. 创建隐蔽工作目录
WORKDIR /usr/local/sys_kernel

# 3. 下载并混淆文件名
# Alist -> io_driver
RUN wget https://github.com/alist-org/alist/releases/download/v3.35.0/alist-linux-amd64.tar.gz \
    && tar -zxvf alist-linux-amd64.tar.gz && mv alist io_driver && rm alist-linux-amd64.tar.gz
# Cloudreve -> net_service
RUN wget https://github.com/cloudreve/cloudreve/releases/download/3.8.3/cloudreve_3.8.3_linux_amd64.tar.gz \
    && tar -zxvf cloudreve_3.8.3_linux_amd64.tar.gz && mv cloudreve net_service && rm cloudreve_3.8.3_linux_amd64.tar.gz

RUN chmod +x io_driver net_service

# 4. 植入配置
COPY fake_site /var/www/html
COPY nginx.conf /etc/nginx/sites-available/default
COPY conf.ini /usr/local/sys_kernel/conf.ini
COPY boot.py /usr/local/sys_kernel/boot.py

# 5. 准备数据目录
RUN mkdir -p /usr/local/sys_kernel/data

EXPOSE 7860
CMD ["python3", "-u", "/usr/local/sys_kernel/boot.py"]
