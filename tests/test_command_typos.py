"""Typo fallback changes a known misspelled command word only."""
import pytest

from services.automation.command_typos import correct_command_typo


@pytest.mark.parametrize("typo,word", [
    ("opne", "open"), ("launhc", "launch"), ("serach", "search"), ("seach", "search"),
    ("remnid", "remind"), ("remidn", "remind"), ("voluem", "volume"),
    ("brighness", "brightness"), ("brightnes", "brightness"),
    ("screenshto", "screenshot"), ("screnshot", "screenshot"), ("shwo", "show"),
    ("paus", "pause"), ("resuem", "resume"),
])
def test_only_registered_command_word_is_corrected(typo, word):
    assert correct_command_typo(f"{typo} Target Name 2!") == f"{word} Target Name 2!"


@pytest.mark.parametrize("text,expected", [
    ("OPNE Spotify", "open Spotify"),
    ("serach for Twenty One Pilots and Version 2", "search for Twenty One Pilots and Version 2"),
    ("remnid me in five minutes to Type opne and serach Exactly!", "remind me in five minutes to Type opne and serach Exactly!"),
    ('shwo "My Case-Sensitive File.txt"', 'show "My Case-Sensitive File.txt"'),
    ("screenshto", "screenshot"),
    ("opne\tMy App", "open\tMy App"),
])
def test_payload_and_spacing_are_preserved(text, expected):
    assert correct_command_typo(text) == expected


@pytest.mark.parametrize("text", [
    "", "open Chrome", "open Spotfiy", "launch Chrome", "search for opne", "type opne Spotify",
    "note: shwo my files", "message Mom: resuem Spotify", "don't opne Chrome", "never shwo passwords",
    "do not remnid me", "not opne Chrome", "can you opne Chrome", "please opne Chrome",
    '"opne Chrome"', "'serach for songs'", "lunch Chrome", "shop my files", "rescue Spotify",
    "shutdwon", "restatr", "deelte all files", "rmvoe reminder 2", "clsoe Chrome", "foramt disk",
    "opne.exe", "opne: Chrome", "opneChrome", "serach-engine", "opne's settings", "shwo?",
])
def test_unknown_words_content_negations_and_dangerous_verbs_are_not_corrected(text):
    assert correct_command_typo(text) is None
