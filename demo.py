# -*- coding: utf-8 -*-
"""一键演示:从 schema.sql 现建一个内存库,把全部业务规则的执法效果跑给你看。

用法:python demo.py   (仅依赖 Python 标准库,SQLite >= 3.37)
预期:所有场景 PASS,结尾输出余额对账。
"""
import sqlite3, sys, os

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

assert sqlite3.sqlite_version_info >= (3, 37, 0), f'STRICT 需要 SQLite>=3.37,当前 {sqlite3.sqlite_version}'

con = sqlite3.connect(':memory:', isolation_level=None)
con.execute('PRAGMA foreign_keys=ON')
with open('schema.sql', encoding='utf-8') as f:
    con.executescript(f.read())

PASSED = 0

def shot(sql, label, expect):
    """expect='放' 预期放行落账;expect='拦' 预期被数据库拒绝"""
    global PASSED
    try:
        con.execute(sql); got = '放行'
    except sqlite3.IntegrityError as e:
        got = '拦: ' + e.args[0].split('CHECK|UNIQUE|RAISE')[-1]
    ok = (expect == '拦') == got.startswith('拦')
    PASSED += ok
    print(f"{'PASS' if ok else 'FAIL'} [{label}] 预期{expect} -> {got}")

def balance(name):
    return con.execute(
        "select coalesce(sum(t.balance_delta),0) from transactions t "
        "join members m on t.member_id=m.id where m.name=?", (name,)).fetchone()[0]

con.execute("insert into services(name,price) values('剪发',1000)")  # 10.00 元,金额一律整数分

print('=== 合法流:一位老会员的完整生命周期 ===')
con.execute("insert into members(name) values('王芳')")
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('迁移期初',(select id from members where name='王芳'),0,30000,'OPEN:60001','2026-10-20 09:00:00')",
     '① 老会员迁移:期初一行,余额 300 元', '放')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('充值',(select id from members where name='王芳'),10000,12000,'TOPUP0001','2026-10-21 10:00:00')",
     '② 充值 100 实收/到账 120(赠送 20 并入差值)', '放')
shot("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     "values('消费',(select id from members where name='王芳'),(select id from services where name='剪发'),1000,1000,-1000,'BUY000001','2026-10-22 11:00:00')",
     '③ 消费剪发 10 元(成交价快照随行)', '放')
shot("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,reverses_id,occurred_at) "
     "values('消费',(select id from members where name='王芳'),(select id from services where name='剪发'),1000,-1000,1000,'REV000001',"
     "(select id from transactions where request_id='BUY000001'),'2026-10-22 11:00:00')",
     '④ 记错了:同类型红字冲正(七格镜像,金额取反,业务时间同原行)', '放')
print(f"    -> 王芳余额 = {balance('王芳')}/100 = {balance('王芳')/100:.2f} 元 (期初300+充值120-消费10+冲正10=420)")
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('退卡',(select id from members where name='王芳'),0,-42000,'CLOSE0001','2026-10-23 09:00:00')",
     '⑤ 退卡=一键清零(delta=当时全部余额,实退现金线下自定不进系统)', '放')
print(f"    -> 王芳余额 = {balance('王芳')}/100 = {balance('王芳')/100:.2f} 元")

print()
print('=== 拦截流:数据库替店主守住每一条规矩(文案即触发器原文) ===')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('迁移期初',(select id from members where name='王芳'),0,9999,'OPEN:60001x','2026-10-20 09:00:00')",
     '⑥ 给已有流水的会员再塞期初(白送余额的后门)', '拦')
con.execute("insert into members(name) values('李强')")
shot("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     "values('消费',(select id from members where name='李强'),(select id from services where name='剪发'),1000,1000,-1000,'BUY000002','2026-10-22 11:00:00')",
     '⑦ 余额不足的扣卡(不存在扣到清零)', '拦')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('充值',(select id from members where name='李强'),-10000,-10000,'TOPUP0002','2026-10-22 11:00:00')",
     '⑧ 充值金额方向反(负数)', '拦')
shot("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     "values('消费',(select id from members where name='李强'),(select id from services where name='剪发'),1000,500,-400,'BUY000003','2026-10-22 11:00:00')",
     '⑨ 消费金额与余额变动不相等(500 对 -400)', '拦')
shot("insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     "values('消费',(select id from members where name='李强'),(select id from services where name='剪发'),1000,-80,80,'BUY000004','2026-10-22 11:00:00')",
     '⑩ 野生红字:冒充负数消费凭空加钱(amount=-80/delta=+80)', '拦')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('赠送',(select id from members where name='李强'),0,80,'GIFT000001','2026-10-22 11:00:00')",
     '⑪ 字典外自造类型(赠送已并入充值差值,不设独立类型)', '拦')
shot("delete from members where name='李强'",
     '⑫ 删除会员(历史账目的主体,禁删)', '拦')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at,recorded_at) "
     "values('充值',(select id from members where name='李强'),100,120,'TOPUP0003','2026-10-26 09:00:00','2026-10-25 09:00:00')",
     '⑬ 补录时间晚于系统记账时间(年份手误防线)', '拦')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('充值',(select id from members where name='李强'),100,120,'SHORT01','2026-10-22 11:00:00')",
     '⑭ 幂等键长度不足 8(短键漏传会被当重放)', '拦')

con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            "values('充值',(select id from members where name='李强'),100,120,'TOPUP0004','2026-10-22 11:00:00')")
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     "values('充值',(select id from members where name='李强'),-100,-120,'REV000002',"
     "(select id from transactions where request_id='TOPUP0004'),'2026-10-22 11:00:00')",
     '⑮ 合法红字冲正充值', '放')
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     "values('充值',(select id from members where name='李强'),-100,-120,'REV000003',"
     "(select id from transactions where request_id='TOPUP0004'),'2026-10-22 11:00:00')",
     '⑯ 同一笔冲第二次(一笔只能一冲)', '拦')
con.execute("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            "values('充值',(select id from members where name='李强'),100,120,'TOPUP0005','2026-10-22 11:00:00')")
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     "values('充值',(select id from members where name='李强'),-100,-100,'REV000004',"
     "(select id from transactions where request_id='TOPUP0005'),'2026-10-23 12:00:00')",
     '⑰ 假镜像:金额没翻对+业务时间对不上原行', '拦')

print()
total = con.execute("select count(*), sum(case when reverses_id is null then 1 else -1 end) from transactions").fetchone()
print(f'对账:流水 {total[0]} 行,有效笔数(正行-红字)= {total[1]},全部 {PASSED} 个场景 PASS' if PASSED == 17 else f'!! 有场景 FAIL,仅 {PASSED}/17 PASS')
