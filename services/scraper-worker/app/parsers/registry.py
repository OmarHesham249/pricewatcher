from app.parsers.base import BaseStoreParser
from app.parsers.amazon_eg import AmazonEgParser
from app.parsers.noon_eg import NoonEgParser

PARSERS: dict[str, BaseStoreParser] = {
    "amazon": AmazonEgParser(),
    "noon": NoonEgParser(),
}


def get_parser(store: str) -> BaseStoreParser:
    if store not in PARSERS:
        raise KeyError(f"Unsupported store parser: {store}")
    return PARSERS[store]
