"""端到端测试：模拟 DB 模式下 price_check 的完整调用链"""
import sys
import os
import logging

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
_log = logging.getLogger("e2e_test")

# 全部应命中（DB 直连模式，数据完整）
TEST_CASES = [
    ("y500i 凤迎金 12+256", ["y500i", "凤迎金", "12+256"]),
    ("z10x 月岩钛 12+256", ["z10x", "月岩钛", "12+256g"]),
    ("z11x 夜影黑 12+256", ["z11x", "夜影黑", "12+256g"]),
    ("z11 天光白 16+512", ["z11", "天光白", "16+512g"]),
    ("z10turbo 云海白 12+256", ["z10", "turbo+", "云海白", "12+256g"]),
    ("z10turbo+ 云海白 16+512", ["z10", "turbo+", "云海白", "16+512g"]),
    ("neo9 格斗黑 12+256", ["neo9", "格斗黑", "12+256g"]),
    ("A3i 星辰紫 6+128", ["a3i", "星辰紫", "6+128"]),
    ("A3i 静夜黑 6+128", ["a3i", "静夜黑", "6+128"]),
    ("A3i 静夜黑 8+128", ["a3i", "静夜黑", "8+128"]),
    ("A5活力版 玛瑙粉 8+256", ["a5", "活力版", "玛瑙粉", "8+256"]),
    ("A5活力版 玛瑙粉 12+256", ["a5", "活力版", "玛瑙粉", "12+256"]),
    ("A6 丝绒灰 12+256", ["a6", "丝绒灰", "12+256"]),
    ("note14 幻影青 8+128", ["note14", "幻影青", "8+128"]),
    ("note14pro+ 子夜黑 12+256", ["note14pro+", "子夜黑", "12+256"]),
    ("turbo4 祥云白 16+256", ["turbo4", "祥云白", "16+256g"]),
    # 单数字容量（LLM 拆分出 "256"/"128"，不带运行内存）
    ("畅享90plus 星海蓝 256", ["畅享", "90", "plus", "星海蓝", "256"]),
    ("畅享70x 雪域白 128", ["畅享", "70x", "雪域白", "128"]),
]


def main():
    from backend.database import SessionLocal
    from backend import price_service

    db = SessionLocal()
    try:
        from backend.models import Tenant
        tenant = db.query(Tenant).filter(Tenant.code == '00000').first()
        if not tenant:
            _log.error("tenant '00000' not found!")
            return

        from backend.main import _ensure_tenant_config
        cfg = _ensure_tenant_config(db, tenant.id)
        _field_name = cfg.feishu_field_name or "商品名称"
        _price_field_name = cfg.feishu_price_field_name or "报价"
        _log.info(f"source_mode={tenant.source_mode}, field_name={_field_name}, price_field_name={_price_field_name}")

        cache_rows, sync_status, sync_count, _ = price_service.get_rows_from_cache(
            db, tenant.code, False, False  # 不触发强制刷新，用缓存
        )
        _log.info(f"loaded {len(cache_rows)} rows")

    finally:
        db.close()

    from backend.feishu_api import match_keywords_in_rows_batch

    formatted = [{
        _field_name: r.get("product_name", ""),
        _price_field_name: r.get("price", ""),
        "extra_json": r.get("extra_json", "{}") or "{}",
    } for r in cache_rows]

    all_kws = [tc[1] for tc in TEST_CASES]
    results = match_keywords_in_rows_batch(formatted, _field_name, _price_field_name, all_kws)

    print("\n" + "=" * 80)
    print("MATCH RESULTS (DB 直连模式):")
    print("=" * 80)
    ok = 0
    no_match = 0
    for idx, (tc, result) in enumerate(zip(TEST_CASES, results)):
        input_text = tc[0]
        keywords = tc[1]
        price, matched_name = result

        if price:
            ok += 1
            print(f"\nCase {idx+1}: ✓ MATCHED  price={price}")
            print(f"  Input:     {input_text}")
            print(f"  Keywords:  {keywords}")
            print(f"  Matched:   {matched_name}")
        else:
            no_match += 1
            print(f"\nCase {idx+1}: ✗ NO MATCH")
            print(f"  Input:     {input_text}")
            print(f"  Keywords:  {keywords}")

    print(f"\n{'='*80}")
    print(f"结果: {ok}/{len(TEST_CASES)} 命中, {no_match} 未命中")
    if no_match == 0:
        print("✓ 全部通过!")
    else:
        print("✗ 存在未命中!")


if __name__ == "__main__":
    main()
