# -*- coding: utf-8 -*-
"""事务与幂等验证件:RAISE(ABORT) 的边界行为 + 重放语义,全部在从 schema.sql 现建的内存库上验证。

用法:python tx_idempotency_test.py
每个验证点都带程序自动核对(断言),任一不符即报错并以非零状态退出。
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
    raise AssertionError('违规首充未被拦截')
except sqlite3.IntegrityError as e:
    assert e.args[0] == '充值金额必须大于0/充值到账金额不能少于实收', e.args[0]
    print('第二句违规被拦,文案核对通过:', e.args[0])
assert con.in_transaction, '事务应当仍然开着'
assert count('members') == 1, '第一句的行还在(未自动回滚)'
con.rollback()
assert count('members') == 0 and count('transactions') == 0, '应用显式回滚后应整体清空'
print('应用显式 rollback 后:会员 0 人、流水 0 行 -> 开卡整体回滚,不留半张卡')

print()
print('=== 验证二:同一 request_id 发两次,只扣一次 ===')
con.execute("insert into members(name) values('孙洁')")
con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            "values('充值',(select id from members where name='孙洁'),10000,10000,'TOPUP9001','2026-10-22 10:00:00')")
con.execute("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
            "values('消费',(select id from members where name='孙洁'),(select id from services where name='剪发'),1000,10000,-10000,'BUY009001','2026-10-22 11:00:00')")
bal = con.execute("select sum(balance_delta) from transactions t join members m on t.member_id=m.id where m.name='孙洁'").fetchone()[0]
assert bal == 0, f'余额应恰好花光,实际 {bal}'
print(f'充值 100 后消费 100,余额恰好花光: {bal/100:.2f} 元')

print('-- 2a 花光后裸 INSERT 重放(错误姿势):断言先撞余额触发器,而非唯一索引 --')
try:
    con.execute("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
                "values('消费',(select id from members where name='孙洁'),(select id from services where name='剪发'),1000,10000,-10000,'BUY009001','2026-10-22 11:00:00')")
    raise AssertionError('重放未被拦截')
except sqlite3.IntegrityError as e:
    assert e.args[0] == '余额不足', f'预期[余额不足](BEFORE 触发器先于唯一索引开枪),实际 {e.args[0]}'
    print('  报错文案核对通过: 余额不足  <- 重放拿不到原结果,只拿到报错')

print('-- 2b 后端规矩:写前查(正确姿势),重放返回原结果、绝不新增行 --')
con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            "values('充值',(select id from members where name='孙洁'),10000,10000,'TOPUP9003','2026-10-23 09:00:00')")
def idempotent_write(request_id, occurred='2026-10-23 11:00:00'):
    """幂等写入:事务内先按 request_id 查,有则返回原行,无则插入新行"""
    con.execute('BEGIN IMMEDIATE')
    row = con.execute("select id,type,amount,balance_delta from transactions where request_id=?", (request_id,)).fetchone()
    if row is None:
        con.execute("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
                    "values('消费',(select id from members where name='孙洁'),(select id from services where name='剪发'),1000,10000,-10000,?,?)",
                    (request_id, occurred))
        row = con.execute("select id,type,amount,balance_delta from transactions where request_id=?", (request_id,)).fetchone()
        con.execute('COMMIT')
        return row, '新写入'
    con.execute('COMMIT')
    return row, '返回原结果'

before = count('transactions')
row1, r1 = idempotent_write('BUY009002')          # 第一次:写入
row2, r2 = idempotent_write('BUY009002')          # 第二次(重放):应返回原结果
after = count('transactions')
assert r1 == '新写入' and r2 == '返回原结果', (r1, r2)
assert row1 == row2, '重放必须返回与第一次完全相同的行'
assert after - before == 1, f'重放不得新增行,行数变化 {after - before}'
print(f'  第一次 {r1} {row1};第二次 {r2} {row2};总行数 {before} -> {after}(只多 1 行)')

print('-- 2c 对照:余额没花光时,裸 INSERT 重放撞的是唯一索引(与 2a 凑成两种形态) --')
con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            "values('充值',(select id from members where name='孙洁'),10000,10000,'TOPUP9002','2026-10-23 10:00:00')")
try:
    con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
                "values('充值',(select id from members where name='孙洁'),10000,10000,'TOPUP9002','2026-10-23 10:00:00')")
    raise AssertionError('重放未被拦截')
except sqlite3.IntegrityError as e:
    assert e.args[0] == 'UNIQUE constraint failed: transactions.request_id', e.args[0]
    print('  报错文案核对通过: UNIQUE constraint failed: transactions.request_id')

print()
print('验证结论:事务边界由应用掌控(RAISE 只管单句);裸 INSERT 重放在两种余额状态下都拿不到原结果,'
      '幂等必须写前查+唯一索引兜底:重放返回原结果、绝不二次扣款。全部断言通过。')
