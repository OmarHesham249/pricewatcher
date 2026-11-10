from abc import ABC, abstractmethod
from dataclasses import dataclass


class ParserLayoutChangedError(Exception):
    """Raised loudly when a store changes its HTML layout so Prometheus can alert."""


@dataclass
class ScrapedProduct:
    title: str
    price: float
    currency: str = "EGP"


class BaseStoreParser(ABC):
    store_name: str

    @abstractmethod
    def parse(self, html: str) -> ScrapedProduct:
        raise NotImplementedError

    @staticmethod
    def clean_price(raw_text: str) -> float:
        cleaned = (
            raw_text.replace("جنيه", "")
            .replace("ج.م", "")
            .replace("EGP", "")
            .replace(",", "")
            .replace("٬", "")
            .strip()
        )
        arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
        cleaned = cleaned.translate(arabic_digits)
        return float(cleaned)
