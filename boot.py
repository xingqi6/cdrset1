import os
import subprocess
import time
import signal
import sys
import re
from datetime import datetime

# ================= 环境变量配置 =================
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "cloud_kernel_backup").strip('/')
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 1800)) # 默认 30 分钟备份一次
SYS_TOKEN = os.environ.get("SYS_TOKEN", "Admin123")        # Alist 管理密码

# ================= 路径定义 =================
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"
ALIST_DB_LOCAL = f"{CORE_DIR}/data/data.db"
CLOUD_DB_LOCAL = f"{CORE_DIR}/sys.db"

# 备份文件前缀 (用来区分是哪个程序的数据库)
PREFIX_ALIST = "bk_io_"
PREFIX_CLOUD = "bk_net_"

p_nginx = None
p_alist = None
p_cloud = None
p_rclone = None

# ================= 1. 网络修复 (确保能连上 HuggingFace) =================
def patch_network_final():
    print(">>> [Kernel] Applying stable network patch...")
    targets = ["huggingface.co", "s3.huggingface.co", "cdn-lfs.huggingface.co"]
    # AWS US-East-1 CloudFront IPs (最稳定的官方IP)
    stable_ips = ["18.172.170.60", "18.172.170.92", "18.172.170.36", "18.172.170.52"]
    try:
        # 强制系统优先读取 hosts 文件
        with open("/etc/nsswitch.conf", "w") as f:
            f.write("hosts: files dns\nnetworks: files\n")
        # 写入 hosts
        with open("/etc/hosts", "a") as f:
            f.write(f"\n# Network Patch\n")
            for domain in targets:
                for ip in stable_ips:
                    f.write(f"{ip} {domain}\n")
    except: pass

# ================= 2. 备份与轮替核心 (WebDAV Keep 5) =================
def run_cmd(cmd):
    """静默执行 Shell 命令"""
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except: return False

def get_remote_url(filename):
    return f"{WEBDAV_URL}/{BACKUP_PATH}/{filename}"

def ensure_remote_dir():
    if not WEBDAV_URL: return
    # MKCOL 创建文件夹
    run_cmd(f"curl -X MKCOL -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{WEBDAV_URL}/{BACKUP_PATH}/' --silent --insecure")

def list_remote_files():
    """获取远程目录下的所有文件名"""
    if not WEBDAV_URL: return []
    # 使用 PROPFIND 获取文件列表
    cmd = ["curl", "-X", "PROPFIND", "-u", f"{WEBDAV_USER}:{WEBDAV_PASS}", f"{WEBDAV_URL}/{BACKUP_PATH}/", "--header", "Depth: 1", "--silent", "--insecure"]
    try:
        output = subprocess.check_output(cmd).decode('utf-8')
        # 使用正则从 XML 中提取文件名
        matches = re.findall(r'<[a-zA-Z0-9:]*href>([^<]+)</[a-zA-Z0-9:]*href>', output, re.IGNORECASE)
        # 清洗路径，只保留文件名 (例如 /dav/backup/bk_io_xxx.db -> bk_io_xxx.db)
        return [m.rstrip('/').split('/')[-1] for m in matches if m.rstrip('/').split('/')[-1]]
    except: return []

def cleanup_old_backups(prefix):
    """
    【核心逻辑】只保留最新的 5 份备份
    1. 获取所有文件
    2. 筛选出当前类型的文件 (比如只看 bk_io_...)
    3. 排序 (文件名包含时间戳，所以 ASCII 排序就是时间排序)
    4. 删除旧的
    """
    all_files = list_remote_files()
    target_files = sorted([f for f in all_files if f.startswith(prefix)])
    
    total = len(target_files)
    if total > 5:
        # 需要删除的数量
        delete_count = total - 5
        # 取出最旧的那几个 (列表前面的是旧的)
        to_delete = target_files[:delete_count]
        
        print(f">>> [Backup] Cleanup: Removing {delete_count} old files for {prefix}...")
        for f in to_delete:
            del_url = get_remote_url(f)
            run_cmd(f"curl -X DELETE -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{del_url}' --silent --insecure")

def backup_data():
    """执行备份并触发清理"""
    if not WEBDAV_URL: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f">>> [Backup] Starting sync at {timestamp}...")
    
    ensure_remote_dir()

    # 1. 备份 Alist 数据库
    if os.path.exists(ALIST_DB_LOCAL):
        name = f"{PREFIX_ALIST}{timestamp}.db"
        # 上传
        if run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{ALIST_DB_LOCAL}' '{get_remote_url(name)}' --silent --insecure"):
            # 上传成功后，清理旧的
            cleanup_old_backups(PREFIX_ALIST)

    # 2. 备份 Cloudreve 数据库
    if os.path.exists(CLOUD_DB_LOCAL):
        name = f"{PREFIX_CLOUD}{timestamp}.db"
        if run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{CLOUD_DB_LOCAL}' '{get_remote_url(name)}' --silent --insecure"):
            # 上传成功后，清理旧的
            cleanup_old_backups(PREFIX_CLOUD)
            
    print(f">>> [Backup] Sync complete.")

def restore_data():
    """启动时恢复数据"""
    if not WEBDAV_URL: return
    print(">>> [System] Checking backups...")
    ensure_remote_dir()
    all_files = list_remote_files()
    
    # 恢复 Alist (取最新的一个)
    alist_bks = sorted([f for f in all_files if f.startswith(PREFIX_ALIST)])
    if alist_bks:
        latest = alist_bks[-1]
        print(f">>> [System] Restoring IO DB: {latest}")
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(latest)}' -o '{ALIST_DB_LOCAL}' --silent --insecure")
    
    # 恢复 Cloudreve (取最新的一个)
    cloud_bks = sorted([f for f in all_files if f.startswith(PREFIX_CLOUD)])
    if cloud_bks:
        latest = cloud_bks[-1]
        print(f">>> [System] Restoring Cloud DB: {latest}")
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(latest)}' -o '{CLOUD_DB_LOCAL}' --silent --insecure")

# ================= 3. 辅助组件 =================
def set_secret():
    """设置 Alist 密码"""
    try: subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def start_rclone_bridge():
    """启动 Rclone 桥接 (把 WebDAV 转为 S3 给 Cloudreve 用)"""
    global p_rclone
    print(">>> [Kernel] Starting Bridge...")
    # 生成配置
    rclone_config_cmd = [
        "rclone", "config", "create", "alist_proxy", "webdav",
        f"url=http://127.0.0.1:5244/dav/", "vendor=other", "user=admin", f"pass={SYS_TOKEN}",
        "--non-interactive", "--obscure", "--config", "/tmp/rclone.conf"
    ]
    subprocess.run(rclone_config_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 启动服务
    serve_cmd = [
        "rclone", "serve", "s3", "alist_proxy:/", "--addr", ":5200",
        "--access-key-id", "cloudreve", "--secret-access-key", "cloudreve",
        "--no-auth", "--config", "/tmp/rclone.conf"
    ]
    p_rclone = subprocess.Popen(serve_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ================= 4. 启动流程 =================
def start_services():
    global p_nginx, p_alist, p_cloud
    
    patch_network_final()
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    
    # 1. 恢复数据
    restore_data()
    
    # 2. 启动 Alist
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    time.sleep(5)
    set_secret() 
    
    # 3. 启动 Rclone 桥接
    start_rclone_bridge()
    time.sleep(2)

    # 4. 启动 Cloudreve
    # 直接启动，不带任何重置参数。
    # 如果是新库，它会把密码打印在日志里。
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    
    # 5. 启动 Nginx (首页直连 Cloudreve)
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop_handler(signum, frame):
    print(">>> [Kernel] Shutting down...")
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    if p_rclone: p_rclone.terminate()
    backup_data() # 退出时执行最后一次备份和清理
    sys.exit(0)

if __name__ == "__main__":
    start_services()
    # 监听停止信号
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    
    # 定时循环
    step = 0
    while True:
        time.sleep(1)
        step += 1
        if step >= SYNC_INTERVAL:
            backup_data()
            step = 0
