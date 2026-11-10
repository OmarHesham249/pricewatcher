import pytest
from app.parsers.amazon_eg import AmazonEgParser
from app.parsers.noon_eg import NoonEgParser
from app.parsers.base import ParserLayoutChangedError


def test_amazon_eg_parser_success():
    sample_html = """
    <html>
      <body>
        <span id="productTitle">  أبل آيفون 15 برو 256 جيجا  </span>
        <span class="a-price"><span class="a-offscreen">49,999.00 جنيه</span></span>
      </body>
    </html>
    """
    parser = AmazonEgParser()
    result = parser.parse(sample_html)
    assert result.title == "أبل آيفون 15 برو 256 جيجا"
    assert result.price == 49999.0


def test_amazon_eg_parser_fails_loudly_on_layout_change():
    broken_html = "<html><body><div>CAPTCHA or new layout</div></body></html>"
    parser = AmazonEgParser()
    with pytest.raises(ParserLayoutChangedError):
        parser.parse(broken_html)


def test_noon_eg_parser_json_ld():
    sample_html = """
    <html>
      <head>
        <script type="application/ld+json">
          {"@type": "Product", "name": "Samsung Galaxy S24 Ultra", "offers": {"price": "46500"}}
        </script>
      </head>
    </html>
    """
    parser = NoonEgParser()
    result = parser.parse(sample_html)
    assert result.title == "Samsung Galaxy S24 Ultra"
    assert result.price == 46500.0
