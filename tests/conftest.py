"""Shared test fixtures: load cached sample responses from samples/."""

import json
import os

import pytest

SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples"
)


def _load(name):
    with open(os.path.join(SAMPLES_DIR, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def hiring_cafe_sample():
    return _load("hiring_cafe.json")


@pytest.fixture
def greenhouse_sample():
    return _load("greenhouse.json")


@pytest.fixture
def lever_sample():
    return _load("lever.json")


@pytest.fixture
def ashby_sample():
    return _load("ashby.json")


class FakeHttp:
    """Stands in for HttpClient; returns a canned payload, records calls."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get_json(self, url, fixture=None, **kwargs):
        self.calls += 1
        return self.payload

    def post_json(self, url, json_body, fixture=None, **kwargs):
        self.calls += 1
        # Return payload only for page 0 so pagination terminates.
        if json_body.get("page", 0) == 0:
            return self.payload
        return {"results": []}


@pytest.fixture
def fake_http():
    return FakeHttp
