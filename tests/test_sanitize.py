import os
from tvrenamer.sanitize import (
    normalize_unicode,
    sanitize_filename,
    sanitize_full_path,
)


def test_normalize_unicode():
    # "e" + combining acute vs composed
    s1 = "e\u0301"  # e + ´
    s2 = "\u00e9"  # é
    assert normalize_unicode(s1) == normalize_unicode(s2)


def test_illegal_characters_replaced():
    name = 'Show:Name?*"<>|\n'
    out = sanitize_filename(name, strict_windows=False)
    # illegal characters should be removed or replaced; result should not contain any illegal char
    assert not any(c in out for c in '<>:"/\\|?*')


def test_windows_reserved():
    # when strict_windows=True, reserved name should be avoided
    name = "CON"
    out = sanitize_filename(name, strict_windows=True)
    assert out.upper() != "CON"


def test_shorten_name():
    long = "a" * 300 + ".mkv"
    out = sanitize_filename(long, max_component=100)
    # basename should be <= max_component
    base = os.path.splitext(out)[0]
    assert len(base) <= 100


def test_sanitize_full_path_shortens():
    # Construct a long path with multiple long components
    comp1 = "a" * 80
    comp2 = "b" * 80
    comp3 = "c" * 120 + ".mkv"
    path = os.path.join(comp1, comp2, comp3)
    out = sanitize_full_path(path, max_path_len=100, strict_windows=True)
    assert len(out) <= 100


def test_sanitize_full_path_preserves_extension():
    comp1 = "dir"
    comp2 = "subdir"
    comp3 = "x" * 200 + ".srt"
    path = os.path.join(comp1, comp2, comp3)
    out = sanitize_full_path(path, max_path_len=120, strict_windows=True)
    assert out.endswith(".srt")
