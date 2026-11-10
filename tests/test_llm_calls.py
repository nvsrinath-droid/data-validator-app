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


# ---- timeout and error messages ----------------------------------------------------------------

def raising(exc, seen):
    def call(**kwargs):
        seen.append(kwargs)
        raise exc
    return call


def test_every_call_carries_a_timeout_that_the_environment_can_change(monkeypatch):
    seen = []
    monkeypatch.setattr(agent_mod, "completion", lambda **kw: (seen.append(kw), mocked_completion()(**kw))[1])
    monkeypatch.delenv("TRUEALIGN_LLM_TIMEOUT", raising=False)
    AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi")
    monkeypatch.setenv("TRUEALIGN_LLM_TIMEOUT", "7.5")
    AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi")
    assert [c["timeout"] for c in seen] == [60.0, 7.5]


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5", "inf", "nan"])
def test_a_bad_timeout_setting_falls_back_to_the_default(monkeypatch, bad):
    monkeypatch.setenv("TRUEALIGN_LLM_TIMEOUT", bad)
    assert agent_mod.llm_timeout() == 60.0


def test_a_real_litellm_timeout_becomes_a_clear_message(monkeypatch):
    """LiteLLM's own mock_timeout raises its genuine Timeout after `timeout` seconds."""
    monkeypatch.setenv("TRUEALIGN_LLM_TIMEOUT", "0.2")
    monkeypatch.setattr(agent_mod, "completion", mocked_completion(mock_timeout=True))
    with pytest.raises(RuntimeError) as err:
        AIAgent("deepseek/deepseek-chat", "sk-secret")._call_llm("hi")
    text = str(err.value)
    assert "deepseek/deepseek-chat did not answer within 0.2 seconds" in text and "TRUEALIGN_LLM_TIMEOUT" in text
    assert "sk-secret" not in text


@pytest.mark.parametrize("exc, expected", [
    (litellm.AuthenticationError("bad sk-secret", "deepseek", "m"), "rejected the API key"),
    (litellm.RateLimitError("slow down sk-secret", "deepseek", "m"), "rate-limiting"),
    (litellm.NotFoundError("no such model", "m", "deepseek"), "was not found"),
    (litellm.APIConnectionError("dns failure sk-secret", "deepseek", "m"), "Could not reach the provider"),
    (ValueError("boom sk-secret"), "boom ***"),                  # anything else: provider text, key redacted
])
def test_provider_failures_get_plain_messages_and_never_echo_the_key(monkeypatch, exc, expected):
    seen = []
    monkeypatch.setattr(agent_mod, "completion", raising(exc, seen))
    with pytest.raises(RuntimeError) as err:
        AIAgent("deepseek/deepseek-chat", "sk-secret")._call_llm("hi")
    assert str(err.value).startswith("LLM Provider Error: ") and expected in str(err.value)
    assert "sk-secret" not in str(err.value)


@pytest.fixture
def hung_calls(monkeypatch):
    """completion() that blocks until the test releases it, with a tiny deadline, and a clean abandoned list."""
    release = threading.Event()
    calls = []
    monkeypatch.setenv("TRUEALIGN_LLM_TIMEOUT", "0.05")
    monkeypatch.setattr(agent_mod, "HARD_DEADLINE_GRACE", 0.05)
    monkeypatch.setattr(agent_mod, "_in_flight", set())
    monkeypatch.setattr(agent_mod, "completion", lambda **kw: (calls.append(kw), release.wait(30))[1])
    yield release, calls
    release.set()


def test_after_the_cap_of_hung_calls_new_calls_are_refused_without_contacting_the_provider(hung_calls, monkeypatch):
    release, calls = hung_calls
    monkeypatch.setattr(agent_mod, "MAX_IN_FLIGHT_CALLS", 2)
    agent = AIAgent("deepseek/deepseek-chat", "sk-secret")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="did not answer"):
            agent._call_llm("hi")
    assert len(calls) == 2
    with pytest.raises(RuntimeError) as err:
        agent._call_llm("hi")
    text = str(err.value)
    assert len(calls) == 2                                          # the third never reached completion()
    assert text == "Too many AI requests are running at once. Wait a moment and try again."
    assert "hanging" not in text
    assert "sk-secret" not in text and not text.startswith("LLM Provider Error")


def test_calls_are_accepted_again_once_the_hung_ones_finish(hung_calls, monkeypatch):
    release, calls = hung_calls
    monkeypatch.setattr(agent_mod, "MAX_IN_FLIGHT_CALLS", 1)
    agent = AIAgent("deepseek/deepseek-chat", "k")
    with pytest.raises(RuntimeError, match="did not answer"):
        agent._call_llm("hi")
    with pytest.raises(RuntimeError, match="running at once"):
        agent._call_llm("hi")
    release.set()                                                   # the provider finally answers the old call
    for t in list(agent_mod._in_flight):
        t.join(5)
    monkeypatch.setattr(agent_mod, "completion", mocked_completion())
    assert agent._call_llm("hi") == "hello"
    assert agent_mod._in_flight == set()


def test_twenty_concurrent_calls_never_exceed_the_cap(hung_calls, monkeypatch):
    release, calls = hung_calls
    cap = agent_mod.MAX_IN_FLIGHT_CALLS
    assert cap == 12
    start = threading.Barrier(20)
    outcomes, lock = [], threading.Lock()

    def one_call():
        start.wait()                                                # all 20 at the same moment
        try:
            AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi")
            result = "ok"
        except RuntimeError as e:
            result = "refused" if "running at once" in str(e) else "timeout"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=one_call) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(outcomes) == 20
    assert len(calls) == cap                                        # only the cap ever reached the provider
    assert outcomes.count("timeout") == cap and outcomes.count("refused") == 20 - cap
    assert len(agent_mod._in_flight) == cap


def test_a_call_that_finishes_before_its_deadline_is_never_counted(monkeypatch):
    monkeypatch.setattr(agent_mod, "_in_flight", set())
    monkeypatch.setattr(agent_mod, "completion", mocked_completion())
    for _ in range(agent_mod.MAX_IN_FLIGHT_CALLS + 2):
        assert AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi") == "hello"
    assert agent_mod._in_flight == set()


# ---- no retries, hard total deadline -----------------------------------------------------------

def test_litellm_is_told_not_to_retry(monkeypatch):
    seen = []
    monkeypatch.setattr(agent_mod, "completion", lambda **kw: (seen.append(kw), mocked_completion()(**kw))[1])
    AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi")
    assert seen[0]["max_retries"] == 0


def test_a_call_that_ignores_its_own_timeout_is_abandoned_at_the_hard_deadline(monkeypatch):
    release = threading.Event()
    monkeypatch.setenv("TRUEALIGN_LLM_TIMEOUT", "0.2")
    monkeypatch.setattr(agent_mod, "HARD_DEADLINE_GRACE", 0.3)
    monkeypatch.setattr(agent_mod, "completion", lambda **kw: release.wait(30))   # a hung connection
    monkeypatch.setattr(agent_mod, "_in_flight", set())
    started = time.time()
    try:
        with pytest.raises(RuntimeError) as err:
            AIAgent("deepseek/deepseek-chat", "sk-secret")._call_llm("hi")
    finally:
        release.set()
    elapsed = time.time() - started
    assert 0.5 <= elapsed < 5
    # The user waited timeout + grace (0.2 + 0.3), so that is what the message says, not the 0.2 s timeout.
    assert "did not answer within 0.5 seconds" in str(err.value) and "sk-secret" not in str(err.value)


def test_the_message_for_an_ordinary_timeout_still_names_the_timeout(monkeypatch):
    monkeypatch.setenv("TRUEALIGN_LLM_TIMEOUT", "0.2")
    monkeypatch.setattr(agent_mod, "HARD_DEADLINE_GRACE", 30)
    monkeypatch.setattr(agent_mod, "completion", mocked_completion(mock_timeout=True))
    with pytest.raises(RuntimeError, match="did not answer within 0.2 seconds"):
        AIAgent("deepseek/deepseek-chat", "k")._call_llm("hi")
