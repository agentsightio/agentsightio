"""Importing the package must be free of side effects.

This is the regression guard for the defect that motivated the data-plane
rewrite: in 0.0.x, ``agentsight/client/`` built two singletons at module scope
and each raised ``NoApiKeyException`` when no key was set, so anyone using the
file exporter or their own span exporter could not import the package at all.

The checks run in a subprocess with a scrubbed environment and a working
directory containing no ``.env``, because ``agentsight`` loads one when it can
and that would otherwise supply the very key whose absence is under test.
"""

import os
import subprocess
import sys
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(source, tmp_path, **extra_env):
    """Execute `source` in a clean interpreter, from a directory with no .env."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": REPO_ROOT,
        "HOME": str(tmp_path),
    }
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_importing_without_an_api_key_does_not_raise(tmp_path):
    result = run(
        """
        import agentsight
        print("ok")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_importing_does_not_build_a_client(tmp_path):
    result = run(
        """
        import agentsight.api as api
        assert api._default is None, "a client was built at import time"
        print("ok")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_importing_opens_no_socket(tmp_path):
    result = run(
        """
        import socket

        class Tripwire(socket.socket):
            def connect(self, *a, **kw):
                raise AssertionError("import opened a socket")

        socket.socket = Tripwire
        import agentsight            # noqa: F401
        import agentsight.api        # noqa: F401
        print("ok")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_the_default_client_is_built_on_first_use(tmp_path):
    result = run(
        """
        import agentsight.api as api

        assert api._default is None
        client = api.client
        assert api._default is client
        assert client is api.client          # and only once
        print(client.endpoint)
        """,
        tmp_path,
        AGENTSIGHT_API_KEY="ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3",
    )

    assert result.returncode == 0, result.stderr
    assert "agentsight.io" in result.stdout


def test_touching_the_default_client_without_a_key_raises_there_not_at_import(tmp_path):
    result = run(
        """
        import agentsight.api as api
        from agentsight.exceptions import MissingApiKeyError

        try:
            api.client
        except MissingApiKeyError:
            print("raised at use")
        else:
            raise AssertionError("expected MissingApiKeyError")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "raised at use" in result.stdout


def test_an_unknown_attribute_still_raises_attribute_error(tmp_path):
    result = run(
        """
        import agentsight.api as api

        try:
            api.nonexistent
        except AttributeError:
            print("ok")
        else:
            raise AssertionError("expected AttributeError")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_the_legacy_clients_are_gone(tmp_path):
    result = run(
        """
        import agentsight

        for name in ("AgentSightAPI", "agentsight_api",
                     "ConversationManager", "conversation_manager"):
            assert not hasattr(agentsight, name), name

        for module in ("agentsight.client", "agentsight.http"):
            try:
                __import__(module)
            except ImportError:
                continue
            raise AssertionError(module + " still importable")
        print("ok")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
