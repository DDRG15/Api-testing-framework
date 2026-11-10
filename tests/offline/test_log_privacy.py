from src.utils.logger import _MASK, _mask_sensitive_body, _mask_sensitive_metadata


def test_nested_body_credentials_are_masked_without_mutating_the_payload():
    payload = {"items": [{"Password": "synthetic-sensitive", "amount": 3}],
               "auth": {"token": "synthetic-token"}}
    result = _mask_sensitive_body(None, "debug", {"request_body": payload})
    assert result["request_body"]["items"][0] == {"Password": _MASK, "amount": 3}
    assert result["request_body"]["auth"]["token"] == _MASK
    assert payload["items"][0]["Password"] == "synthetic-sensitive"


def test_url_credentials_queries_and_fragments_are_removed_from_metadata():
    auth = "demo:" + "synthetic-password"
    event = {"redis_url": f"redis://{auth}@localhost:6379/0",
             "url": "https://api.example.com/items?token=synthetic-token#private",
             "exception": f"Failed at https://{auth}@api.example.com/x?q=private"}
    result = _mask_sensitive_metadata(None, "error", event)
    assert result["redis_url"] == "redis://localhost:6379/0"
    assert result["url"] == "https://api.example.com/items?REDACTED"
    assert "synthetic-password" not in str(result)
    assert "synthetic-token" not in str(result)
    assert "private" not in str(result)


def test_metadata_preserves_counts_and_masks_nested_credentials():
    event = {"count": 2, "details": [{"secret": "synthetic-value", "status": "failed"}]}
    result = _mask_sensitive_metadata(None, "info", event)
    assert result == {"count": 2, "details": [{"secret": _MASK, "status": "failed"}]}
