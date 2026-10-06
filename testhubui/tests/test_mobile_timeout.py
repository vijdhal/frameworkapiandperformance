"""
Tests for the iOS timeout floor in the Mobilewright engine.

Why this file exists
--------------------
`_timeout_ms` silently rewrites a value the user typed into the Studio. That is
exactly the kind of behaviour that decays: someone later "simplifies" the floor
away, Android and iOS get one shared default again, and the symptom is not a
crash — it is every client's FIRST iOS run failing with

    Test timeout of 30000ms exceeded while setting up "device"

which reads like a broken test rather than a budget that was too small. The
whole point of the floor is that a first run must not look like a failure, so
the floor needs a test that fails loudly when it is removed.

Measured basis for the number: see IOS_TIMEOUT_FLOOR_MS in the engine.

Run:  testhubui/.venv/bin/python -m pytest testhubui/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

from engines.mobile_mobilewright import MobileWrightEngine as E  # noqa: E402


def test_ios_default_is_raised_to_the_floor():
    """The 30s default is an Android number; on iOS it must be lifted."""
    assert E._timeout_ms('30000', 'ios') == str(E.IOS_TIMEOUT_FLOOR_MS)


def test_android_default_is_left_alone():
    """Android gains nothing from a 180s budget except slow feedback on a
    genuinely wrong locator, so the floor must not leak across platforms."""
    assert E._timeout_ms('30000', 'android') == '30000'


def test_floor_raises_but_never_caps():
    """A user asking for MORE than the floor keeps what they asked for —
    this is a floor, not a clamp."""
    assert E._timeout_ms('300000', 'ios') == '300000'


def test_garbage_input_still_lands_on_the_floor():
    """Non-numeric input falls back to the default, which iOS then floors.
    It must not fall through to 30000 and reintroduce the failure."""
    assert E._timeout_ms('abc', 'ios') == str(E.IOS_TIMEOUT_FLOOR_MS)
    assert E._timeout_ms(None, 'ios') == str(E.IOS_TIMEOUT_FLOOR_MS)


@pytest.mark.parametrize('platform', ['iOS', 'IOS', 'Ios'])
def test_platform_match_is_case_insensitive(platform):
    """render() lowercases before calling this, so the floor currently works by
    luck of the caller. Assert it directly so a future caller cannot silently
    lose the floor and reintroduce the first-run failure."""
    assert E._timeout_ms('30000', platform) == str(E.IOS_TIMEOUT_FLOOR_MS)


def test_real_device_name_with_a_slash_cannot_break_the_regex_literal():
    """Device names come back from `mobilecli devices` as whatever the owner
    typed in iOS Settings. An unescaped `/` closes the `/.../` literal early
    and emits TypeScript that does not parse."""
    from engines.mobile_mobilewright import _device_regex
    assert _device_regex('Vuyani/Work iPhone') == r'Vuyani\/Work iPhone'


def test_intentional_regex_syntax_is_preserved():
    """The field is documented as a regex, so metacharacters must survive —
    escaping them would break the case the feature exists for."""
    from engines.mobile_mobilewright import _device_regex
    assert _device_regex('iPhone (14|16)') == 'iPhone (14|16)'


def test_invalid_regex_is_rejected_with_a_useful_message():
    """An unbalanced group must fail here, naming the field — not later as a
    syntax error inside a generated file the user never wrote."""
    from engines.mobile_mobilewright import _device_regex
    with pytest.raises(ValueError, match='not a valid regex'):
        _device_regex('iPhone (14')


def test_emitted_config_carries_the_floor():
    """End to end through render(): the number must actually reach the file
    the runner executes, not just the helper."""
    cfg = {
        'assetName': 'contacts', 'serviceName': 'launch', 'platform': 'ios',
        'bundleId': 'com.apple.MobileAddressBook', 'deviceName': 'iPhone',
        'expectText': 'Contacts', 'positive': True, 'negative': False,
        'steps': [{'action': 'waitFor', 'locator': 'Contacts'}],
        'paths': {'mobile': 'mobile'},
    }
    engine = E()
    assets = engine.render(cfg, engine.build_matrix(cfg))
    config = next(body for path, body in assets.files.items()
                  if str(path).endswith('mobilewright.config.ts'))
    assert f'timeout: {E.IOS_TIMEOUT_FLOOR_MS},' in config
