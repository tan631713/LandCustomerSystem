"""Find existing owners that a manually typed new record probably belongs to.

Pure functions shared by the API server (which does the matching, so the
identity numbers and phones never leave it unmasked) and the tests.  Nothing
here touches the database or Qt.

Scores, highest first:

* 100 身分證相同（兩邊都是完整 10 碼且完全一樣）
*  80 姓名相同＋身分證前4碼與末碼相同（多數資料只存 5 碼，例如 H2211 =
      H221＋末碼 1；完整 10 碼取第 1-4 與第 10 碼，遮蔽格式 H221*****1 也取
      前 4 與末碼）
*  70 姓名相同＋電話相同
*  60 姓名相同＋地址相同（台/臺、全半形、三段/3段、之1/-1、樓/F、空白都不計）
*  50 姓名相同＋地址相似
*  20 只有姓名相同

Same name but two complete, different identity numbers is a different
person and is never offered.  A matching 5-character key under a different
name is not offered either: about 50 000 combinations collide too easily.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

HIGH_MATCH_SCORE = 50
DEFAULT_CANDIDATE_LIMIT = 10
ADDRESS_SIMILARITY_RATIO = 0.85
# Containment ("中壢區中正路3段10號" inside "桃園市中壢區中正路3段10號") only
# counts once the shorter address is long enough to mean something.
ADDRESS_CONTAINMENT_MIN_LENGTH = 8

SCORE_IDENTITY = 100
SCORE_IDENTITY_PARTIAL = 80
IDENTITY_KEY_LENGTH = 5
SCORE_PHONE = 70
SCORE_ADDRESS_SAME = 60
SCORE_ADDRESS_SIMILAR = 50
SCORE_NAME_ONLY = 20

_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "壹": 1, "二": 2, "貳": 2, "兩": 2,
    "三": 3, "參": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陸": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_CHINESE_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CHINESE_NUMBER_CHARS = "".join(_CHINESE_DIGITS) + "".join(_CHINESE_UNITS)
# Address parts whose number is often written either way (三段 / 3段).
_ADDRESS_NUMBER_SUFFIXES = "段巷弄號号樓楼鄰邻衖"
_ADDRESS_PUNCTUATION = re.compile(r"[\s,，、.。·・()（）\[\]【】「」'\"#＃:：;；/]+")
_FULL_IDENTITY = re.compile(r"[A-Z][0-9A-Z]\d{8}")


def _text(value):
    return str(value or "").strip()


def _nfkc(value):
    return unicodedata.normalize("NFKC", _text(value))


def chinese_number_to_int(text):
    """三 -> 3, 十二 -> 12, 二十 -> 20, 一百零五 -> 105; None when not a number."""

    text = _text(text)
    if not text or any(char not in _CHINESE_NUMBER_CHARS for char in text):
        return None
    if all(char in _CHINESE_DIGITS for char in text):
        # 一二三 written digit by digit.
        return int("".join(str(_CHINESE_DIGITS[char]) for char in text))
    total = 0
    current = 0
    for char in text:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        else:
            unit = _CHINESE_UNITS[char]
            total += (current or 1) * unit
            current = 0
    return total + current


def _replace_chinese_numbers(text):
    def before_suffix(match):
        number = chinese_number_to_int(match.group(1))
        # The leading space keeps "之1五樓" from becoming "之15樓"; spaces are
        # dropped at the end of normalize_owner_address().
        return match.group(0) if number is None else f" {number}{match.group(2)}"

    text = re.sub(
        f"([{_CHINESE_NUMBER_CHARS}]+)([{_ADDRESS_NUMBER_SUFFIXES}之])",
        before_suffix,
        text,
    )

    def after_zhi(match):
        number = chinese_number_to_int(match.group(1))
        return match.group(0) if number is None else f"之{number} "

    return re.sub(f"之([{_CHINESE_NUMBER_CHARS}]+)", after_zhi, text)


def normalize_owner_address(value):
    """One spelling for the ways the same address gets typed.

    台/臺, full/half width, 三段/3段, 之1/-1, 3F/3樓, spaces and punctuation
    all collapse; the result is only used for comparing, never stored.
    """

    text = _nfkc(value)
    if not text:
        return ""
    text = text.replace("臺", "台").replace("号", "號").replace("楼", "樓")
    text = text.replace("邻", "鄰")
    text = re.sub(r"[‐‑‒–—―−~～]", "-", text)
    # Punctuation becomes a space first so "12號之1 5F" cannot run together
    # into "之15"; the spaces go once the numbers are settled.
    text = _ADDRESS_PUNCTUATION.sub(" ", text).casefold()
    text = re.sub(r"\s*([段巷弄號樓鄰之-])\s*", r"\1", text)
    text = _replace_chinese_numbers(text)
    # Leading postal code: 330桃園市... / 33045桃園市...
    text = re.sub(r"^\s*\d{3,6}(?=\s*\D)", "", text)
    # 3f / 3樓 / 3層
    text = re.sub(r"(\d+)\s*(?:f|層)(?![a-z])", r"\1樓", text)
    # 12號之1 / 12之1號 / 12-1號 -> 12-1號
    text = re.sub(r"(\d+)號之(\d+)", r"\1-\2號", text)
    text = re.sub(r"(\d+)之(\d+)", r"\1-\2", text)
    # 3樓之2 -> 3樓-2
    text = re.sub(r"樓之(\d+)", r"樓-\1", text)
    text = re.sub(r"\s+", "", text)
    return text


def normalize_owner_name(value):
    text = _nfkc(value).replace("臺", "台")
    return "".join(text.split()).casefold()


def normalize_identity(value):
    text = _nfkc(value).upper()
    return re.sub(r"[\s\-]", "", text)


def normalize_phone(value):
    digits = re.sub(r"\D", "", _nfkc(value))
    if digits.startswith("886") and len(digits) >= 11:
        digits = "0" + digits[3:]
    return digits


def is_full_identity(value):
    return bool(_FULL_IDENTITY.fullmatch(normalize_identity(value)))


def mask_owner_identity(value):
    """Same light mask the desktop uses elsewhere: 前4碼＋星號＋末1碼."""

    text = _text(value)
    if len(text) <= 5:
        return text
    return text[:4] + ("*" * (len(text) - 5)) + text[-1]


def mask_phone(value):
    text = _text(value)
    digits = normalize_phone(text)
    if len(digits) < 6:
        return "*" * len(digits)
    return digits[:2] + "*" * (len(digits) - 5) + digits[-3:]


def addresses_similar(left, right):
    left = normalize_owner_address(left)
    right = normalize_owner_address(right)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= ADDRESS_CONTAINMENT_MIN_LENGTH and shorter in longer:
        return True
    return SequenceMatcher(None, left, right).ratio() >= ADDRESS_SIMILARITY_RATIO


def identity_match_key(value):
    """前4碼＋末碼, the part of an identity number the owner's data keeps.

    A complete 10-character number gives characters 1-4 and 10; a 5-character
    value (the usual stored form, e.g. H2211) is its own key; a masked form
    such as H221*****1 also gives its first four and last characters.  Any
    other length, or a ``*`` inside those five characters, gives None.
    """

    text = normalize_identity(value)
    if "*" not in text and len(text) not in (IDENTITY_KEY_LENGTH, 10):
        return None
    if len(text) < IDENTITY_KEY_LENGTH:
        return None
    key = text[:4] + text[-1]
    return None if "*" in key else key


def score_owner_candidate(query, owner):
    """(score, reasons) for one existing owner, or None when it is not a match.

    ``query`` and ``owner`` are plain dicts with owner_name, external_id,
    address and phone (owner: phones, a list).
    """

    typed_name = normalize_owner_name(query.get("owner_name"))
    owner_name = normalize_owner_name(owner.get("owner_name"))
    typed_id = normalize_identity(query.get("external_id"))
    stored_id = normalize_identity(owner.get("external_id"))
    same_name = bool(typed_name) and typed_name == owner_name

    if (
        is_full_identity(typed_id)
        and is_full_identity(stored_id)
        and typed_id == stored_id
    ):
        reasons = ["身分證相同"]
        if same_name:
            reasons.append("姓名相同")
        return SCORE_IDENTITY, reasons
    if not same_name:
        return None
    if (
        typed_id
        and stored_id
        and is_full_identity(typed_id)
        and is_full_identity(stored_id)
        and typed_id != stored_id
    ):
        # 同名不同人.
        return None

    score = SCORE_NAME_ONLY
    reasons = ["姓名相同"]
    typed_key = identity_match_key(typed_id)
    if typed_key is not None and typed_key == identity_match_key(stored_id):
        score = max(score, SCORE_IDENTITY_PARTIAL)
        reasons.append("身分證前4碼與末碼相同")

    typed_phone = normalize_phone(query.get("phone"))
    if len(typed_phone) >= 6:
        phones = {normalize_phone(phone) for phone in owner.get("phones") or ()}
        if typed_phone in phones:
            score = max(score, SCORE_PHONE)
            reasons.append("電話相同")

    typed_address = normalize_owner_address(query.get("address"))
    stored_address = normalize_owner_address(owner.get("address"))
    if typed_address and stored_address:
        if typed_address == stored_address:
            score = max(score, SCORE_ADDRESS_SAME)
            if _text(query.get("address")) == _text(owner.get("address")):
                reasons.append("地址相同")
            else:
                reasons.append("地址相同（寫法不同）")
        elif addresses_similar(typed_address, stored_address):
            score = max(score, SCORE_ADDRESS_SIMILAR)
            reasons.append("地址相似")
    return score, reasons


def rank_owner_candidates(
    query, owners, *, ignored_owner_ids=(), exact_owner_id=None,
    limit=DEFAULT_CANDIDATE_LIMIT,
):
    """Score every owner and return the matches, best first.

    ``exact_owner_id`` is the owner the record would already be saved under
    (same owner_key); it is flagged so the desktop can say so.  Owners in
    ``ignored_owner_ids`` were already rejected as "都不是" and are left out.
    """

    ignored = {int(value) for value in ignored_owner_ids}
    results = []
    for owner in owners:
        owner_id = int(owner["owner_id"])
        if owner_id in ignored and owner_id != exact_owner_id:
            continue
        scored = score_owner_candidate(query, owner)
        if scored is None:
            continue
        score, reasons = scored
        exact = exact_owner_id is not None and owner_id == int(exact_owner_id)
        results.append(
            {
                "owner_id": owner_id,
                "score": score,
                "reasons": reasons,
                "same_owner_key": exact,
                "owner": owner,
            }
        )
    results.sort(
        key=lambda item: (
            -item["score"],
            not item["same_owner_key"],
            -int(item["owner"].get("land_count") or 0),
            item["owner_id"],
        )
    )
    return results[: max(1, int(limit))]


def candidate_response_item(result):
    """What the API sends for one candidate: identity and phones masked."""

    owner = result["owner"]
    phones = [mask_phone(phone) for phone in owner.get("phones") or () if _text(phone)]
    return {
        "owner_id": result["owner_id"],
        "owner_name": _text(owner.get("owner_name")),
        "external_id_masked": mask_owner_identity(owner.get("external_id")),
        "has_external_id": bool(_text(owner.get("external_id"))),
        "address": _text(owner.get("address")),
        "phones_masked": list(dict.fromkeys(phones)),
        "land_count": int(owner.get("land_count") or 0),
        "sample_record_id": owner.get("sample_record_id"),
        "lands": list(owner.get("lands") or [])[:5],
        "score": result["score"],
        "reasons": list(result["reasons"]),
        "same_owner_key": bool(result["same_owner_key"]),
        "high_match": result["score"] >= HIGH_MATCH_SCORE,
    }


def identity_is_placeholder(submitted, real):
    """True when the form only carried the mask (or nothing) for ``real``."""

    submitted = _text(submitted)
    if not submitted:
        return True
    if "*" in submitted:
        return True
    return submitted == mask_owner_identity(real) and submitted != _text(real)
