from mcpset.cli import _append_only


def test_append_only_merges_unique_list_items():
    base = {"a": [1, 2], "b": {"c": 1}}
    incoming = {"a": [2, 3], "b": {"d": 4}}

    result = _append_only(base, incoming)

    assert result["a"] == [1, 2, 3]
    assert result["b"] == {"c": 1, "d": 4}


def test_append_only_preserves_existing_scalars():
    base = {"a": 1}
    incoming = {"a": 2, "b": 3}

    result = _append_only(base, incoming)

    assert result["a"] == 1
    assert result["b"] == 3
