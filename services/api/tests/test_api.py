from app.main import detect_store
import pytest
from fastapi import HTTPException


def test_detect_store_valid():
    assert detect_store("https://www.amazon.eg/-/ar/dp/B0CHX2F5QT") == "amazon"
    assert detect_store("https://www.noon.com/egypt-ar/item/p/") == "noon"


def test_detect_store_invalid():
    with pytest.raises(HTTPException) as exc:
        detect_store("https://www.ebay.com/itm/12345")
    assert exc.value.status_code == 400
    assert "غير مدعوم" in exc.value.detail
