from types import SimpleNamespace

import pytest

from src.vision.service import ArmoredVision
import src.vision.service as vision_service
from src.vision.modules.v1 import shopee_resolver as resolver
from src.vision.modules.v1.shopee_api import ShopeeProductNotFoundError
from src.vision.contracts import VisionUnresolvedError


class FakeAPI:
    def __init__(self, product=None, error=None):
        self.product = product or {
            "productName": "Produto teste",
            "itemId": "28131151896",
            "shopId": "198996577",
            "shopName": "Loja teste",
            "priceMin": 10,
            "sales": 123,
            "imageUrl": "https://img.example/test.jpg",
            "offerLink": "https://s.shopee.com.br/affiliate-test",
        }
        self.error = error
        self.calls = []

    def get_exact_product(self, shop_id, item_id):
        self.calls.append(("get_exact_product", shop_id, item_id))
        if self.error:
            raise self.error
        return self.product

    def affiliate_link_for_product(self, product):
        self.calls.append(("affiliate_link_for_product", product["itemId"]))
        return product["offerLink"]


def test_armored_vision_resolves_exact_product_and_returns_v1_result(monkeypatch):
    monkeypatch.setattr(
        vision_service,
        "resolve_short_url",
        lambda url: SimpleNamespace(
            original_url=url,
            resolved_url="https://shopee.com.br/product/198996577/28131151896",
            shop_id="198996577",
            item_id="28131151896",
        ),
    )
    api = FakeAPI()
    item = SimpleNamespace(original_url="https://s.shopee.com.br/1BEcv24py4")

    result = ArmoredVision(api=api).identify(item)

    assert result.affiliate_name == "Produto teste"
    assert result.affiliate_url == "https://s.shopee.com.br/affiliate-test"
    assert result.affiliate_urls == ("https://s.shopee.com.br/affiliate-test",)
    assert result.publication_caption is None
    assert result.ia_context["vision_version"] == "V1"
    assert result.ia_context["vision_approved"] is True
    assert result.ia_context["resolved_shop_id"] == "198996577"
    assert result.ia_context["resolved_item_id"] == "28131151896"
    assert result.ia_context["source_original_url"] == item.original_url
    assert api.calls[0] == ("get_exact_product", "198996577", "28131151896")


def test_armored_vision_unresolved_product_does_not_fabricate_affiliate_url(monkeypatch):
    monkeypatch.setattr(
        resolver,
        "resolve_short_url",
        lambda url: SimpleNamespace(
            original_url=url,
            resolved_url="https://shopee.com.br/opaanlp/198996577/28131151896",
            shop_id="198996577",
            item_id="28131151896",
        ),
    )
    api = FakeAPI(error=ShopeeProductNotFoundError("Produto não encontrado"))
    item = SimpleNamespace(original_url="https://s.shopee.com.br/1BEcv24py4")

    with pytest.raises(VisionUnresolvedError):
        ArmoredVision(api=api).identify(item)


def test_armored_vision_requires_original_url():
    api = FakeAPI()

    with pytest.raises(RuntimeError, match="original Shopee URL ausente"):
        ArmoredVision(api=api).identify(SimpleNamespace(original_url=""))


def test_armored_vision_does_not_call_generate_short_link_when_offer_exists(monkeypatch):
    monkeypatch.setattr(
        resolver,
        "resolve_short_url",
        lambda url: SimpleNamespace(
            original_url=url,
            resolved_url=url,
            shop_id="10",
            item_id="20",
        ),
    )
    api = FakeAPI()

    def forbidden(*args, **kwargs):
        raise AssertionError("generateShortLink não deve ser usado pelo V1")

    api.generate_short_link = forbidden
    item = SimpleNamespace(original_url="https://s.shopee.com.br/abc123")

    result = ArmoredVision(api=api).identify(item)

    assert result.affiliate_url == "https://s.shopee.com.br/affiliate-test"
