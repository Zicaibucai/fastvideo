"""全量数字证据和面积语义分类测试。"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.facts import _fact_view
from app.services.fact_extractor import (
    _extract_from_page,
    _is_identifier_label,
    _is_low_priority_label,
    _normalize_ai_category,
    detect_conflicts,
)


def test_area_context_is_preserved_and_semantically_separated():
    text = "本项目占地面积11787㎡，地上建筑面积41891.5㎡，地下建筑面积 21008.0㎡，总建筑面积 62899.5㎡。"
    rows = _extract_from_page(text)
    by_name = {row["fact_name"]: row for row in rows}

    assert by_name["area_land"]["fact_value"] == "11787"
    assert by_name["area_building_above"]["fact_value"] == "41891.5"
    assert by_name["area_building_below"]["fact_value"] == "21008.0"
    assert by_name["area_building"]["fact_value"] == "62899.5"
    for row in by_name.values():
        assert row["source_quote"] == text


def test_numeric_scan_keeps_materials_and_dimensions():
    text = "地下室混凝土强度等级C35~C50、抗渗等级为P8，底板厚度达到1000mm。"
    rows = _extract_from_page(text)
    values = {(row["fact_value"], row["unit"], row["metadata_json"]["display_name"]) for row in rows}

    assert ("C35~C50", None, "强度等级") in values
    assert ("P8", None, "抗渗等级") in values
    assert ("1000", "mm", "厚度") in values


def test_nearby_label_does_not_cross_another_number():
    text = "图中红色钢柱为塔吊STT603起吊半径35m，额定吊重16.56吨范围内最不利的工况，此时最重分段为地上一节钢柱，重量为15.83吨，满足要求；"
    rows = _extract_from_page(text)
    values = {(row["fact_value"], row["unit"], row["metadata_json"]["display_name"]) for row in rows}

    assert ("35", "m", "半径") in values
    assert ("16.56", "吨", "额定吊重") in values
    assert ("15.83", "吨", "重量") in values


def test_numeric_category_is_checked_against_name_and_unit():
    # AI 即使把类别写错，台账也不能让“半径+吨位”落到同一个类别。
    assert _normalize_ai_category("起吊半径", "m", "工程范围/场地") == "尺寸/标高/深度"
    assert _normalize_ai_category("额定吊重", "吨", "工程参数") == "面积/工程量"


def test_identifier_labels_are_not_treated_as_engineering_facts():
    assert _is_identifier_label("文件编号")
    assert _is_identifier_label("条款号")
    assert _is_identifier_label("序号")
    assert not _is_identifier_label("型号")
    assert not _is_identifier_label("材料/型号")


def test_non_engineering_labels_are_low_priority():
    assert _is_low_priority_label("人员年龄")
    assert _is_low_priority_label("软件版本")
    assert _is_low_priority_label("门牌号")
    assert not _is_low_priority_label("梁高")
    assert not _is_low_priority_label("混凝土强度等级")


def test_numeric_candidates_do_not_create_false_conflicts():
    rows = [
        SimpleNamespace(id="a", fact_type="numeric_candidate", fact_name="numeric_candidate", fact_value="100", verification_status="unverified"),
        SimpleNamespace(id="b", fact_type="numeric_candidate", fact_name="numeric_candidate", fact_value="200", verification_status="unverified"),
    ]
    assert detect_conflicts(rows) == []


def test_scoped_parameters_do_not_conflict_across_building_parts():
    rows = [
        SimpleNamespace(
            id="tower",
            fact_type="height_building",
            fact_name="height_building",
            fact_value="69.95",
            verification_status="unverified",
            metadata_json={"scope": "塔楼"},
        ),
        SimpleNamespace(
            id="podium",
            fact_type="height_building",
            fact_name="height_building",
            fact_value="23.95",
            verification_status="unverified",
            metadata_json={"scope": "裙房"},
        ),
    ]
    assert detect_conflicts(rows) == []


def test_usage_bands_only_review_middle_confidence_range():
    def fact(confidence: float, auto_usable: bool = False):
        return SimpleNamespace(
            fact_name="numeric_candidate",
            fact_value="1",
            confidence=confidence,
            verification_status="unverified",
            metadata_json={"display_name": "参数", "auto_usable": auto_usable},
        )

    assert _fact_view(fact(0.59))[3] == "low_confidence"
    assert _fact_view(fact(0.60))[3] == "review"
    assert _fact_view(fact(0.80))[3] == "auto_usable"
    assert _fact_view(fact(0.80, auto_usable=True))[3] == "auto_usable"
