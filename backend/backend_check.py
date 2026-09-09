"""Validate all 6 Ingredient Discovery Engine gaps."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

# ── Gap 1+2: image_classifier ──────────────────────────────────────────────────
from url_scanner.image_classifier import (
    _INGREDIENTS_OCR_SIGNAL, _NUTRITION_ONLY_SIGNAL,
    _score_ocr_signals, IMAGE_TYPES, CATEGORIES,
    _FIELD_TO_PREFERRED_TYPES, _OCR_SIGNAL_TO_FIELD,
    rank_for_missing_fields,
)

print("=== Gap 1+2: image_classifier ===")

# 1a. INGREDIENT_PANEL in IMAGE_TYPES
assert "INGREDIENT_PANEL" in IMAGE_TYPES, "FAIL: INGREDIENT_PANEL not in IMAGE_TYPES"
assert IMAGE_TYPES["INGREDIENT_PANEL"]["lm_relevance"] == 90
print("  INGREDIENT_PANEL in IMAGE_TYPES (lm=90) OK")

# 1b. ingredient_panel in CATEGORIES
assert "ingredient_panel" in CATEGORIES
assert "ingredient" in CATEGORIES["ingredient_panel"]
assert "composition" in CATEGORIES["ingredient_panel"]
print("  ingredient_panel in CATEGORIES OK")

# 1c. _INGREDIENTS_OCR_SIGNAL matches variants
tests = [
    "INGREDIENTS: Rolled Oats (25%), Wheat Flakes",
    "INGREDIANTS: Sugar, Salt",         # misspelling
    "INGREDlENTS: Oats",                # OCR l vs I
    "INGRED1ENTS: Oats",                # OCR 1 vs I
    "COMPOSITION: Wheat Flour, Salt",
    "MADE FROM: Natural Ingredients",
    "PREPARED FROM: Oats, Ragi",
]
for t in tests:
    assert _INGREDIENTS_OCR_SIGNAL.search(t), f"FAIL: signal missed '{t}'"
print("  _INGREDIENTS_OCR_SIGNAL matches all 7 variants OK")

# 1d. _NUTRITION_ONLY_SIGNAL does NOT fire on ingredient text
nutrition_text = "NUTRITION FACTS: Calories 200, Total Fat 5g"
ing_text = "INGREDIENTS: Rolled Oats (25%)"
assert _NUTRITION_ONLY_SIGNAL.search(nutrition_text), "FAIL: nutrition not detected"
assert not _NUTRITION_ONLY_SIGNAL.search(ing_text), "FAIL: ingredient text misclassified as nutrition"
print("  _NUTRITION_ONLY_SIGNAL correctly distinguishes nutrition vs ingredient OK")

# 1e. _score_ocr_signals returns has_ingredients=True with +45 boost
score, reason, signals = _score_ocr_signals("INGREDIENTS: Rolled Oats, Wheat\nMfg by: Test Ltd\n")
assert signals["has_ingredients"] is True, "FAIL: has_ingredients not True"
assert signals["has_manufacturer"] is True
assert "45" in reason, f"FAIL: +45 boost not in reason: {reason}"
print(f"  _score_ocr_signals: has_ingredients=True, boost includes +45 OK")
print(f"    reason: {reason}")

# 1f. has_ingredients in _OCR_SIGNAL_TO_FIELD
assert "has_ingredients" in _OCR_SIGNAL_TO_FIELD
assert _OCR_SIGNAL_TO_FIELD["has_ingredients"] == "ingredients"
print("  has_ingredients in _OCR_SIGNAL_TO_FIELD OK")

# 1g. ingredients routing prefers ingredient_panel first
assert _FIELD_TO_PREFERRED_TYPES["ingredients"][0] == "ingredient_panel"
print("  ingredients routes to ingredient_panel first OK")

# 1h. rank_for_missing_fields elevates ingredient_panel candidate
candidates = [
    {"url": "http://a.com/front.jpg", "compliance_score": 90,
     "classification": {"category": "front_package"},
     "ocr_signals": {"has_net_qty": True}},
    {"url": "http://a.com/back.jpg", "compliance_score": 70,
     "classification": {"category": "back_package"},
     "ocr_signals": {"has_manufacturer": True}},
    {"url": "http://a.com/ingr.jpg", "compliance_score": 60,
     "classification": {"category": "ingredient_panel"},
     "ocr_signals": {"has_ingredients": True}},
]
ranked = rank_for_missing_fields(candidates, ["ingredients"])
assert ranked[0]["url"] == "http://a.com/ingr.jpg", \
    f"FAIL: ingredient_panel not ranked #1, got {ranked[0]['url']}"
print("  rank_for_missing_fields: ingredient_panel ranked #1 when seeking ingredients OK")

# ── Gap 3: entity_extractor ────────────────────────────────────────────────────
print("\n=== Gap 4+5: entity_extractor ===")
from url_scanner.intelligence.entity_extractor import (
    extract_entities, _check_ingredient_completeness,
    _INGREDIENTS_PATTERNS,
)

# Gap 4a: COMPOSITION pattern
result = extract_entities("COMPOSITION: Rolled Oats (25%), Wheat Flakes (20%), Sugar.")
assert result.get("ingredients"), f"FAIL: COMPOSITION not detected: {result}"
print(f"  COMPOSITION pattern: '{result['ingredients'][:50]}' OK")

# Gap 4b: MADE FROM pattern
result2 = extract_entities("MADE FROM: Oats, Wheat, Ragi, Jowar, Almonds.")
assert result2.get("ingredients"), "FAIL: MADE FROM not detected"
print(f"  MADE FROM pattern: '{result2['ingredients'][:50]}' OK")

# Gap 4c: Standard INGREDIENTS
result3 = extract_entities("INGREDIENTS: Rolled Oats (25%), Wheat Flakes (20%).")
assert result3.get("ingredients"), "FAIL: INGREDIENTS not detected"
print(f"  Standard INGREDIENTS: '{result3['ingredients'][:50]}' OK")

# Gap 5a: completeness — complete list
assert _check_ingredient_completeness("Rolled Oats, Wheat, Sugar.") is True
print("  Completeness: list ending with '.' returns True OK")

# Gap 5b: completeness — truncated (ends with comma)
assert _check_ingredient_completeness("Rolled Oats, Wheat, Sugar,") is False
print("  Completeness: list ending with ',' returns False OK")

# Gap 5c: completeness — truncated (ends with 'and')
assert _check_ingredient_completeness("Rolled Oats and") is False
print("  Completeness: list ending with 'and' returns False OK")

# Gap 5d: ingredient_complete in extracted entities
assert "ingredient_complete" in result3, "FAIL: ingredient_complete not in entities"
print(f"  ingredient_complete in extract_entities output OK (value={result3['ingredient_complete']})")

# ── Gap 6: formatter ────────────────────────────────────────────────────────────
print("\n=== Gap 6: formatter ===")
from url_scanner.formatter import format_product
model_with_ingredients = {
    "product": {"name": "Test Oats", "brand": "TestBrand"},
    "commerce": {"mrp_raw": "Rs 215"},
    "manufacturer": {"name": "Test Mfr Ltd"},
    "packer": {}, "importer": {}, "origin": {},
    "quantity": {}, "dates": {}, "consumer_care": {},
    "regulatory": {"fssai": "12345678901234"},
    "ingredients": "Rolled Oats (25%), Wheat Flakes (20%), Sugar, Salt.",
    "ingredient_complete": True,
    "allergen_info": "",
    "storage_instructions": "",
    "ocr_stats": {"images_downloaded": 3, "ocr_char_count": 800, "avg_confidence": 0.88, "image_results": []},
}
out = format_product(model_with_ingredients, {"display_name": "Amazon"}, [], [])
assert "INGREDIENTS" in out, "FAIL: INGREDIENTS section missing"
assert "Completeness: COMPLETE" in out, f"FAIL: completeness not shown. out={out[out.find('INGREDIENT'):][:200]}"
print("  Formatter shows INGREDIENTS + Completeness: COMPLETE OK")

# Test truncated case
model_truncated = dict(model_with_ingredients)
model_truncated["ingredients"] = "Rolled Oats, Wheat,"
model_truncated["ingredient_complete"] = False
out2 = format_product(model_truncated, {"display_name": "Amazon"}, [], [])
assert "POSSIBLE TRUNCATION" in out2, "FAIL: truncation warning not shown"
print("  Formatter shows POSSIBLE TRUNCATION warning OK")

# Test not detected case
model_none = dict(model_with_ingredients)
model_none["ingredients"] = ""
model_none["ingredient_complete"] = None
out3 = format_product(model_none, {"display_name": "Amazon"}, [], [])
assert "Not Detected" in out3, "FAIL: 'Not Detected' not shown when no ingredients"
print("  Formatter shows 'Not Detected' when ingredients empty OK")

print("\n========================================")
print("All 6 Ingredient Discovery Engine gaps PASSED!")
print("========================================")
