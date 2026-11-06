"""Behaviour of AIAgent._call_llm around the LiteLLM call: warnings, timeout and error messages."""
import threading
import time
import warnings

import litellm
import pytest

import ai.agent as agent_mod
from ai.agent import AIAgent

PYDANTIC_TEXT = ("Pydantic serializer warnings:\n  PydanticSerializationUnexpectedValue(Expected 10 fields but got 5: "
                 "Expected `Message` - serialized value may not be as expected [field_name='message'])")


def mocked_completion(**fixed):
    """The real litellm.completion with a canned reply (no network), so LiteLLM's own code paths run."""
    real = litellm.completion

    def call(**kwargs):
        return real(**{**kwargs, "mock_response": "hello", **fixed})
    return call


def pydantic_warnings(caught):
    return [w for w in caught if "Pydantic serializer warnings" in str(w.message)]


def test_filter_ignores_only_the_serializer_warning_even_from_another_thread():
    """LiteLLM emits the warning from a worker thread after completion() has returned, so the filter has to be
    process-wide (catch_warnings in the caller could never see it)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        agent_mod.silence_litellm_serializer_warning()
        t = threading.Thread(target=lambda: (warnings.warn(PYDANTIC_TEXT, UserWarning),
                                             warnings.warn("something unrelated", UserWarning)))
        t.start()
        t.join()
    assert [str(w.message) for w in caught] == ["something unrelated"]


def _call_and_wait(monkeypatch, seconds=3.0, stop_when_seen=False):
    monkeypatch.setattr(agent_mod, "completion", mocked_completion())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")             # what a test runner does: nothing is filtered out
        assert AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi") == "hello"
        deadline = time.time() + seconds
        while time.time() < deadline and not (stop_when_seen and pydantic_warnings(caught)):
            time.sleep(0.05)
    return caught


def test_a_real_litellm_call_through_the_agent_emits_no_serializer_warning(monkeypatch):
    assert pydantic_warnings(_call_and_wait(monkeypatch, seconds=1.5)) == []


def test_control_litellm_itself_does_emit_it_without_our_filter():
    """Guards the test above: if LiteLLM stops emitting the warning, the silencing is no longer needed."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        litellm.completion(model="deepseek/deepseek-chat", messages=[{"role": "user", "content": "hi"}],
                           api_key="k", mock_response="hello")
        deadline = time.time() + 3
        while time.time() < deadline and not pydantic_warnings(caught):
            time.sleep(0.05)
    if not pydantic_warnings(caught):
        pytest.skip("this LiteLLM/pydantic combination no longer emits the warning")
