from backend.database.db import SessionLocal
from backend.database.models import Message


def add_message(role, content):

    db = SessionLocal()

    try:
        message = Message(
            role=role,
            content=content
        )

        db.add(message)
        db.commit()

    finally:
        db.close()


def get_history():

    db = SessionLocal()

    try:
        messages = db.query(Message).order_by(Message.id).all()

        return [
            {
                "role": msg.role,
                "content": msg.content
            }
            for msg in messages
        ]

    finally:
        db.close()


def clear_memory():

    db = SessionLocal()

    try:
        db.query(Message).delete()
        db.commit()

    finally:
        db.close()