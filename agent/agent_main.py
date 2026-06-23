# -*- coding: utf-8 -*-
"""MySQL Backup Agent - Pull Mode

作为独立运行的守护进程，通过 HTTP API 向管理中心拉取自己的备份任务。
自动解密凭据后执行本地 MySQL 物理克隆、Gzip 压缩并 Rsync 至 NFS。
"""

import os
import time
import json
import socket
import logging
import argparse
import traceback
import subprocess
from datetime import datetime
import urllib.request
import urllib.error

# 如果打包成单文件，需要内置依赖
try:
    from cryptography.fernet import Fernet
except ImportError:
    print("需要安装 cryptography 库: pip install cryptography")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("agent")

AGENT_VERSION = "1.0.0"

class BackupAgent:
    def __init__(self, api_base: str = None, token: str = None, hostname: str = None, poll_interval: int = None):
        # 优先读取传入的参数，其次读取环境变量，支持在 systemd 配置
        self.api_base = (api_base or os.getenv("API_BASE", "http://127.0.0.1:8000")).rstrip("/")
        self.token = token or os.getenv("TOKEN", "")
        self.hostname = hostname or os.getenv("HOSTNAME", socket.gethostname())
        
        interval_str = poll_interval if poll_interval is not None else os.getenv("POLL_INTERVAL", "15")
        self.poll_interval = int(interval_str)
        
        if not self.token:
            logger.error("Token 不能为空。请通过环境变量 TOKEN、命令行参数 -t 或配置文件传入（与管理端的 ENCRYPTION_KEY 保持一致）。")
            sys.exit(1)
            
    def _decrypt(self, encrypted_text: str) -> str:
        f = Fernet(self.token.encode())
        return f.decrypt(encrypted_text.encode()).decode()
        
    def report_progress(self, record_id: int, status: str = None, progress: str = None, error: str = None, filename: str = None, filesize: int = None):
        """向上游管理中心汇报进度"""
        url = f"{self.api_base}/api/agent/report/{record_id}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        payload = {"agent_version": AGENT_VERSION}
        if status: payload["status"] = status
        if progress: payload["progress_status"] = progress
        if error: payload["error_message"] = error
        if filename: payload["backup_file"] = filename
        if filesize is not None: payload["file_size_bytes"] = filesize
        
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
        except Exception as e:
            logger.warning(f"上报进度失败: {e}")

    def run_cmd(self, cmd: str) -> tuple:
        """执行本地 shell 命令并返回退出码、标准输出和标准错误"""
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        return process.returncode, stdout.strip(), stderr.strip()

    def perform_backup(self, task: dict):
        record_id = task["record_id"]
        db_port = task["db_port"]
        db_user = self._decrypt(task["db_user_enc"])
        db_pass = self._decrypt(task["db_pass_enc"])
        backup_dir = task["backup_dir"].rstrip("/")
        nfs_dir = task["nfs_dir"].rstrip("/")
        bwlimit = task.get("rsync_bwlimit", "100000")
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        local_log_file = f"{backup_dir}/backup_{timestamp}.log"
        temp_clone_dir = f"{backup_dir}/temp_clone_{timestamp}"
        temp_tar_file = f"{backup_dir}/temp_{timestamp}.tar.gz"
        
        try:
            logger.info(f"开始执行任务 {record_id}...")
            self.report_progress(record_id, status="running", progress="INITIALIZING")
            
            # 1. 建立目录
            self.run_cmd(f"mkdir -p {backup_dir}")
            
            # 2. 清理历史遗留临时文件
            cleanup_cmd = (
                f"if [ -n '{temp_clone_dir}' ] && [ '{temp_clone_dir}' != '/' ] && [ '{temp_clone_dir}' != ' ' ]; then "
                f"rm -rf '{temp_clone_dir}'; fi; "
                f"if [ -n '{temp_tar_file}' ] && [ '{temp_tar_file}' != '/' ] && [ '{temp_tar_file}' != ' ' ]; then "
                f"rm -f '{temp_tar_file}'; fi"
            )
            self.run_cmd(cleanup_cmd)
            
            # 3. 克隆
            logger.info("启动 MySQL CLONE 物理克隆...")
            self.report_progress(record_id, progress="CLONE: RUNNING")
            clone_sql = (
                f"mysql -u{db_user} -p'{db_pass}' "
                f"-h127.0.0.1 -P{db_port} -e \"CLONE LOCAL DATA DIRECTORY = '{temp_clone_dir}';\""
            )
            code, out, err = self.run_cmd(clone_sql)
            if code != 0:
                raise RuntimeError(f"MySQL 克隆失败: {err or out}")
                
            # 4. 压缩
            logger.info("克隆完成，开始进行 Gzip 最大化打包压缩...")
            self.report_progress(record_id, progress="COMPRESSING")
            tar_cmd = f"tar -czf {temp_tar_file} -C {backup_dir} temp_clone_{timestamp}"
            code, out, err = self.run_cmd(tar_cmd)
            if code != 0:
                raise RuntimeError(f"打包失败: {err}")
                
            # 清理克隆源目录
            self.run_cmd(f"rm -rf '{temp_clone_dir}'")
            
            # 5. MD5 与重命名
            logger.info("压缩完成，正在计算 MD5...")
            code, out, err = self.run_cmd(f"md5sum {temp_tar_file}")
            if code != 0:
                raise RuntimeError("计算 MD5 失败")
            md5_val = out.split()[0].strip()
            
            # {ip}_{hostname}_full_{timestamp}.{md5}.tar.gz
            # 注意：在 Agent 中，可能需要获取本机 IP。为了简单起见，这里直接使用 "local" 或解析本机的对外 IP，
            # 不过更稳妥的做法是从 hostname 反查或让控制端下发。为兼容，暂时设为 local_ip。
            # 为了减少侵入，控制端暂未下发 IP。我们可以动态获取本机 IP。
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(('8.8.8.8', 1))
                ip = s.getsockname()[0]
            except Exception:
                ip = '127.0.0.1'
            finally:
                s.close()
                
            final_filename = f"{ip}_{self.hostname}_full_{timestamp}.{md5_val}.tar.gz"
            final_path = f"{backup_dir}/{final_filename}"
            self.run_cmd(f"mv {temp_tar_file} {final_path}")
            
            code, out, err = self.run_cmd(f"stat -c%s {final_path}")
            file_size = int(out.strip()) if code == 0 else 0
            
            # 6. Rsync to NFS
            logger.info("准备 Rsync 同步至 NFS...")
            self.report_progress(record_id, progress="RSYNCING")
            self.run_cmd(f"mkdir -p {nfs_dir}")
            rsync_cmd = f"rsync -av --bwlimit={bwlimit} {final_path} {nfs_dir}/"
            code, out, err = self.run_cmd(rsync_cmd)
            if code != 0:
                raise RuntimeError(f"Rsync 到 NFS 失败: {err}")
                
            # 双重校验
            nfs_file = f"{nfs_dir}/{final_filename}"
            code, out, err = self.run_cmd(f"stat -c%s {nfs_file}")
            if code != 0 or int(out.strip()) != file_size:
                raise RuntimeError("NFS 双重校验失败，文件大小不一致")
                
            # 7. 完成
            logger.info(f"任务 {record_id} 备份成功！")
            self.report_progress(record_id, status="success", progress="COMPLETED", filename=final_filename, filesize=file_size)
            
        except Exception as e:
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"备份失败: {err_msg}")
            self.report_progress(record_id, status="failed", progress="FAILED", error=err_msg)
            # 清理临时文件
            self.run_cmd(f"if [ -n '{temp_clone_dir}' ]; then rm -rf '{temp_clone_dir}'; fi")
            self.run_cmd(f"if [ -n '{temp_tar_file}' ]; then rm -f '{temp_tar_file}'; fi")

    def poll_for_tasks(self):
        url = f"{self.api_base}/api/agent/task?hostname={self.hostname}"
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        
        while True:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = response.read().decode('utf-8')
                    if data and data != "null":
                        task = json.loads(data)
                        self.perform_backup(task)
            except urllib.error.HTTPError as e:
                logger.warning(f"轮询被服务器拒绝 (状态码 {e.code})，请检查 TOKEN 是否匹配。")
            except Exception as e:
                pass # 网络错误时静默，等待下一次轮询
                
            time.sleep(self.poll_interval)


def main():
    # 尝试加载可能存在的 .env 配置文件
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass  # 独立打包环境下若无 dotenv 则跳过
        
    parser = argparse.ArgumentParser(description="MySQL Backup Agent (Pull Mode)")
    parser.add_argument("-a", "--api-base", help="管理中心的 API 地址 (例如 http://192.168.1.100:8000)", type=str)
    parser.add_argument("-t", "--token", help="鉴权与解密 Token (与管理端 ENCRYPTION_KEY 相同)", type=str)
    parser.add_argument("-n", "--hostname", help="本机的注册别名，在管理端配置", type=str)
    parser.add_argument("-i", "--interval", help="轮询任务间隔 (秒)", type=int)
    
    args = parser.parse_args()
    
    logger.info(f"Backup Agent (Pull Mode) v{AGENT_VERSION} starting...")
    agent = BackupAgent(
        api_base=args.api_base,
        token=args.token,
        hostname=args.hostname,
        poll_interval=args.interval
    )
    logger.info(f"Target API: {agent.api_base}, Hostname: {agent.hostname}, Interval: {agent.poll_interval}s")
    agent.poll_for_tasks()

if __name__ == "__main__":
    main()
