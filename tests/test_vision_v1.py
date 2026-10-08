from types import SimpleNamespace

import pytest

from src.vision import ArmoredVision, VisionUnresolvedError
from src.vision.modules.v1 import shopee_resolver


class FakeAPI:
    def __init__(self, product):
        self.product = product
        self.calls = []

    def get_exact_product(self, shop_id, item_id):
        self.calls.append((shop_id, item_id))
        return self.product

    def affiliate_link_for_product(self, product):
        return product["offerLink"]


def test_direct_shopee_url_is_resolved_without_http():
    resolved = shopee_resolver.resolve_short_url(
        "https://shopee.com.br/product/123/456"
    )
    assert resolved.shop_id == "123"
    assert resolved.item_id == "456"
    assert resolved.resolved_url == resolved.original_url


def test_vision_v1_returns_affiliate_and_ia_context(monkeypatch):
    product = {
        "itemId": 456,
        "shopId": 123,
        "productName": "Produto Teste",
        "shopName": "Loja Teste",
        "offerLink": "https://shope.ee/affiliate",
        "sales": 99,
        "imageUrl": "https://example.com/image.jpg",
    }
    api = FakeAPI(product)
    monkeypatch.setattr(
        "src.vision.service.resolve_short_url",
        lambda url: SimpleNamespace(shop_id="123", item_id="456"),
    )

    item = SimpleNamespace(original_url="https://shope.ee/example")
    result = ArmoredVision(api=api).identify(item)

    assert result.affiliate_name == "Produto Teste"
    assert result.affiliate_url == "https://shope.ee/affiliate"
    assert result.affiliate_urls == ("https://shope.ee/affiliate",)
    assert result.ia_context["productName"] == "Produto Teste"
    assert result.ia_context["vision_version"] == "V1"
    assert result.ia_context["vision_approved"] is True
    assert result.ia_context["source_original_url"] == "https://shope.ee/example"
    assert result.ia_context["resolved_shop_id"] == "123"
    assert result.ia_context["resolved_item_id"] == "456"
    assert result.ia_context["affiliate_url"] == "https://shope.ee/affiliate"
    assert api.calls == [("123", "456")]


def test_vision_v1_unresolved_product_is_waiting_vision_error(monkeypatch):
    class MissingAPI(FakeAPI):
        def get_exact_product(self, shop_id, item_id):
            from src.vision.modules.v1.shopee_api import ShopeeProductNotFoundError
            raise ShopeeProductNotFoundError("missing")

    monkeypatch.setattr(
        "src.vision.service.resolve_short_url",
        lambda url: SimpleNamespace(shop_id="123", item_id="456"),
    )

    with pytest.raises(VisionUnresolvedError):
        ArmoredVision(api=MissingAPI({})).identify(
            SimpleNamespace(original_url="https://shope.ee/example")
        )
