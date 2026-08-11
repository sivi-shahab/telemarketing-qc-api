"""Unit tests for compliance.pdf_parser against the example transcript PDFs."""
import glob
import os
from datetime import datetime

import pytest

from compliance.pdf_parser import (
    build_transcript,
    parse_filename_timestamp,
    parse_transcript_pdf,
    ticket_id_from_filename,
)

TRANS_DIR = os.path.join(os.path.dirname(__file__), "..", "example_final", "transkrip")


def _pdf(name):
    return os.path.join(TRANS_DIR, name)


# --------------------------------------------------------------------------
# parse_filename_timestamp
# --------------------------------------------------------------------------

def test_parse_filename_timestamp_basic():
    assert parse_filename_timestamp("201134FTJu_20260520110338.pdf") == datetime(2026, 5, 20, 11, 3, 38)


def test_parse_filename_timestamp_strips_duplicate_suffix():
    assert parse_filename_timestamp("130525f7HE_20260521140236 (1).pdf") == datetime(2026, 5, 21, 14, 2, 36)


def test_parse_filename_timestamp_with_full_path():
    assert parse_filename_timestamp(_pdf("201134FTJu_20260520110338.pdf")) == datetime(2026, 5, 20, 11, 3, 38)


def test_parse_filename_timestamp_invalid_returns_none():
    assert parse_filename_timestamp("weird_name.pdf") is None
    assert parse_filename_timestamp("no_timestamp_here.pdf") is None


# --------------------------------------------------------------------------
# parse_transcript_pdf
# --------------------------------------------------------------------------

def test_parse_single_pdf_segments():
    segs = parse_transcript_pdf(_pdf("201134FTJu_20260520110338.pdf"))
    # Known-good count from manual verification.
    assert len(segs) == 23
    first = segs[0]
    assert first["speaker"] == "SPEAKER_1"
    assert first["timestamp"] == "00:00.21 -> 00:29.81"
    assert first["text"].startswith("Hai. Ya, halo.")
    # both speakers tracked
    assert {s["speaker"] for s in segs} == {"SPEAKER_0", "SPEAKER_1"}
    # header lines are skipped (no "Transcription Report" leaking into text)
    assert all("Transcription Report" not in s["text"] for s in segs)


def test_parse_pdf_joins_cross_page_text():
    segs = parse_transcript_pdf(_pdf("201134FTJu_20260520110338.pdf"))
    # The segment starting at 03:36.96 spans the page-0 / page-1 boundary.
    seg = next(s for s in segs if s["timestamp"].startswith("03:36.96"))
    assert "Rp150.000" in seg["text"]           # start (page 0)
    assert "satu kali" in seg["text"]            # continuation (page 1)


def test_parse_pdf_no_empty_text():
    segs = parse_transcript_pdf(_pdf("201134FTJu_20260520110338.pdf"))
    assert all(s["text"].strip() for s in segs)


# --------------------------------------------------------------------------
# build_transcript
# --------------------------------------------------------------------------

def test_build_transcript_sorts_and_indexes():
    paths = glob.glob(_pdf("130220dkIM_*.pdf"))
    # shuffle by passing in reverse to prove sorting is by filename timestamp
    sorted_filenames, messages, _ = build_transcript(sorted(paths, reverse=True))
    # ascending by YYYYMMDDHHMMSS
    assert sorted_filenames == sorted(os.path.basename(p) for p in paths)
    # call_index is 1-based and contiguous
    indices = sorted({m["call_index"] for m in messages})
    assert indices == list(range(1, len(sorted_filenames) + 1))
    # every message carries the required keys (incl. ticket_id)
    for m in messages:
        assert set(m.keys()) == {"call_index", "ticket_id", "speaker", "timestamp", "text"}
    # ticket_id matches the source file stem for its call_index
    for m in messages:
        expected = ticket_id_from_filename(sorted_filenames[m["call_index"] - 1])
        assert m["ticket_id"] == expected


def test_ticket_id_from_filename():
    assert ticket_id_from_filename("130220dkIM_20260519132045.pdf") == "130220dkIM_20260519132045"
    # duplicate suffix stripped
    assert ticket_id_from_filename("130525f7HE_20260521140236 (1).pdf") == "130525f7HE_20260521140236"
    # customer id = prefix before underscore
    tid = ticket_id_from_filename("130220dkIM_20260519132045.pdf")
    assert tid.rsplit("_", 1)[0] == "130220dkIM"


def test_build_transcript_duplicate_suffix_set():
    paths = glob.glob(_pdf("130525f7HE_*.pdf"))
    sorted_filenames, messages, _ = build_transcript(paths)
    # 4 files (two base + two " (1)" duplicates), ascending by timestamp
    assert len(sorted_filenames) == len(paths)
    ts = [parse_filename_timestamp(f) for f in sorted_filenames]
    assert ts == sorted(ts)
    assert len(messages) > 0


def test_build_transcript_three_file_session():
    paths = glob.glob(_pdf("210112Fzav_*.pdf"))
    sorted_filenames, messages, _ = build_transcript(paths)
    assert len(sorted_filenames) == 3
    assert max(m["call_index"] for m in messages) == 3
