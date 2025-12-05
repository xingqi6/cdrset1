import os
import subprocess
import time
import signal
import sys
import re
import json
import urllib.request
from datetime import datetime

# ================= 环境变量 =================
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "cloud_kernel_backup").strip('/')
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 1800)) 
SYS_TOKEN = os.environ.get("SYS_TOKEN", "123456") 

# ================= 路径定义 =================
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"
ALIST_DB_LOCAL = f"{CORE_DIR}/data/data.db"
CLOUD_DB_LOCAL = f"{CORE_DIR}/sys.db"
PREFIX_ALIST = "bk_io_"
PREFIX_CLOUD = "bk_net_"

p_nginx = None
p_alist = None
p_cloud = None

# ================= 网络修复 (S3 & HF 域名) =================
def resolve_ip_doh(domain):
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

def patch_network_final():
    print(">>> [Kernel] Applying stable network patch...")
    targets = ["huggingface.co", "s3.huggingface.co", "cdn-lfs.huggingface.co"]
    stable_ips = ["18.172.170.60", "18.172.170.92", "18.172.170.36", "18.172.170.52"]
    
    try:
        with open("/etc/nsswitch.conf", "w") as f:
            f.write("hosts: files dns\nnetworks: files\n")
        with open("/etc/hosts", "a") as f:
            f.write(f"\n# Stable Patch\n")
            for domain in targets:
                for ip in stable_ips:
                    f.write(f"{ip} {domain}\n")
        print(">>> [Kernel] Network patched.")
    except Exception as e:
        print(f">>> [Kernel] Patch failed: {e}")

# ================= 备份与恢复 =================
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
    all_files = list_remote_files()
    target_files = sorted([f for f in all_files if f.startswith(prefix)])
    while len(target_files) > 5:
        oldest = target_files.pop(0)
        run_cmd(f"curl -X DELETE -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(oldest)}' --silent --insecure")

def backup_data():
    if not WEBDAV_URL: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.path.exists(ALIST_DB_LOCAL):
        name = f"{PREFIX_ALIST}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{ALIST_DB_LOCAL}' '{get_remote_url(name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_ALIST)
    if os.path.exists(CLOUD_DB_LOCAL):
        name = f"{PREFIX_CLOUD}{timestamp}.db"
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{CLOUD_DB_LOCAL}' '{get_remote_url(name)}' --silent --insecure")
        cleanup_old_backups(PREFIX_CLOUD)

def restore_data():
    if not WEBDAV_URL: return
    ensure_remote_dir()
    all_files = list_remote_files()
    alist_bks = sorted([f for f in all_files if f.startswith(PREFIX_ALIST)])
    if alist_bks:
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(alist_bks[-1])}' -o '{ALIST_DB_LOCAL}' --silent --insecure")
    cloud_bks = sorted([f for f in all_files if f.startswith(PREFIX_CLOUD)])
    if cloud_bks:
        run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(cloud_bks[-1])}' -o '{CLOUD_DB_LOCAL}' --silent --insecure")

def set_secret():
    try:
        subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

# ================= 启动流程 =================
def start_services():
    global p_nginx, p_alist, p_cloud
    
    # 1. 修复网络
    patch_network_final()
    
    # 2. 准备目录
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    
    # 3. 启动 Alist
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    
    # 4. 设置 Alist 密码
    time.sleep(5)
    set_secret() 
    
    # =======================================================
    # [新增] 暴力重置 Cloudreve 密码 (关键步骤)
    # =======================================================
    print("\n" + "="*50)
    print(">>> [Kernel] FORCING PASSWORD RESET...")
    print(">>> [Kernel] Please look for 'Admin user name' and 'Admin password' below:")
    print("="*50 + "\n")
    
    # 执行重置命令，这会将 output 直接打印到 Logs
    subprocess.run([CLOUD_BIN, "-c", "conf.ini", "--database-script", "ResetAdminPassword"], cwd=CORE_DIR)
    
    print("\n" + "="*50 + "\n")
    # =======================================================

    # 5. 启动 Cloudreve
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    
    # 6. 启动 Nginx
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop_handler(signum, frame):
    if p_nginx: p_nginx.terminate()
    if p_cloud: p_cloud.terminate()
    if p_alist: p_alist.terminate()
    backup_data()
    sys.exit(0)

if __name__ == "__main__":
    restore_data()
    start_services()
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    step = 0
    while True:
        time.sleep(1)
        step += 1
        if step >= SYNC_INTERVAL:
            backup_data()
            step = 0
