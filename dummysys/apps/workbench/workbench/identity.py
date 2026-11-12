"""Stable process identity comparison, shared by platform adapters."""

def identity_matches(actual: dict | None, expected: dict) -> bool:
    return bool(isinstance(actual, dict) and isinstance(expected, dict)
                and type(expected.get("pid")) is int and expected["pid"] > 0
                and isinstance(expected.get("process_created_at"), str)
                and expected["process_created_at"].isdigit()
                and isinstance(expected.get("user_sid"), str) and expected["user_sid"]
                and all(actual.get(key) == expected[key]
                        for key in ("pid", "process_created_at", "user_sid")))

