"""Shared bounded display-name contract for Steam, lobbies and native rosters."""
import unicodedata

MAX_NAME_UTF8_BYTES=128


def display_name(value):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('Steam did not supply a player name.')
    try: raw=value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('Player names must be valid UTF-8.') from exc
    if len(raw)>MAX_NAME_UTF8_BYTES:
        raise ValueError('Player names must fit within 128 UTF-8 bytes.')
    if any(unicodedata.category(char) in ('Cc','Cs','Zl','Zp') for char in value):
        raise ValueError('Player names cannot contain control characters or line breaks.')
    return value
