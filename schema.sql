-- 理发店会员系统 建库脚本 schema.sql
-- 内容:四张 STRICT 表 + 类型字典数据 + 三条索引 + 七条触发器(三禁删/未知类型兜底/trg_rule 九句/trg_opening/trg_reverse)
-- 依赖:SQLite >= 3.37(STRICT 要求);建库后每次连接需 PRAGMA foreign_keys=ON,生产端连接另加 PRAGMA recursive_triggers=ON
-- 用法:在空库上整文件执行;建表顺序已按依赖排好(先父后子),tx_types 字典数据随脚本就位,随后即可插入业务数据
-- 迁移窗口日常量在 trg_opening 第二臂(当前占位 '2026-12-15'),正式定档后改此常量并重建该触发器

CREATE TABLE members (
    id integer primary key,
    name text,
    phone text,
    note text,
    created_at text,
    legacy_card_no text unique,
	CONSTRAINT chk_phone CHECK(phone is NULL or phone not glob '*[^0-9]*'),
	CONSTRAINT chk_na_ph CHECK(name is NOT NULL or phone is NOT NULL),
	CONSTRAINT chk_credat CHECK(datetime(created_at)is created_at)
)STRICT;

CREATE TABLE services (
    id integer primary key,
    name text not null,
    price integer not null,
	CONSTRAINT chk_price CHECK (price > 0)
)STRICT;

CREATE TABLE tx_types(name text primary key)STRICT;

CREATE TABLE transactions(
    id integer primary key,
    type text not null references tx_types(name),
    member_id integer not null references members(id),
    service_id integer references services(id),
    price_snapshot integer,
    amount integer not null,
    balance_delta integer not null,
    request_id text not null unique,
    reverses_id integer references transactions(id),
    occurred_at text not null,
	recorded_at text not null DEFAULT(datetime('now','+8 hours')),
	CONSTRAINT chk_service_price CHECK((service_id is NULL AND price_snapshot is NULL)or(service_id is NOT NULL AND price_snapshot is NOT NULL AND price_snapshot>0)),
	CONSTRAINT chk_occedat CHECK (datetime(occurred_at) is occurred_at),
	CONSTRAINT chk_reqlen CHECK (length(request_id)>=8),
	CONSTRAINT chk_recedat CHECK(datetime(recorded_at) is recorded_at)
)STRICT;

insert into tx_types (name) values
('充值'),
('消费'),
('退卡'),
('迁移期初');

CREATE INDEX idx_member_time on transactions(member_id,occurred_at);

CREATE UNIQUE INDEX idx_member on transactions(member_id) where type='迁移期初' and reverses_id is null;

CREATE UNIQUE INDEX idx_reverses on transactions(reverses_id) WHERE reverses_id is not NULL;

create trigger trg_no_del_memb before delete on members
begin
select raise(abort,'会员表禁止删除');
end;

create trigger trg_no_del_serv before delete on services
begin
select raise(abort,'服务表禁止删除');
end;

create trigger trg_no_del_txtp before delete on tx_types
begin
select raise(abort,'操作类型表禁止删除');
end;

create trigger trg_no_in_tran before insert on transactions
when new.type not in ('充值','消费','退卡','迁移期初')
begin
select raise(abort,'未知的操作类型');
end;

create trigger trg_rule before insert on transactions
begin
select case when new.reverses_id is null and new.type='充值' and (new.amount <= 0 or new.balance_delta < new.amount) then raise(abort,'充值金额必须大于0/充值到账金额不能少于实收') end;
select case when new.reverses_id is null and new.type='消费' and (new.amount<=0 or new.balance_delta!=-new.amount) then raise(abort,'消费金额必须等于金额变动/消费金额必须大于0') end;
select case when new.reverses_id is null and new.type='退卡' and (new.amount!=0 or new.balance_delta>=0) then raise(abort,'退卡时金额变动必须为负数,比如扣10就是-10,不是+10') end;
select case when new.type='迁移期初' and new.amount!=0 then raise(abort,'迁移期初金额必须为0') end;
select case when new.type='消费' and (new.service_id is NULL or new.price_snapshot is NULL) then raise(abort,'服务或单价快照不能为空') end;
select case when (new.type='充值' or new.type='退卡' or new.type='迁移期初') and (new.service_id is not NULL and new.price_snapshot is not NULL) then raise(abort,'充值/退卡/迁移期初服务和单价快照必须为空') end;
select case when new.reverses_id is null and new.type='退卡' and (new.balance_delta!=-(select coalesce(sum(balance_delta),0) from transactions where member_id=new.member_id)) then raise(abort,'退卡时退的钱必须等于账户全部余额') end;
select case when new.balance_delta+(select coalesce(sum(balance_delta),0) from transactions where member_id=new.member_id)<0 then raise(abort,'余额不足') end;
select case when new.occurred_at>new.recorded_at then raise(abort,'补录时间不能晚于系统记账时间') end;
end;

create trigger trg_opening before insert on transactions
when new.type='迁移期初'
begin
select case when (select count(*)>0 from transactions where member_id=new.member_id) then raise(abort,'此人已有流水,期初必须是第一笔') end;
select case when date('now','+8 hours')>'2026-12-15' then raise(abort,'迁移期初窗口已关') end;
end;

create trigger trg_reverse before insert on transactions
when new.reverses_id is not null
begin
select case when (select reverses_id from transactions where id=new.reverses_id)is not null then raise(abort,'原行已是红字') end;
select case when (select count(*)>0 from transactions where reverses_id=new.reverses_id) then raise(abort,'原行已被冲过') end;
select case when new.type is not (select type from transactions where id=new.reverses_id) or new.member_id is not (select member_id from transactions where id=new.reverses_id) or new.service_id is not (select service_id from transactions where id=new.reverses_id) or new.price_snapshot is not (select price_snapshot from transactions where id=new.reverses_id) or new.amount is not -(select amount from transactions where id=new.reverses_id) or new.balance_delta is not -(select balance_delta from transactions where id=new.reverses_id) or new.occurred_at is not (select occurred_at from transactions where id=new.reverses_id) then raise(abort,'不是精确镜像') end;
end;