"""``bind_arguments`` and its signature cache.

The cache exists so ``inspect.signature()`` runs once per function instead of
once per call. These tests pin the behaviours the cache must not change: the
positional fallback for builtins, real parameter names for unhashable
callables (which cannot pass through ``lru_cache``), and the fallback on calls
that do not match the signature.
"""

import inspect

from agentsight.sdk import serialization
from agentsight.sdk.serialization import bind_arguments


def test_signature_is_constructed_once_per_function(monkeypatch):
    serialization._signature_of.cache_clear()

    calls = []
    real_signature = inspect.signature

    def counting_signature(func, *args, **kwargs):
        calls.append(func)
        return real_signature(func, *args, **kwargs)

    monkeypatch.setattr(inspect, "signature", counting_signature)

    def greet(name, punctuation="!"):
        return name + punctuation

    assert bind_arguments(greet, ("ada",), {}) == {"name": "ada", "punctuation": "!"}
    assert bind_arguments(greet, (), {"name": "bob"}) == {"name": "bob", "punctuation": "!"}
    assert calls == [greet]


def test_builtins_still_fall_back_to_positional_keys():
    # max, unlike len, has no inspectable signature even on modern CPython.
    assert bind_arguments(max, (3, 7), {}) == {"arg0": 3, "arg1": 7}


def test_unhashable_callable_keeps_real_parameter_names():
    class Handler:
        # Defining __eq__ without __hash__ makes instances unhashable, so
        # lru_cache raises TypeError before ever calling through.
        def __eq__(self, other):
            return self is other

        __hash__ = None

        def __call__(self, query, limit=10):
            return query

    arguments = bind_arguments(Handler(), ("find me",), {})
    assert arguments == {"query": "find me", "limit": 10}


def test_mismatched_call_falls_back_instead_of_raising():
    def one_arg(x):
        return x

    assert bind_arguments(one_arg, (1, 2, 3), {"k": 4}) == {
        "arg0": 1,
        "arg1": 2,
        "arg2": 3,
        "k": 4,
    }
