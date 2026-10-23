"""Single source of truth for product identity and version."""

APP_NAME = "MyAI Studio Ultimate"
APP_SHORT_NAME = "MyAI Studio"
APP_VENDOR = "MyAI Studio"
APP_TAGLINE_EN = "Design, build and run with intelligent agents"
APP_TAGLINE_FA = "طراحی، ساخت و اجرا با عامل‌های هوشمند"
APP_ID = "com.myaistudio.ultimate"

# Phase-by-phase release train.  Bumped at the end of every completed phase,
# and again for the capability round that followed Phase 5.
VERSION = "0.7.3"
PHASE = 6
BUILD_CHANNEL = "Round 3.1 - Windows release, final debug"

__all__ = [
    "APP_NAME",
    "APP_SHORT_NAME",
    "APP_VENDOR",
    "APP_TAGLINE_EN",
    "APP_TAGLINE_FA",
    "APP_ID",
    "VERSION",
    "PHASE",
    "BUILD_CHANNEL",
]
