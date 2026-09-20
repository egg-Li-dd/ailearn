"""validators 模块单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.validators import (
    validate_action, validate_color, validate_course_id, validate_date,
    validate_difficulty, validate_is_active, validate_mastery,
    validate_sort, validate_time, validate_weekday,
)


class TestValidateWeekday:
    def test_valid(self):
        assert validate_weekday(0) == (0, None)
        assert validate_weekday(6) == (6, None)
        assert validate_weekday("3") == (3, None)

    def test_out_of_range(self):
        _, err = validate_weekday(7)
        assert err is not None
        _, err = validate_weekday(-1)
        assert err is not None

    def test_non_numeric(self):
        _, err = validate_weekday("abc")
        assert err is not None


class TestValidateTime:
    def test_valid(self):
        assert validate_time("09:00") == ("09:00", None)
        assert validate_time("23:59") == ("23:59", None)

    def test_auto_pad(self):
        assert validate_time("9:00") == ("09:00", None)
        assert validate_time("9:5") == ("09:05", None)

    def test_invalid_hour(self):
        _, err = validate_time("25:00")
        assert err is not None

    def test_invalid_minute(self):
        _, err = validate_time("09:60")
        assert err is not None

    def test_invalid_format(self):
        _, err = validate_time("9点")
        assert err is not None


class TestValidateDate:
    def test_valid(self):
        assert validate_date("2026-08-23") == ("2026-08-23", None)

    def test_invalid_format(self):
        _, err = validate_date("2026/8/23")
        assert err is not None

    def test_invalid_date(self):
        _, err = validate_date("2026-02-30")
        assert err is not None


class TestValidateColor:
    def test_valid(self):
        assert validate_color("--subj-ds") == ("--subj-ds", None)

    def test_invalid(self):
        _, err = validate_color("--bad-color")
        assert err is not None


class TestValidateAction:
    def test_valid(self):
        assert validate_action("add") == ("add", None)
        assert validate_action("remove") == ("remove", None)

    def test_invalid(self):
        _, err = validate_action("delete")
        assert err is not None


class TestValidateSort:
    def test_valid(self):
        assert validate_sort(0) == (0, None)
        assert validate_sort("5") == (5, None)

    def test_negative(self):
        _, err = validate_sort(-1)
        assert err is not None


class TestValidateDifficulty:
    def test_valid(self):
        assert validate_difficulty(3) == (3, None)

    def test_clamp(self):
        assert validate_difficulty(10) == (5, None)
        assert validate_difficulty(0) == (1, None)


class TestValidateMastery:
    def test_valid(self):
        assert validate_mastery(50) == (50, None)

    def test_clamp(self):
        assert validate_mastery(150) == (100, None)
        assert validate_mastery(-10) == (0, None)


class TestValidateCourseId:
    def test_valid(self):
        valid = {1, 2, 3}
        assert validate_course_id(1, valid) == (1, None)

    def test_invalid_id(self):
        valid = {1, 2, 3}
        _, err = validate_course_id(99, valid)
        assert err is not None


class TestValidateIsActive:
    def test_bool(self):
        assert validate_is_active(True) == (True, None)
        assert validate_is_active(False) == (False, None)

    def test_string(self):
        assert validate_is_active("true") == (True, None)
        assert validate_is_active("false") == (False, None)
