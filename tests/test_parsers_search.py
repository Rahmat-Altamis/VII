"""Areas 7, 9-13: response parsing, raw results, url_citation, association."""
import json

from vii.domain.schemas import SearchResultItem
from vii.evidence import validation as vmod
from vii.evidence.sources import credibility_tier
from vii.meta import response_parser as rp


def _resp():
    return {
        "id": "resp_1",
        "output": [
            {"type": "web_search_call", "id": "ws_1", "results": [
                {"url": "https://www.eiffel-tower.com/en/", "title": "Official site",
                 "snippet": "330 metres tall"},
                {"url": "https://example.com/blog", "title": "Blog", "snippet": "tall tower"}]},
            {"type": "message", "content": [
                {"type": "output_text", "text": "It is 330m tall.",
                 "annotations": [
                     {"type": "url_citation", "url": "https://www.eiffel-tower.com/en/",
                      "title": "Official site", "cited_text": "330m",
                      "start_index": 6, "end_index": 10}]}]},
        ],
    }


def test_search_results_parsed():
    items = rp.parse_search_results(_resp())
    assert len(items) == 2 and items[0].search_response_id == "ws_1"
    assert rp.search_performed(_resp())


def test_no_search_call_means_not_performed():
    assert not rp.search_performed({"output": [{"type": "message", "content": []}]})


def test_citations_parsed_with_claim_link():
    cits = rp.parse_citations(_resp(), ["c001"])
    assert len(cits) == 1 and cits[0].claim_ids == ["c001"]
    assert cits[0].start_index == 6


def test_video_json_parsed():
    vu = rp.parse_video_json(json.dumps({"summary": "s", "factual_claims": [
        {"text": "X is true", "start_s": 1.0}]}), offline=True)
    assert vu.summary == "s" and rp.parsed_claims(vu)[0]["text"] == "X is true"


def test_video_malformed_falls_back():
    vu = rp.parse_video_json("not json at all {{{")
    assert isinstance(vu.summary, str)


def test_validation_counts():
    r = [SearchResultItem(url="https://a.example/x", title="t"),
         SearchResultItem(url="notaurl", title="bad")]
    from vii.domain.schemas import CitationAnnotation
    v = vmod.validate(r, [CitationAnnotation(url="https://a.example/x", claim_ids=["c1"])])
    assert v["retrieved"] == 2 and v["real"] == 1 and v["cited"] == 1


def test_credibility_prefers_official():
    assert credibility_tier("https://www.nasa.gov/x") > credibility_tier("https://randomblog.example/x")
