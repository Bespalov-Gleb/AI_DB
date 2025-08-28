from __future__ import annotations
import re


def normalize_contact(value: str | None) -> str | None:
    """Нормализует контактные данные в свободной форме.
    - Заменяет слова 'собачка'/'собака'/'at' на '@'
    - Заменяет 'точка'/'dot' на '.'
    - Убирает пробелы вокруг '@' и '.'
    - Схлопывает повторяющиеся пробелы
    Возвращает None для пустого результата.
    """
    if value is None:
        return None
    s = str(value)
    if not s.strip():
        return None
    # унифицируем кириллицу/латиницу в маркерах
    s = re.sub(r"\s*(?:собачк[аи]?|собака|at|\(at\)|\[at\]|\{at\})\s*", "@", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*(?:точка|dot)\s*", ".", s, flags=re.IGNORECASE)
    # убрать пробелы вокруг @ и .
    s = re.sub(r"\s*@\s*", "@", s)
    s = re.sub(r"\s*\.\s*", ".", s)
    # множественные пробелы
    s = re.sub(r"\s+", " ", s).strip()
    return s or None

