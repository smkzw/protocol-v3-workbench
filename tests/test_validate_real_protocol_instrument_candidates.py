from scripts.validate_real_protocol_instrument_candidates import (
    _instrument_token_matches,
)


def test_instrument_token_matching_supports_promis_chinese_alias() -> None:
    searchable = "患者报告结局测量信息系统简表-睡眠相关影响（8a-24小时回忆）"

    assert _instrument_token_matches(searchable, "PROMIS-睡眠相关影响")
    assert not _instrument_token_matches(searchable, "PROMIS-睡眠困扰")


def test_instrument_token_matching_does_not_treat_separate_candidates_as_merged() -> None:
    assert not _instrument_token_matches("DLQI 皮肤病学生活质量指数", "DLQI / CDLQI")
    assert not _instrument_token_matches("CDLQI 儿童皮肤病生活质量指数", "DLQI / CDLQI")
    assert _instrument_token_matches("DLQI / CDLQI 皮肤病学生活质量指数", "DLQI / CDLQI")
