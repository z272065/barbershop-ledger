from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, event, select, func
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import Member, Transaction, Service, Setting, now_bj


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


DB_PATH = Path(__file__).resolve().parent / "practice3.db"
engine = create_engine(f"sqlite:///{DB_PATH}")


@event.listens_for(engine, "connect")
def _pragmas(dbapi_connection, connection_record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA recursive_triggers=ON")


app = FastAPI()


@app.get("/members")
def find_members(last4: str):
    with Session(engine) as s:
        li = []

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


@app.post("/transactions")
def cost(conque: ConsumeRequest):
    with Session(engine) as s:
        exist = s.scalar(
            select(Transaction).where(Transaction.request_id == conque.request_id)
        )
        if exist is None:
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
                yuedict = {"personyuefen": bal - conque.amount}
                return yuedict
            else:
                raise HTTPException(400, detail=f"余额不足,还有{bal}分")
        else:
            bal = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == conque.member_id
                )
            )
            yuedict = {"personyuefen": bal}
            return yuedict


@app.post("/recharge")
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
            balance = s.scalar(
                select(func.sum(Transaction.balance_delta)).where(
                    Transaction.member_id == exist.member_id
                )
            )
            if balance is None:
                balance = 0
            return {"personyuefen": balance, "personid": exist.member_id}


@app.get("/recharge_preview")
def daozhang(amount: int):
    with Session(engine) as s:
        rate = int(
            s.scalar(select(Setting.value).where(Setting.key == "recharge_bonus_rate"))
        )
        bonus = amount * rate // 100
        daozhang = amount + bonus
    return {"zengsongfen": bonus, "daozhangfen": daozhang}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
