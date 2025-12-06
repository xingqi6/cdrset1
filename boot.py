import os, subprocess, time, signal, sys, re, json, urllib.request
from datetime import datetime

# === 配置 ===
WEBDAV_URL = os.environ.get("WEBDAV_URL", "").rstrip('/')
WEBDAV_USER = os.environ.get("WEBDAV_USERNAME")
WEBDAV_PASS = os.environ.get("WEBDAV_PASSWORD")
BACKUP_PATH = "cloud_data_backup"
SYS_TOKEN = os.environ.get("SYS_TOKEN", "Admin123") # Alist 密码

# === 路径 ===
CORE = "/usr/local/sys_kernel"
ALIST_BIN = f"{CORE}/io_driver"
CLOUD_BIN = f"{CORE}/net_service"
DB_ALIST = f"{CORE}/data/data.db"
DB_CLOUD = f"{CORE}/sys.db"

# === 网络修复 (解决 HF S3 连接报错) ===
def patch_network():
    print(">>> [System] Patching network for Datasets...")
    targets = ["huggingface.co", "s3.huggingface.co", "cdn-lfs.huggingface.co"]
    ips = ["18.172.170.60", "18.172.170.92", "18.172.170.36", "18.172.170.52"]
    try:
        with open("/etc/hosts", "a") as f:
            f.write("\n# Network Patch\n")
            for d in targets:
                for ip in ips: f.write(f"{ip} {d}\n")
    except: pass

# === Rclone 桥接 (Cloudreve -> S3 -> Rclone -> WebDAV -> Alist) ===
def start_rclone():
    print(">>> [System] Starting Storage Bridge...")
    # 1. 生成 Rclone 配置，指向内部 Alist
    conf = f"""[alist_bridge]
type = webdav
url = http://127.0.0.1:5244/dav/
vendor = other
user = admin
pass = {subprocess.getoutput(f"rclone obscure {SYS_TOKEN}")}
"""
    with open("/tmp/rclone.conf", "w") as f: f.write(conf)
    
    # 2. 启动 S3 服务端 (端口 5200)
    cmd = [
        "rclone", "serve", "s3", "alist_bridge:/",
        "--addr", ":5200",
        "--access-key-id", "cloudreve",
        "--secret-access-key", "cloudreve",
        "--no-auth", "--config", "/tmp/rclone.conf"
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# === 备份与恢复 ===
def run_backup_restore(action):
    if not WEBDAV_URL: return
    auth = f"-u '{WEBDAV_USER}:{WEBDAV_PASS}'"
    base = f"{WEBDAV_URL}/{BACKUP_PATH}"
    
    if action == "restore":
        print(">>> [Backup] Restoring data...")
        # 尝试创建远程目录
        subprocess.run(f"curl {auth} -X MKCOL '{base}/' -s -k", shell=True)
        # 下载
        subprocess.run(f"curl {auth} '{base}/alist.db' -o '{DB_ALIST}' -s -k", shell=True)
        subprocess.run(f"curl {auth} '{base}/cloud.db' -o '{DB_CLOUD}' -s -k", shell=True)
        
    elif action == "backup":
        if os.path.exists(DB_ALIST):
            subprocess.run(f"curl {auth} -T '{DB_ALIST}' '{base}/alist.db' -s -k", shell=True)
        if os.path.exists(DB_CLOUD):
            subprocess.run(f"curl {auth} -T '{DB_CLOUD}' '{base}/cloud.db' -s -k", shell=True)
        print(f">>> [Backup] Synced at {datetime.now().strftime('%H:%M')}")

# === 主流程 ===
def main():
    patch_network()
    run_backup_restore("restore")
    os.makedirs(f"{CORE}/data", exist_ok=True)
    
    # 1. 启动 Alist
    subprocess.Popen([ALIST_BIN, "server", "--no-prefix"], cwd=CORE)
    time.sleep(3)
    # 强制设置 Alist 密码
    subprocess.run([ALIST_BIN, "admin", "set", SYS_TOKEN], cwd=CORE, stdout=subprocess.DEVNULL)
    
    # 2. 启动 Rclone 桥接
    start_rclone()
    
    # 3. 启动 Cloudreve (并在日志显示密码)
    print("\n" + "="*40)
    print(">>> [System] CLOUDREVE CREDENTIALS:")
    subprocess.run([CLOUD_BIN, "-c", "conf.ini", "--database-script", "ResetAdminPassword"], cwd=CORE)
    print("="*40 + "\n")
    
    subprocess.Popen([CLOUD_BIN, "-c", "conf.ini"], cwd=CORE)
    
    # 4. 启动 Nginx
    subprocess.Popen(["nginx", "-g", "daemon off;"])
    
    # 循环备份
    count = 0
    while True:
        time.sleep(60)
        count += 1
        if count >= 30: # 30分钟备份一次
            run_backup_restore("backup")
            count = 0

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda s, f: (run_backup_restore("backup"), sys.exit(0)))
    main()
