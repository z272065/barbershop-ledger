# 每日备份脚本:VACUUM INTO 生成带日期的独立文件,本地保留最近 7 份
# 部署时只改下面两个路径;COS 异地上传在部署周接(备案号下来那周),先留占位
import sqlite3, os
from datetime import date

DB_PATH = r"C:\Users\Lenovo\练习\理发店会员系统\practice3.db"      # 练习库;部署时改服务器生产库路径
BACKUP_DIR = r"C:\Users\Lenovo\练习\理发店会员系统\backups"        # 部署时改服务器备份目录
KEEP = 7

# VACUUM INTO 的目标文件不能已存在,当天重跑=先删旧份再备(覆盖式)
backup_path = os.path.join(BACKUP_DIR, f"shop_{date.today().isoformat()}.db")
if os.path.exists(backup_path):
    os.remove(backup_path)

os.makedirs(BACKUP_DIR, exist_ok=True)
c = sqlite3.connect(DB_PATH, isolation_level=None)
c.execute("VACUUM INTO ?", (backup_path,))

# 自检:备份必须能打开能查,查不动=备份没成功(这就是还原演练的最小版)
d = sqlite3.connect(backup_path)
members = d.execute("SELECT count(*) FROM members").fetchone()[0]
txs = d.execute("SELECT count(*) FROM transactions").fetchone()[0]
d.close()
c.close()
print(f"{date.today().isoformat()} 备份成功: {backup_path}")
print(f"  自检通过: members {members} 行 / transactions {txs} 行")

# TODO(部署周): ①COS 异地上传(几行 SDK) ②cron 定时,在宝塔面板"计划任务"里配

# 保留最近 KEEP 份:文件名是 ISO 日期,字典序=时间序(和全库时间列定稿同一原理)
old = sorted(os.listdir(BACKUP_DIR))[:-KEEP]
for name in old:
    os.remove(os.path.join(BACKUP_DIR, name))
    print("  清理旧备份:", name)
