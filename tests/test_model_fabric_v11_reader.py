from __future__ import annotations

from dataclasses import dataclass

from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class FakeGit:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return self.outputs.pop(0)


def test_default_branch_uses_git_symref_without_rest():
    fake = FakeGit([Result(0, "ref: refs/heads/main\tHEAD\n" + "a" * 40 + "\tHEAD\n")])

    def forbidden(*args, **kwargs):
        raise AssertionError("REST must not be used when git symref succeeds")

    reader = GitHubRepositoryReaderV11(git_runner=fake, opener=forbidden)
    assert reader.default_branch("Hawkar-usls/Hrain") == "main"
    assert reader.default_branch("Hawkar-usls/Hrain") == "main"
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == ["git", "ls-remote", "--symref", "https://github.com/Hawkar-usls/Hrain.git"]


def test_branch_head_uses_exact_git_ref_and_caches():
    sha = "b" * 40
    fake = FakeGit([Result(0, f"{sha}\trefs/heads/janus/activator-state\n")])

    def forbidden(*args, **kwargs):
        raise AssertionError("REST must not be used when git ref lookup succeeds")

    reader = GitHubRepositoryReaderV11(git_runner=fake, opener=forbidden)
    assert reader.branch_head("Hawkar-usls/Hawkar-usls", "janus/activator-state") == sha
    assert reader.branch_head("Hawkar-usls/Hawkar-usls", "janus/activator-state") == sha
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == [
        "git",
        "ls-remote",
        "https://github.com/Hawkar-usls/Hawkar-usls.git",
        "refs/heads/janus/activator-state",
    ]


def test_git_failure_falls_back_to_rest_branch_head():
    fake = FakeGit([Result(1, "", "transport unavailable")])
    calls = []

    class Response:
        def read(self):
            return b'{"commit":{"sha":"cccccccccccccccccccccccccccccccccccccccc"}}'

    def opener(request, timeout=20.0):
        calls.append(request.full_url)
        return Response()

    reader = GitHubRepositoryReaderV11(git_runner=fake, opener=opener)
    assert reader.branch_head("Hawkar-usls/Hawkar-usls", "main") == "c" * 40
    assert calls and calls[0].endswith("/repos/Hawkar-usls/Hawkar-usls/branches/main")


def test_unsafe_repository_and_branch_are_rejected_before_git():
    fake = FakeGit([])
    reader = GitHubRepositoryReaderV11(git_runner=fake)
    try:
        reader.branch_head("Hawkar-usls/Hawkar-usls;touch-x", "main")
    except ValueError as exc:
        assert str(exc) == "GIT_REPOSITORY_NAME_INVALID"
    else:
        raise AssertionError("unsafe repository must fail")

    try:
        reader.branch_head("Hawkar-usls/Hawkar-usls", "../../evil")
    except ValueError as exc:
        assert str(exc) == "GIT_BRANCH_NAME_INVALID"
    else:
        raise AssertionError("unsafe branch must fail")

    assert fake.calls == []
