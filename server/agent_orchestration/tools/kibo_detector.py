"""
Kibo Animation Keyword Detector
================================

Scans text for keywords that map to Kibo character states and emotes.
Supports present tense, past tense, and common verb forms.

Animation States: Idle, Walking, Running, Dance, Death, Sitting, Standing
Emotes:           Jump, Yes, No, Wave, Punch, ThumbsUp
"""

import re
from typing import Optional

# ── Keyword → Animation mapping ──────────────────────────────

# Each entry: { set of trigger words } → animation name
# Includes present tense, past tense, gerund, and common variations

STATE_KEYWORDS: dict[str, list[str]] = {
    "Idle": [
        "idle", "idling", "idled", "rest", "resting", "rested",
        "still", "calm", "relax", "relaxing", "relaxed",
    ],
    "Walking": [
        "walk", "walking", "walked", "walks",
        "stroll", "strolling", "strolled",
    ],
    "Running": [
        "run", "running", "ran", "runs",
        "sprint", "sprinting", "sprinted",
        "rush", "rushing", "rushed",
    ],
    "Dance": [
        "dance", "dancing", "danced", "dances",
        "groove", "grooving", "grooved",
    ],
    "Death": [
        "die", "dying", "died", "dies", "death", "dead",
        "kill", "killing", "killed",
        "defeat", "defeating", "defeated",
    ],
    "Sitting": [
        "sit", "sitting", "sat", "sits",
        "seat", "seating", "seated",
    ],
    "Standing": [
        "stand", "standing", "stood", "stands",
        "rise", "rising", "rose", "risen",
        "get up", "getting up", "got up",
    ],
}

EMOTE_KEYWORDS: dict[str, list[str]] = {
    "Jump": [
        "jump", "jumping", "jumped", "jumps",
        "leap", "leaping", "leaped", "leapt",
        "hop", "hopping", "hopped",
    ],
    "Yes": [
        "yes", "yeah", "yep", "nod", "nodding", "nodded",
        "agree", "agreeing", "agreed",
        "correct", "right", "affirmative",
    ],
    "No": [
        "no", "nope", "nah",
        "shake", "shaking", "shook",
        "disagree", "disagreeing", "disagreed",
        "wrong", "incorrect", "deny", "denied",
    ],
    "Wave": [
        "wave", "waving", "waved", "waves",
        "hello", "hi", "hey", "greet", "greeting", "greeted",
        "bye", "goodbye", "farewell",
    ],
    "Punch": [
        "punch", "punching", "punched", "punches",
        "hit", "hitting", "smack", "smacking", "smacked",
        "fight", "fighting", "fought",
        "attack", "attacking", "attacked",
    ],
    "ThumbsUp": [
        "thumbs up", "thumbsup", "thumb up",
        "good job", "well done", "nice", "great",
        "awesome", "excellent", "bravo",
        "approve", "approving", "approved",
    ],
}

# Pre-compile patterns for performance
_state_patterns: dict[str, re.Pattern[str]] = {}
_emote_patterns: dict[str, re.Pattern[str]] = {}


def _build_pattern(keywords: list[str]) -> re.Pattern[str]:
    """Build a word-boundary regex from a list of keywords."""
    escaped = [re.escape(kw) for kw in sorted(keywords, key=len, reverse=True)]
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


def _ensure_compiled() -> None:
    """Lazy-compile all patterns on first use."""
    if _state_patterns:
        return
    for name, kws in STATE_KEYWORDS.items():
        _state_patterns[name] = _build_pattern(kws)
    for name, kws in EMOTE_KEYWORDS.items():
        _emote_patterns[name] = _build_pattern(kws)


def detect_state(text: str) -> Optional[str]:
    """Return the first matching character state name, or None."""
    _ensure_compiled()
    for name, pattern in _state_patterns.items():
        if pattern.search(text):
            return name
    return None


def detect_emote(text: str) -> Optional[str]:
    """Return the first matching emote name, or None."""
    _ensure_compiled()
    for name, pattern in _emote_patterns.items():
        if pattern.search(text):
            return name
    return None


def detect_animation(text: str) -> Optional[dict]:
    """
    Scan text for animation keywords.

    Returns a KiboCommand dict if a keyword is found:
      {"type": "playEmote", "emote": "Wave"}
      {"type": "setState", "state": "Walking"}
    or None if nothing matched.

    Emotes take priority over states (they're more specific actions).
    """
    emote = detect_emote(text)
    if emote:
        return {"type": "playEmote", "emote": emote}

    state = detect_state(text)
    if state:
        return {"type": "setState", "state": state}

    return None
