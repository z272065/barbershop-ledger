# -*- coding: utf-8 -*-
"""一键演示:从 schema.sql 现建内存库,27 个场景覆盖全部 18 条数据库拦截规则。

判据:拦截场景要求报错文案与预期完全一致(不只是"被拦")——删掉或改坏任何一条规则,
对应场景立刻变红;放行场景要求成功落账。
时钟:期初窗口触发器的日期常量在内存库中分别调至远未来/过去,以同时演示"窗口开着"与
"窗口已关"两种状态,schema.sql 原文未动。
退出码:全部通过为 0,任一失败为 1(CI 可用)。

用法:python demo.py(仅依赖 Python 标准库,SQLite >= 3.37)
"""
import sqlite3, sys, os

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
assert sqlite3.sqlite_version_info >= (3, 37, 0), f'STRICT 需要 SQLite>=3.37,当前 {sqlite3.sqlite_version}'

with open('schema.sql', encoding='utf-8') as f:
    SCHEMA = f.read()

def build(window_open=True):
    """建内存库;window_open=False 时把期初窗口常量调到过去,演示窗口已关"""
    day = "'2099-12-31'" if window_open else "'2000-01-01'"
    con = sqlite3.connect(':memory:', isolation_level=None)
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript(SCHEMA.replace("'2026-12-15'", day))
    con.execute("insert into services(name,price) values('剪发',1000)")  # 10.00 元,金额一律整数分
    return con

con = build(True)
PASSED = 0
TOTAL = 0

def shot(sql, label, expect, expect_text=None, c=None):
    """expect='放' 要求落账成功;expect='拦' 要求报错文案与 expect_text 完全一致"""
    global PASSED,TOTAL
    c = c or con
    try:
        c.execute(sql); got = '放行'
        ok = expect == '放'
    except sqlite3.IntegrityError as e:
        got = '拦: ' + e.args[0]
        ok = expect == '拦' and e.args[0] == expect_text
    PASSED += ok
    TOTAL += 1
    print(f"{'PASS' if ok else 'FAIL'} [{label}] 预期{expect}" + (f'「{expect_text}」' if expect == '拦' else '') + f' -> {got}')

def bal(name, c=None):
    c = c or con
    return c.execute("select coalesce(sum(t.balance_delta),0) from transactions t "
                     "join members m on t.member_id=m.id where m.name=?", (name,)).fetchone()[0]

M = "(select id from members where name='%s')"  # 会员 id 子查询

print('=== 合法流:一位老会员的完整生命周期 ===')
con.execute("insert into members(name) values('王芳')")
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('迁移期初',{M % '王芳'},0,30000,'OPEN:60001','2026-10-20 09:00:00')",
     '① 老会员迁移:期初一行,余额 300 元', '放')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('充值',{M % '王芳'},10000,12000,'TOPUP0001','2026-10-21 10:00:00')",
     '② 充值 100 实收/到账 120(赠送 20 并入差值)', '放')
shot(f"insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     f"values('消费',{M % '王芳'},(select id from services where name='剪发'),1000,1000,-1000,'BUY000001','2026-10-22 11:00:00')",
     '③ 消费剪发 10 元(成交价快照随行)', '放')
shot(f"insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,reverses_id,occurred_at) "
     f"values('消费',{M % '王芳'},(select id from services where name='剪发'),1000,-1000,1000,'REV000001',"
     f"(select id from transactions where request_id='BUY000001'),'2026-10-22 11:00:00')",
     '④ 记错了:同类型红字冲正(七格镜像,金额取反,业务时间同原行)', '放')
print(f"    -> 王芳余额 = {bal('王芳')/100:.2f} 元 (300+120-10+10)")
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('退卡',{M % '王芳'},0,-42000,'CLOSE0001','2026-10-23 09:00:00')",
     '⑤ 退卡=一键清零(delta=当时全部余额,实退现金线下自定不进系统)', '放')
print(f"    -> 王芳余额 = {bal('王芳')/100:.2f} 元")

print()
print('=== 拦截流:每条规则一个场景,报错文案与预期逐字核对 ===')
print('-- 金额与余额(演示会员先充值 100 元,确保每条规则独立开枪)--')
con.execute("insert into members(name) values('李强')")
con.execute(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            f"values('充值',{M % '李强'},10000,10000,'TOPUP0004','2026-10-22 10:00:00')")
shot(f"insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     f"values('消费',{M % '李强'},(select id from services where name='剪发'),1000,12000,-12000,'BUY000002','2026-10-22 11:00:00')",
     '⑥ 余额不足的扣卡(卡里只有 100,扣 120)', '拦', '余额不足')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('充值',{M % '李强'},-100,-100,'TOPUP0002','2026-10-22 11:00:00')",
     '⑦ 充值金额为负(方向反)', '拦', '充值金额必须大于0/充值到账金额不能少于实收')
shot(f"insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     f"values('消费',{M % '李强'},(select id from services where name='剪发'),1000,500,-400,'BUY000003','2026-10-22 11:00:00')",
     '⑧ 消费金额与余额变动不相等(500 对 -400)', '拦', '消费金额必须等于金额变动/消费金额必须大于0')
shot(f"insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     f"values('消费',{M % '李强'},(select id from services where name='剪发'),1000,-80,80,'BUY000004','2026-10-22 11:00:00')",
     '⑨ 野生红字:冒充负数消费凭空加钱(amount=-80/delta=+80)', '拦', '消费金额必须等于金额变动/消费金额必须大于0')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('退卡',{M % '李强'},5,-1000,'CLOSE0002','2026-10-23 09:00:00')",
     '⑩ 退卡带金额(退卡的 amount 必须是 0,实退现金线下自定)', '拦', '退卡时金额变动必须为负数,比如扣10就是-10,不是+10')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('退卡',{M % '李强'},0,-3000,'CLOSE0003','2026-10-23 09:00:00')",
     '⑪ 退卡金额与全部余额不符(余额 100,退 30)', '拦', '退卡时退的钱必须等于账户全部余额')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('消费',{M % '李强'},1000,-1000,'BUY000005','2026-10-22 11:00:00')",
     '⑫ 消费缺服务与单价快照', '拦', '服务或单价快照不能为空')
shot(f"insert into transactions(type,member_id,service_id,price_snapshot,amount,balance_delta,request_id,occurred_at) "
     f"values('充值',{M % '李强'},(select id from services where name='剪发'),1000,100,120,'TOPUP0003','2026-10-22 11:00:00')",
     '⑬ 充值带服务与单价快照(只有消费才记)', '拦', '充值/退卡/迁移期初服务和单价快照必须为空')

print('-- 时间与幂等键 --')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at,recorded_at) "
     f"values('充值',{M % '李强'},100,120,'TOPUP0006','2026-10-26 09:00:00','2026-10-25 09:00:00')",
     '⑭ 补录时间晚于系统记账时间(年份手误防线)', '拦', '补录时间不能晚于系统记账时间')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('充值',{M % '李强'},100,120,'SHORT01','2026-10-22 11:00:00')",
     '⑮ 幂等键长度不足 8(短键漏传会被当重放)', '拦', 'CHECK constraint failed: chk_reqlen')

print('-- 期初规则 --')
con.execute("insert into members(name) values('赵六')")
con.execute(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            f"values('充值',{M % '赵六'},100,100,'TOPUP0007','2026-10-22 10:00:00')")
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('迁移期初',{M % '赵六'},0,3000,'OPEN:60077','2026-10-20 09:00:00')",
     '⑯ 已有流水的会员补录期初(白送余额的后门)', '拦', '此人已有流水,期初必须是第一笔')
con.execute("insert into members(name) values('孙七')")
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('迁移期初',{M % '孙七'},50,3000,'OPEN:60088','2026-10-20 09:00:00')",
     '⑰ 期初带金额(期初不进营业额)', '拦', '迁移期初金额必须为0')
closed = build(False)
closed.execute("insert into members(name) values('钱八')")
shot("insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     "values('迁移期初',(select id from members where name='钱八'),0,3000,'OPEN:60099','2026-10-20 09:00:00')",
     '⑱ 割接窗口已关后补导期初(触发器读数据库时钟,倒填日期无效)', '拦', '迁移期初窗口已关', c=closed)

print('-- 红字冲正三道关 --')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     f"values('充值',{M % '李强'},-10000,-10000,'REV000004',"
     f"(select id from transactions where request_id='TOPUP0004'),'2026-10-22 10:00:00')",
     '⑲ 合法红字:冲正一笔充值(余额复原)', '放')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     f"values('充值',{M % '李强'},10000,10000,'REV000005',"
     f"(select id from transactions where request_id='REV000004'),'2026-10-22 10:00:00')",
     '⑳ 冲一张红字行(撤销的撤销不允许)', '拦', '原行已是红字')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     f"values('充值',{M % '李强'},-10000,-10000,'REV000006',"
     f"(select id from transactions where request_id='TOPUP0004'),'2026-10-22 10:00:00')",
     '㉑ 同一笔冲第二次', '拦', '原行已被冲过')
con.execute(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
            f"values('充值',{M % '李强'},10000,10000,'TOPUP0005','2026-10-22 12:00:00')")
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,reverses_id,occurred_at) "
     f"values('充值',{M % '李强'},-100,-10000,'REV000007',"
     f"(select id from transactions where request_id='TOPUP0005'),'2026-10-22 12:00:00')",
     '㉒ 假镜像:金额没翻对(该 -10000 写成 -100)', '拦', '不是精确镜像')

print('-- 禁删与类型 --')
shot("delete from members where name='孙七'", '㉓ 删除会员(历史账目的主体)', '拦', '会员表禁止删除')
shot("delete from services", '㉔ 删除服务', '拦', '服务表禁止删除')
shot("delete from tx_types", '㉕ 删除类型字典', '拦', '操作类型表禁止删除')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('赠送',{M % '李强'},0,80,'GIFT000001','2026-10-22 11:00:00')",
     '㉖ 字典外自造类型(赠送已并入充值差值)', '拦', '未知的操作类型')
shot(f"insert into transactions(type,member_id,amount,balance_delta,request_id,occurred_at) "
     f"values('充值',{M % '李强'},0,50,'ZER00001','2026-10-26 12:00:00')",
     '㉗ 充值金额为 0','拦','充值金额必须大于0/充值到账金额不能少于实收')

total = con.execute("select count(*), sum(case when reverses_id is null then 1 else -1 end) from transactions").fetchone()
print()
print(f'对账:流水 {total[0]} 行,有效笔数(正行-红字)= {total[1]},场景通过 {PASSED}/{TOTAL}')
if PASSED == TOTAL and bal("王芳") == 0 and bal("李强") == 10000:
    print('全部通过:18 条拦截规则各有一个文案精确核对的场景,任何一条被删改,对应场景即变红。')
else:
    print('!! 有场景失败或对账不符')
    sys.exit(1)
