# MySQL 自动物理克隆备份系统

本系统是基于 **Python 3 (FastAPI) 异步后端 + React 19 / Tailwind CSS 浅色控制台**构建的分布式 MySQL 免 Agent 自动物理备份管理系统。系统运行于管理机，远程控制并管理目标 MySQL 实例，提供可靠的物理克隆、网络传输、智能空间管理及安全合规门禁。

---

## 🌟 功能特性

### 1. 核心物理备份与同步 (Agent Pull 模式)
- **Agent Pull 模式**：彻底废弃高危的 SSH 远程执行，采用独立的单文件 Backup Agent 部署在目标机。Agent 每隔 15 秒通过短连接心跳轮询管理端的 HTTP API 获取分配给自己的任务。由于管理端不再需要通向目标机的 SSH 端口及 `sudo` 权限，安全性获得根本性提升。
- **凭据加密动态下发**：Agent 无需在本地配置文件中存储明文的 MySQL 账号密码。中心管理端在下发备份任务时，会将 MySQL 连接凭据使用 AES 加密下发，Agent 在内存中解密直接调用物理克隆，实现凭证的动态流动与落盘隔离。
- **打包与双重校验**：克隆完成后自动在目标机执行 **Gzip 最大化压缩 (等级 9)** 并计算 `MD5` 校验码，将文件名重命名为 `{ip}_{hostname}_full_{timestamp}.{md5}.tar.gz` 规范格式。使用 `rsync` 限制带宽同步至本地挂载的 NFS/GFS 存储，同步后对文件大小及 MD5 执行双重一致性比对。
- **垃圾清理与状态回退**：若克隆、压缩或同步任一阶段失败，系统会自动清除目标机产生的临时物理克隆源目录与压缩包，并将失败原因、故障详细堆栈完整存入管理数据库中。

### 2. 智能空间估算与历史清理
- **备份前自动估算**：启动备份前自动调用 `du` 估算目标 MySQL 数据目录的大小，并与目标机本地备份目录的可用空间进行比对，可用空间必须大于数据目录的 1.2 倍。
- **已同步备份安全删除**：如果可用空间不足，系统会自动扫描该主机在本地备份目录的历史压缩包，通过比对备份名中包含的 MD5，验证其是否已在 NFS 存储中安全、完整地存放。一旦确认 NFS 存在大小及 MD5 完全一致的副本，才安全地删除目标机本地的历史包，直至释放出足够空间，否则自动阻断备份。

### 3. 可选的自定义 Python 邮件告警发信
- **MyAlarm 报警类集成**：系统能够自动读取 `.env` 中配置的报警脚本，利用 Python 的 `importlib.util` 在运行时**动态加载**该文件并提取 `MyAlarm` 类。
- **线程池隔离异步发送**：发信逻辑采用 `asyncio.to_thread` 调度方法在线程池中调用，确保同步发信脚本的阻断或网络超时绝对不影响 FastAPI 主事件循环的性能。
- **双发信模式支持**：
  1. **即时异常告警**：每次有主机备份失败，立即调起 `mail = MyAlarm(ip, title, content)` 发送即时告警。
  2. **每日定时异常汇总**：每天定时（可通过 Cron 配置）查询当天所有失败的备份任务，将异常主机 IP、别名、启动时间和故障原因拼接为 HTML 表格，调起 `MyAlarm` 发送汇总报告。

4. **敏感配置 Fernet 对称加密**
   - 配置文件 `.env` 中敏感的连接字段（如数据库连接 URL、SSH 账号和 MySQL 用户名/密码）均支持通过 Fernet 算法进行加密存放。
   - 配置加载阶段（Pydantic 校验器）自动进行后置解密，且支持自动剥除复制或配置时手抖混入的密钥首尾空格、单引号 `'`、双引号 `"`。
   - 若未配置加密密钥 `ENCRYPTION_KEY` 或解密失败，系统自动回退至普通明文解析，实现完备的向下兼容。
   - **交互式安全加密工具 (`encrypt_tool.py`)**：不带参数运行该小工具将进入对运维友好的安全加密交互模式，自动在控制台使用 `getpass` 隐蔽接收您要加密的密码（终端不回显），彻底防止机密在 Bash 终端 `history` 历史命令中泄露。

5. **多机房 Zabbix 角色安全门禁校验 (带开关控制)**
   - **独立门禁校验开关**：支持在 `.env` 中配置 `ENABLE_ZABBIX_CHECK=True/False`。开启后系统强制对每一台备份主机进行角色校验；关闭后直接自动放行，完全向下兼容。
   - **动态可配置角色列表**：允许在配置中写入 `ZABBIX_ALLOWED_ROLES=L,T,Y` 自定义允许执行备份的角色。系统将自动进行逗号切割与空格清洗。如果 Zabbix 中的主机角色不匹配该列表，或者在已启用校验时发生连接配置丢失，系统将作为严重安全风险予以强制拦截阻断并触发即时报警。
   - **多机房弹性匹配**：在校验时系统自动提取目标主机的 hostname 机房前缀（如 `bj-mysql-01` 得到 `bj`），去配置字典 `ZABBIX_DB_URLS` 中检索匹配该机房对应的 Zabbix 库，支持跨机房的混合检验。该配置使用明文。

6. **简化预检与高并发批量导入**
   - **批量录入与并发校验**：支持在前端 Tab 页面多行文本框中批量粘贴机器 IP，后端利用 `asyncio.gather` 并发异步建立 SSH 连接预检并抓取 hostname 作为系统别名，失败的机器收集具体原因和 IP 组成故障报告汇总返还。
   - **预检失败重填机制**：若批量导入中部分 IP 连接失败，前端 Modal 保持打开呈现报错列表，并将输入框自动重置为“仅保留这批失败的 IP”，方便运维人员修改后一键重新提交。
   - **内网 100% 隔离支持**：彻底去除外网谷歌字体（Google Fonts）依赖，全部改用系统本地字体加载。

---

## 🛠️ 项目技术栈

- **后端**：Python 3.12+ / FastAPI / SQLAlchemy 2.0 (已处理 Python 3.14 兼容性) / asyncssh / APScheduler / Alembic
- **前端**：Vite / React 19 / Tailwind CSS
- **安全库**：cryptography (Fernet)

---

## 🚀 部署与运行指南

### 1. 前端静态编译
进入 `frontend` 目录安装依赖并执行打包：
```bash
cd frontend/
npm install
npm run build
```
这将在 `frontend/dist/` 下生成静态页面文件。之后，FastAPI 后端即可自动检测并托管此目录。

### 2. 配置敏感参数 Fernet 加密 (推荐)
1. 在项目根目录下**直接运行**加密工具：
   ```bash
   python3 encrypt_tool.py
   ```
2. 按照终端提示：
   - 提示 1 (Fernet 密钥)：直接**按回车**，系统将自动生成 32 字节 Base64 安全密钥，将其贴入 `.env` 中的 `ENCRYPTION_KEY` 变量下。
   - 提示 2 (明文字符)：安全输入您要加密的密码，密码输入已安全隐藏。
   - 加密成功后，将生成的密文替换贴入 `.env` 中对应的明文位置即可。

### 3. 配置多机房 Zabbix 角色校验门禁 (可选)
在 `.env` 中加入启用配置、允许的角色列表以及 `ZABBIX_DB_URLS` 配置项：
```ini
# 是否开启 Zabbix 角色安全门禁校验 (True / False)
ENABLE_ZABBIX_CHECK=True
# 允许执行备份的 Zabbix 主机角色列表 (以逗号分隔，如 L,T,Y)
ZABBIX_ALLOWED_ROLES=L,T,Y

# Zabbix 连接串字典配置 (JSON 格式明文映射)
ZABBIX_DB_URLS={"bj": "mysql+aiomysql://zabbix:password@192.168.0.2:3306/zabbix", "sh": "mysql+aiomysql://zabbix:password@192.168.1.2:3306/zabbix"}
```

### 4. 运行后端服务
在项目根目录安装依赖，进行数据库表结构迁移升级（Alembic），并启动 Uvicorn：
```bash
pip3 install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000
```
启动后在浏览器中访问 `http://<管理机IP>:8000/` 即可直接使用备份管理控制台。

### 5. 编译与部署 Backup Agent
Agent 需要放置在目标 MySQL 服务器运行：
```bash
cd agent/
make build
```
编译成功后，将 `dist/backup-agent` 分发到所有目标机，配置并后台运行（例如通过 systemd 管理）：
```bash
export API_BASE="http://<管理机IP>:8000"
export TOKEN="<您在 .env 中的 ENCRYPTION_KEY>"
export HOSTNAME="<本机的注册别名>"
./backup-agent
```
