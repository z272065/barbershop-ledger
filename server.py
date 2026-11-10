import bcrypt
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Response, Depends, Cookie
from sqlalchemy import create_engine, event, select, func
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import Member, Transaction, Service, Setting, LoginSession, now_bj
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import datetime, timezone, timedelta


class AppConfig(BaseSettings):
    shop_password_hash: str
    model_config = SettingsConfigDict(env_file=".env")


config = AppConfig()


class DengluRequest(BaseModel):
    password: str


class ConsumeRequest(BaseModel):
    amount: int
    member_id: int
    request_id: str


class RechargeRequest(BaseModel):
    member_id: int | None = None
    name: str | None = None
    phone: str | None = None
    request_id: str
    amount: int


class ChexiaoRequest(BaseModel):
    reverses_id: int
    request_id: str


class QinglingRequest(BaseModel):
    member_id: int
    request_id: str


DB_PATH = Path(__file__).resolve().parent / "practice3.db"
engine = create_engine(f"sqlite:///{DB_PATH}")


@event.listens_for(engine, "connect")
def _pragmas(dbapi_connection, connection_record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA recursive_triggers=ON")
    dbapi_connection.isolation_level = None


@event.listens_for(engine, "begin")
def _begin(conn):
    conn.exec_driver_sql("BEGIN IMMEDIATE")


app = FastAPI()


def require_login(session: str | None = Cookie(default=None)):
    if session is None:
        raise HTTPException(401, detail="未登录")
    with Session(engine) as s:
        exist = s.scalar(select(LoginSession).where(LoginSession.token == session))
        if exist is None:
            raise HTTPException(401, detail="登录态不存在")
        if exist.expires_at <= now_bj():
            raise HTTPException(401, "登录已过期,请重新登录")
        return {"detail": "通过"}


@app.get("/members", dependencies=[Depends(require_login)])
def find_members(last4: str):
    with Session(engine) as s:
        li = []
        if len(last4) != 4 or not last4.isdigit():
            raise HTTPException(400, detail="这不是后四位手机尾号")
        people = s.scalars(select(Member).where(Member.phone.like("%" + last4))).all()
        for person in people:
            bal = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == person.id
                )
            )
            if bal is None:
                bal = 0
            pesondict = {
                "personid": person.id,
                "personname": person.name,
                "personphone": person.phone,
                "personmoneyfen": bal,
            }
            li.append(pesondict)
    return li


@app.post("/transactions", dependencies=[Depends(require_login)])
def cost(conque: ConsumeRequest):
    with Session(engine) as s:
        exist = s.scalar(
            select(Transaction).where(Transaction.request_id == conque.request_id)
        )
        if exist is None:
            people = s.scalar(select(Member).where(Member.id == conque.member_id))
            if people is None:
                raise HTTPException(404, detail=f"没有{conque.member_id}这个会员")
            bal = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == conque.member_id
                )
            )
            if bal is None:
                bal = 0
            if bal >= conque.amount:
                price = s.scalar(select(Service.price).where(Service.id == 1))
                t = Transaction(
                    type="消费",
                    member_id=conque.member_id,
                    service_id=1,
                    price_snapshot=price,
                    amount=conque.amount,
                    balance_delta=-conque.amount,
                    request_id=conque.request_id,
                    occurred_at=now_bj(),
                )
                try:
                    s.add(t)
                    s.commit()
                except IntegrityError as e:
                    raise HTTPException(400, detail=e.orig.args[0])
                return {"personyuefen": bal - conque.amount}

            else:
                raise HTTPException(400, detail=f"余额不足,还有{bal}分")
        else:
            if (
                exist.type != "消费"
                or exist.reverses_id is not None
                or exist.member_id != conque.member_id
            ):
                raise HTTPException(409, detail="和第一次请求不是一个操作")
            bal = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == exist.member_id,
                    Transaction.id <= exist.id,
                )
            )
            return {"personyuefen": bal}


@app.get("/transactions", dependencies=[Depends(require_login)] )
def list_transactions(member_id: int | None = None):
    with Session(engine) as s:
        li = []
        st = []
        today = now_bj()[:10]
        if member_id is None:
            all_rows = s.scalars(
                select(Transaction)
                .where(Transaction.occurred_at >= today)
                .order_by(Transaction.id.desc())
            ).all()
            for r in all_rows:
                t = {
                    "id": r.id,
                    "type": r.type,
                    "amount": r.amount,
                    "balance_delta": r.balance_delta,
                    "occurred_at": r.occurred_at,
                    "reverses_id": r.reverses_id,
                    "name": s.scalar(
                        select(Member).where(Member.id == r.member_id)
                    ).name,
                }
                li.append(t)
            return li
        else:
            rows = s.scalars(select(Member).where(Member.id == member_id)).all()
            if not rows:
                raise HTTPException(404, detail=f"没有编号为{member_id}的会员")
            else:
                peopletransactions = s.scalars(
                    select(Transaction)
                    .where(Transaction.member_id == member_id)
                    .order_by(Transaction.id.desc())
                ).all()
                me = s.scalar(select(Member).where(Member.id == member_id))
                for p in peopletransactions:
                    t = {
                        "id": p.id,
                        "type": p.type,
                        "amount": p.amount,
                        "balance_delta": p.balance_delta,
                        "occurred_at": p.occurred_at,
                        "reverses_id": p.reverses_id,
                        "name": me.name,
                    }
                    st.append(t)
                return st


@app.post("/recharge", dependencies=[Depends(require_login)])
def recharge(conque: RechargeRequest):
    with Session(engine) as s:
        exist = s.scalar(
            select(Transaction).where(Transaction.request_id == conque.request_id)
        )
        if exist is None:
            if conque.member_id is not None:
                person_id = s.scalar(
                    select(Member.id).where(Member.id == conque.member_id)
                )
                if person_id is None:
                    raise HTTPException(404, detail=f"没有{conque.member_id}这个会员")
            else:
                if conque.name is None or conque.phone is None:
                    raise HTTPException(400, detail="新顾客没填姓名或电话")
                person = Member(
                    name=conque.name, phone=conque.phone, created_at=now_bj()
                )
                s.add(person)
                s.flush()
                person_id = person.id

            rate = int(
                s.scalar(
                    select(Setting.value).where(Setting.key == "recharge_bonus_rate")
                )
            )
            amount = conque.amount
            bonus = amount * rate // 100
            delta = amount + bonus
            t = Transaction(
                type="充值",
                member_id=person_id,
                amount=amount,
                balance_delta=delta,
                request_id=conque.request_id,
                occurred_at=now_bj(),
            )

            balance = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == person_id
                )
            )
            if balance is None:
                balance = 0
            try:
                s.add(t)
                s.commit()
            except IntegrityError as e:
                raise HTTPException(400, detail=e.orig.args[0])
            return {"personyuefen": balance + delta, "personid": person_id}
        else:
            if exist.type != "充值" or exist.reverses_id is not None:
                raise HTTPException(409, detail="和第一次请求不是一个操作")
            if conque.member_id is not None:
                if exist.member_id != conque.member_id:
                    raise HTTPException(409, detail="和第一次请求不是一个操作")
            else:
                first = s.scalar(select(Member).where(Member.id == exist.member_id))
                if conque.name != first.name or conque.phone != first.phone:
                    raise HTTPException(409, detail="和第一次请求不是一个操作")
            balance = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == exist.member_id,
                    Transaction.id <= exist.id,
                )
            )
            if balance is None:
                balance = 0
            return {"personyuefen": balance, "personid": exist.member_id}


@app.get("/recharge_preview", dependencies=[Depends(require_login)])
def daozhang(amount: int):
    with Session(engine) as s:
        if amount <= 0:
            raise HTTPException(400, detail="充值金额必须大于0")
        rate = int(
            s.scalar(select(Setting.value).where(Setting.key == "recharge_bonus_rate"))
        )
        bonus = amount * rate // 100
        daozhang = amount + bonus
    return {"zengsongfen": bonus, "daozhangfen": daozhang}


@app.post("/void", dependencies=[Depends(require_login)])
def chexiao(cx: ChexiaoRequest):
    with Session(engine) as s:
        exist = s.scalar(
            select(Transaction).where(Transaction.request_id == cx.request_id)
        )
        if exist is not None:
            if exist.reverses_id != cx.reverses_id:
                raise HTTPException(409, detail="和第一次请求不是一个操作")
            personyuefen = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == exist.member_id,
                    Transaction.id <= exist.id,
                )
            )
            return {"personyuefen": personyuefen}
        else:
            ab = s.scalar(select(Transaction).where(Transaction.id == cx.reverses_id))
            if ab is None:
                raise HTTPException(404, detail=f"没有{cx.reverses_id}这个流水")
            t = Transaction(
                type=ab.type,
                member_id=ab.member_id,
                price_snapshot=ab.price_snapshot,
                occurred_at=ab.occurred_at,
                amount=-ab.amount,
                balance_delta=-ab.balance_delta,
                request_id=cx.request_id,
                reverses_id=cx.reverses_id,
                service_id=ab.service_id,
            )
            try:
                s.add(t)
                s.commit()
            except IntegrityError as e:
                raise HTTPException(400, detail=e.orig.args[0])
            personyuefen = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == ab.member_id
                )
            )
            return {"personyuefen": personyuefen}


@app.post("/refund", dependencies=[Depends(require_login)])
def qingling(zero: QinglingRequest):
    with Session(engine) as s:
        bal = s.scalar(
            select(func.sum(Transaction.balance_delta)).where(
                Transaction.member_id == zero.member_id
            )
        )
        mideng = s.scalar(
            select(Transaction).where(Transaction.request_id == zero.request_id)
        )
        if mideng is not None:
            if (
                mideng.member_id != zero.member_id
                or mideng.type != "退卡"
                or mideng.reverses_id is not None
            ):
                raise HTTPException(409, detail="和第一次请求不是一个操作")
            return {"personyuefen": 0}
        else:
            people = s.scalar(select(Member).where(Member.id == zero.member_id))
            if people is None:
                raise HTTPException(404, detail=f"不存在{zero.member_id}这个会员")
            if bal == 0:
                raise HTTPException(400, detail="余额已经为0")
            t = Transaction(
                type="退卡",
                amount=0,
                balance_delta=-bal,
                request_id=zero.request_id,
                occurred_at=now_bj(),
                member_id=zero.member_id,
            )
            try:
                s.add(t)
                s.commit()
            except IntegrityError as e:
                raise HTTPException(400, detail=e.orig.args[0])
            return {"personyuefen": 0}


@app.post("/login")
def denglu(mima: DengluRequest, response: Response):
    if not bcrypt.checkpw(mima.password.encode(), config.shop_password_hash.encode()):
        raise HTTPException(401, detail="密码错误")
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone(timedelta(hours=8))) + timedelta(days=30)
    ).strftime("%Y-%m-%d %H:%M:%S")
    with Session(engine) as s:
        l = LoginSession(token=token, expires_at=expires_at)
        s.add(l)
        s.commit()
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=2592000,
        )
        return {"detail": "登录成功"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
