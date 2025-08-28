from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.strict_parse import parse_strict_listing, ParseError


class PreviewRequest(BaseModel):
    text: str


router = APIRouter()


@router.post("/preview", summary="Предпросмотр строгого парсинга заявки")
def ai_preview(payload: PreviewRequest) -> dict:
    try:
        parsed = parse_strict_listing(payload.text)
        return {"type": parsed.type.value, "parsed": parsed.model_dump()}
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Ошибка формата: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))