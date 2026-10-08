from __future__ import annotations

from medmind.core.tool_result_parser import (
    parse_mcp_result,
)


def test_structured_dict_passes_through():

    value = {
        "ok": True,
        "id": "APT-001",
    }

    assert (
        parse_mcp_result(value)
        == value
    )


def test_json_string_is_parsed():

    result = parse_mcp_result(
        '{"ok": true, "count": 2}'
    )

    assert result == {
        "ok": True,
        "count": 2,
    }


def test_python_literal_string_is_parsed():

    result = parse_mcp_result(
        "{'ok': True, 'count': 2}"
    )

    assert result == {
        "ok": True,
        "count": 2,
    }


def test_plain_string_is_preserved():

    result = parse_mcp_result(
        "normal text"
    )

    assert result == "normal text"


def test_single_text_block_is_unwrapped():

    result = parse_mcp_result(
        [
            {
                "type": "text",
                "text": (
                    '{"doctor": "Maher"}'
                ),
            }
        ]
    )

    assert result == {
        "doctor": "Maher",
    }


def test_json_list_inside_text_block_is_flattened():

    result = parse_mcp_result(
        [
            {
                "type": "text",
                "text": (
                    '[{"id": 1}, {"id": 2}]'
                ),
            }
        ]
    )

    assert result == [
        {"id": 1},
        {"id": 2},
    ]


def test_non_text_block_is_preserved():

    block = {
        "type": "resource",
        "uri": "test://resource",
    }

    result = parse_mcp_result(
        [block]
    )

    assert result == block


def test_non_dict_list_item_is_preserved():

    result = parse_mcp_result(
        [
            123,
            {
                "type": "text",
                "text": '{"ok": true}',
            },
        ]
    )

    assert result == [
        123,
        {
            "ok": True,
        },
    ]


def test_malformed_text_block_remains_text():

    result = parse_mcp_result(
        [
            {
                "type": "text",
                "text": "not-json",
            }
        ]
    )

    assert result == "not-json"