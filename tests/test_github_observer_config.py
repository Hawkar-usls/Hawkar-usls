from pathlib import Path

from janus_spi.github_observer import GitHubObserver, RepoSource


def test_repo_source_keeps_extra_metadata():
    source = RepoSource.from_mapping({
        "repository": "Hawkar-usls/Hawkar-usls",
        "branch": "main",
        "role": "HOME_COGNITIVE_GATEWAY_AND_ROOT_ACTIVATOR",
        "root_activation_authority": True,
        "external_effect_authority": False,
    })
    assert source.metadata["root_activation_authority"] is True
    assert source.metadata["external_effect_authority"] is False


def test_current_constellation_initializes_observer():
    observer = GitHubObserver(Path("config/constellation.json"))
    repos = {source.repository: source for source in observer.sources}
    assert repos["Hawkar-usls/Hawkar-usls"].metadata["root_activation_authority"] is True
    assert repos["Hawkar-usls/Janus-Demiurge"].metadata["root_activation_authority"] is False
    assert repos["Hawkar-usls/janus-distributed-ai-swarm"].metadata["physical_runtime_inside_github"] is False
