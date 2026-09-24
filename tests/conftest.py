"""Offline tests inject a tokenizer; measured counts belong to live evaluations."""

import pytest

from net2cloud import request_budget


class OfflineEncoding:
    def encode_ordinary(self, text):
        # Deliberately synthetic, deterministic counts: no vocabulary download.
        return range((len(text.encode("utf-8")) + 3) // 4)


@pytest.fixture(autouse=True)
def offline_tokenizer(monkeypatch):
    monkeypatch.setattr(request_budget, "_encoding", lambda: OfflineEncoding())
