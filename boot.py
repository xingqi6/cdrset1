import os
import subprocess
import time
import signal
import sys
import re
import json
import urllib.request
from datetime import datetime

# ================= 配置区域 =================
# 外部 WebDAV 备份 (用于存数据库，重启不丢数据的关键)
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "cloud_kernel_backup").strip('/')
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 1800)) # 默认30分钟备份一次
SYS_TOKEN = os.environ.get("SYS_TOKEN", "Admin123456")    # Alist 管理密码

# ================= 路径定义 =================
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"

# 数据库文件 (这两个文件是“灵魂”，必须备份)
ALIST_DB = f"{CORE_DIR}/data/data.db"
CLOUD_DB = f"{CORE_DIR}/sys.db"

# 备份文件前缀
PREFIX_ALIST = "bk_io_"
PREFIX_CLOUD = "bk_net_"

# 进程句柄
p_nginx = None
p_alist = None
p_cloud = None

# ================= 网络修复 (解决 TLS Handshake) =================
def resolve_ip_doh(domain):
    """通过 Google DoH 获取真实 IP，绕过容器 DNS"""
    try:
        url = f"https://dns.google/resolve?name={domain}&type=A"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if "Answer" in data:
                for ans in data["Answer"]:
                    if ans["type"] == 1: return ans["data"]
    except: pass
    return None

def patch_network():
    print(">>> [Kernel] Optimizing network routing...")
    targets = ["huggingface.co", "cdn-lfs.huggingface.co"]
    # 保底 IP (AWS US-East-1)
    fallback_map = {"huggingface.co": "18.172.170.60"}
    
    try:
        # 优先读 hosts
        with open("/etc/nsswitch.conf", "w") as f:
            f.write("hosts: files dns\nnetworks: files\n")
            
        with open("/etc/hosts", "a") as f:
            f.write("\n# Network Optimization\n")
            for domain in targets:
                ip = resolve_ip_doh(domain)
                if not ip and domain in fallback_map: ip = fallback_map[domain]
                if ip:
                    f.write(f"{ip} {domain}\n")
                    print(f">>> [Kernel] Route added: {domain} -> {ip}")
    except Exception as e:
        print(f">>> [Kernel] Network patch warning: {e}")

# ================= 备份与恢复 (核心逻辑) =================
def run_cmd(cmd):
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except: return False

def get_remote_url(filename):
    return f"{WEBDAV_URL}/{BACKUP_PATH}/{filename}"

def ensure_remote_dir():
    if not WEBDAV_URL: return
    cmd = f"curl -X MKCOL -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{WEBDAV_URL}/{BACKUP_PATH}/' --silent --insecure"
    run_cmd(cmd)

def list_remote_files():
    if not WEBDAV_URL: return []
    cmd = ["curl", "-X", "PROPFIND", "-u", f"{WEBDAV_USER}:{WEBDAV_PASS}", f"{WEBDAV_URL}/{BACKUP_PATH}/", "--header", "Depth: 1", "--silent", "--insecure"]
    try:
        output = subprocess.check_output(cmd).decode('utf-8')
        matches = re.findall(r'<[a-zA-Z0-9:]*href>([^<]+)</[a-zA-Z0-9:]*href>', output, re.IGNORECASE)
        return [m.rstrip('/').split('/')[-1] for m in matches if m.rstrip('/').split('/')[-1]]
    except: return []

def cleanup_old_backups(prefix):
    """只保留最新的 5 份备份"""
    all_files = list_remote_files()
    target_files = sorted([f for f in all_files if f.startswith(prefix)])
    while len(target_files) > 5:
        oldest = target_files.pop(0)
        run_cmd(f"curl -X DELETE -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(oldest)}' --silent --insecure")

def backup_data():
    """上传数据库到 WebDAV"""
    if not WEBDAV_URL: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 备份 Alist 数据
    if os.path.exists(ALIST_DB):
        name = f"{PREFIX_ALIST}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{ALIST_DB}' '{get_remote_url(name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_ALIST)
        
    # 备份 Cloudreve 数据
    if os.path.exists(CLOUD_DB):
        name = f"{PREFIX_CLOUD}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{CLOUD_DB}' '{get_remote_url(name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_CLOUD)
    
    print(f">>> [Kernel] State synced at {timestamp}")

def restore_data():
    """从 WebDAV 拉取最新数据库"""
    if not WEBDAV_URL: return
    print(">>> [Kernel] Restoring system state...")
    ensure_remote_dir()
    all_files = list_remote_files()
    
    # 恢复 Alist
    alist_bks = sorted([f for f in all_files if f.startswith(PREFIX_ALIST)])
    if alist_bks:
        latest = alist_bks[-1]
        print(f">>> [Kernel] Loading IO state: {latest}")
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(latest)}' -o '{ALIST_DB}' --silent --insecure")
    
    # 恢复 Cloudreve
    cloud_bks = sorted([f for f in all_files if f.startswith(PREFIX_CLOUD)])
    if cloud_bks:
        latest = cloud_bks[-1]
        print(f">>> [Kernel] Loading Net state: {latest}")
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(latest)}' -o '{CLOUD_DB}' --silent --insecure")

def set_password():
    """强制设置 Alist 密码"""
    try:
        subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

# ================= 服务管理 =================
def start_system():
    global p_nginx, p_alist, p_cloud
    
    # 1. 修复网络
    patch_network()
    
    # 2. 准备目录
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    
    # 3. 启动 IO 驱动 (Alist)
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    
    # 4. 设置密码 (等待启动后)
    time.sleep(5)
    set_password()
    
    # 5. 启动网络服务 (Cloudreve)
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    
    # 6. 启动伪装网关 (Nginx)
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop_handler(signum, frame):
    print(">>> [Kernel] Stopping...")
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    backup_data() # 退出前强制备份
    sys.exit(0)

if __name__ == "__main__":
    restore_data() # 启动前先恢复
    start_system()
    
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    
    step = 0
    while True:
        time.sleep(1)
        step += 1
        if step >= SYNC_INTERVAL:
            backup_data()
            step = 0
