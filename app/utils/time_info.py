from datetime import datetime


def get_time_information() -> str:
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y, %I:%M %p")