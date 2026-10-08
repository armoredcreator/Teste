from __future__ import annotations

from .contracts import VisionResult, VisionUnresolvedError
from .modules.v1.shopee_api import ShopeeAffiliateAPI, ShopeeProductNotFoundError
from .modules.v1.shopee_resolver import resolve_short_url


class ArmoredVision:
    """Native Vision V1 for the definitive ArmoredCreator project.

    The implementation preserves the proven V1 behavior while removing any
    runtime dependency on the frozen armoredcreator-test repository.
    """

    def __init__(self, api=None):
        self.api = api

    @staticmethod
    def _ia_context(product: dict) -> dict:
        keys = (
            "productName", "itemId", "shopId", "shopName", "productCatIds",
            "priceMin", "priceMax", "sales", "ratingStar", "brand",
            "brandName", "model", "modelName", "description", "attributes",
            "technicalCharacteristics", "imageUrl",
        )
        return {
            key: product[key]
            for key in keys
            if key in product and product[key] not in (None, "", [], {})
        }

    def identify(self, item) -> VisionResult:
        original = (getattr(item, "original_url", None) or "").strip()
        if not original:
            raise RuntimeError("Vision: original Shopee URL ausente")

        resolved = resolve_short_url(original)
        api = self.api or ShopeeAffiliateAPI()
        try:
            product = api.get_exact_product(resolved.shop_id, resolved.item_id)
        except ShopeeProductNotFoundError as exc:
            raise VisionUnresolvedError(
                f"Vision V1 não resolveu o produto Shopee "
                f"{resolved.shop_id}:{resolved.item_id}; "
                "item preservado para futura recuperação"
            ) from exc

        affiliate_url = str(api.affiliate_link_for_product(product)).strip()
        identifier = str(
            product.get("productName")
            or product.get("itemId")
            or f"{resolved.shop_id}_{resolved.item_id}"
        )

        ia_context = self._ia_context(product)
        ia_context.update(
            {
                "vision_version": "V1",
                "vision_approved": True,
                "source_original_url": original,
                "resolved_shop_id": resolved.shop_id,
                "resolved_item_id": resolved.item_id,
                "affiliate_url": affiliate_url,
            }
        )

        return VisionResult(
            identifier,
            affiliate_url,
            affiliate_urls=(affiliate_url,),
            publication_caption=None,
            ia_context=ia_context,
        )


def build(**_kwargs):
    return ArmoredVision()
