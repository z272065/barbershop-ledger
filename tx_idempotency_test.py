# -*- coding: utf-8 -*-
"""事务与幂等验证件:RAISE(ABORT) 的边界行为 + 重放语义,全部在从 schema.sql 现建的内存库上验证。

用法:python tx_idempotency_test.py
背景:SQLite 的 RAISE(ABORT) 只撤销当前语句,不回滚整个事务——
多语句事务(如"开卡=建会员+首充")中途违规时,前几句已生效的行还在,回滚是应用层的责任。
"""
import sqlite3, sys, os

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

con = sqlite3.connect(':memory:', isolation_level=None)
con.execute('PRAGMA foreign_keys=ON')
with open('schema.sql', encoding='utf-8') as f:
    con.executescript(f.read())
con.execute("insert into services(name,price) values('剪发',1000)")

def count(table):
    return con.execute(f'select count(*) from {table}').fetchone()[0]

print('=== 验证一:开卡事务中途违规,RAISE 不回滚,回滚归应用 ===')
con.execute('BEGIN')                                    # 开卡 = 两条语句一个事务
con.execute("insert into members(name) values('赵敏')")   # ① 建会员
print('第一句已执行:会员数 =', count('members'))
try:                                                     # ② 首充金额方向反
    con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
                "values('充值',(select id from members where name='赵敏'),-100,120,'BADOPEN01','2026-10-22 10:00:00')")
except sqlite3.IntegrityError as e:
    print(f'第二句违规被拦: {e.args[0]}')
print('报错后事务并未自动回滚: 会员 =', count('members'), '人(第一句的行还在), 事务仍开着 =', con.in_transaction)
con.rollback()
print('应用显式 rollback 后: 会员 =', count('members'), '人, 流水 =', count('transactions'), '行 -> 开卡整体回滚,不留半张卡')
assert count('members') == 0 and count('transactions') == 0

print()
print('=== 验证二:同一 request_id 发两次,只扣一次 ===')
con.execute("insert into members(name) values('孙洁')")
con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            "values('充值',(select id from members where name='孙洁'),10000,10000,'TOPUP9001','2026-10-22 10:00:00')")
con.execute("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
            "values('消费',(select id from members where name='孙洁'),(select id from services where name='剪发'),1000,10000,-10000,'BUY009001','2026-10-22 11:00:00')")
bal = con.execute("select sum(balance_delta) from transactions t join members m on t.member_id=m.id where m.name='孙洁'").fetchone()[0]
print(f'充值 100 后消费 100,余额恰好花光: {bal/100:.2f} 元')

print('-- 2a 手抖重发同一笔消费,直接 INSERT(错误姿势) --')
try:
    con.execute("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
                "values('消费',(select id from members where name='孙洁'),(select id from services where name='剪发'),1000,10000,-10000,'BUY009001','2026-10-22 11:00:00')")
except sqlite3.IntegrityError as e:
    print(f'  报错: {e.args[0]}   <-- 余额已花光,BEFORE 余额触发器先于唯一索引开枪,拿到的是[余额不足]而非重放结果')

print('-- 2b 后端规矩:写前查(正确姿势) --')
rows = con.execute("select id,type,amount from transactions where request_id='BUY009001'").fetchall()
if rows:
    print(f'  request_id 已存在 -> 不再插入,直接返回原结果: {rows[0]}')
after = con.execute("select count(*) from transactions where request_id='BUY009001'").fetchone()[0]
print(f'  同一 request_id 落账行数 = {after} (只扣一次)')

print()
print('验证结论:事务边界由应用掌控(RAISE 只管单句);幂等=写前查+唯一索引兜底,重放永远返回原结果、绝不二次扣款。')
