"""알림 자리 (아직 만들지 않음).

나중에 신호가 바뀌면 텔레그램이나 이메일로 보내려면 여기에 send() 를 채운다.
토큰은 .env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 에서 읽는다 (코드에 적지 않는다).
"""


def send(title: str, body: str) -> bool:
    """알림을 보낸다. 지금은 아무것도 하지 않고 False 를 돌려준다."""
    return False
