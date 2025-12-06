import os, subprocess, time, signal, sys, re, json, urllib.request
from datetime import datetime

# === 环境变量 ===
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = os.environ.get("WEBDAV_BACKUP_PATH", "cloud_kernel_backup").strip('/')
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 1800)) 
SYS_TOKEN = os.environ.get("SYS_TOKEN", "Admin123") 

# === 路径 ===
CORE_DIR = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE_DIR}/io_driver"
CLOUD_BIN = f"{CORE_DIR}/net_service"
ALIST_DB_LOCAL = f"{CORE_DIR}/data/data.db"
CLOUD_DB_LOCAL = f"{CORE_DIR}/sys.db"
PREFIX_ALIST = "bk_io_"
PREFIX_CLOUD = "bk_net_"

p_nginx = None; p_alist = None; p_cloud = None; p_rclone = None

# === 网络修复 ===
def patch_network_final():
    print(">>> [Kernel] Applying stable network patch...")
    targets = ["huggingface.co", "s3.huggingface.co", "cdn-lfs.huggingface.co"]
    stable_ips = ["18.172.170.60", "18.172.170.92", "18.172.170.36", "18.172.170.52"]
    try:
        with open("/etc/nsswitch.conf", "w") as f: f.write("hosts: files dns\nnetworks: files\n")
        with open("/etc/hosts", "a") as f:
            f.write(f"\n# Network Patch\n")
            for domain in targets:
                for ip in stable_ips: f.write(f"{ip} {domain}\n")
    except: pass

# === 备份与轮替 ===
def run_cmd(cmd):
    try: subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return True
    except: return False

def get_remote_url(filename): return f"{WEBDAV_URL}/{BACKUP_PATH}/{filename}"

def ensure_remote_dir():
    if not WEBDAV_URL: return
    run_cmd(f"curl -X MKCOL -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{WEBDAV_URL}/{BACKUP_PATH}/' --silent --insecure")

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
    if len(target_files) > 5:
        to_delete = target_files[:(len(target_files) - 5)]
        for f in to_delete:
            run_cmd(f"curl -X DELETE -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(f)}' --silent --insecure")

def backup_data():
    if not WEBDAV_URL: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f">>> [Backup] Syncing...")
    if os.path.exists(ALIST_DB_LOCAL):
        name = f"{PREFIX_ALIST}{timestamp}.db"
        if run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{ALIST_DB_LOCAL}' '{get_remote_url(name)}' --silent --insecure"): cleanup_old_backups(PREFIX_ALIST)
    if os.path.exists(CLOUD_DB_LOCAL):
        name = f"{PREFIX_CLOUD}{timestamp}.db"
        if run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' -T '{CLOUD_DB_LOCAL}' '{get_remote_url(name)}' --silent --insecure"): cleanup_old_backups(PREFIX_CLOUD)

def restore_data():
    if not WEBDAV_URL: return
    ensure_remote_dir()
    all_files = list_remote_files()
    alist_bks = sorted([f for f in all_files if f.startswith(PREFIX_ALIST)])
    if alist_bks: run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(alist_bks[-1])}' -o '{ALIST_DB_LOCAL}' --silent --insecure")
    cloud_bks = sorted([f for f in all_files if f.startswith(PREFIX_CLOUD)])
    if cloud_bks: run_cmd(f"curl -u '{WEBDAV_USER}:{WEBDAV_PASS}' '{get_remote_url(cloud_bks[-1])}' -o '{CLOUD_DB_LOCAL}' --silent --insecure")

def set_secret():
    try: subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def start_rclone_bridge():
    global p_rclone
    rclone_config_cmd = [
        "rclone", "config", "create", "alist_proxy", "webdav",
        f"url=http://127.0.0.1:5244/dav/", "vendor=other", "user=admin", f"pass={SYS_TOKEN}",
        "--non-interactive", "--obscure", "--config", "/tmp/rclone.conf"
    ]
    subprocess.run(rclone_config_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    serve_cmd = [
        "rclone", "serve", "s3", "alist_proxy:/", "--addr", ":5200",
        "--access-key-id", "cloudreve", "--secret-access-key", "cloudreve",
        "--no-auth", "--config", "/tmp/rclone.conf"
    ]
    p_rclone = subprocess.Popen(serve_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# === 启动流程 ===
def start_services():
    global p_nginx, p_alist, p_cloud
    patch_network_final()
    os.makedirs(f"{CORE_DIR}/data", exist_ok=True)
    restore_data()
    p_alist = subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE_DIR)
    time.sleep(5)
    set_secret() 
    start_rclone_bridge()
    time.sleep(2)
    p_cloud = subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE_DIR)
    print(">>> [Kernel] System Online.")
    p_nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

def stop_handler(signum, frame):
    if p_nginx: p_nginx.terminate();
    if p_cloud: p_cloud.terminate();
    if p_alist: p_alist.terminate();
    if p_rclone: p_rclone.terminate();
    backup_data()
    sys.exit(0)

if __name__ == "__main__":
    start_services()
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    step = 0
    while True:
        time.sleep(1)
        step += 1
        if step >= SYNC_INTERVAL:
            backup_data(); step = 0
