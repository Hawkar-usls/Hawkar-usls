from __future__ import annotations

import unittest

from janus_spi.model_fabric_v11 import ModelFabricCompilerV11


class BranchReader:
    def __init__(self):
        self.defaults = {
            "Hawkar-usls/old-tool": "master",
            "Hawkar-usls/special-tool": "develop",
        }
        self.heads = {
            ("Hawkar-usls/Hawkar-usls", "main"): "1" * 40,
            ("Hawkar-usls/old-tool", "master"): "2" * 40,
            ("Hawkar-usls/special-tool", "develop"): "3" * 40,
        }

    def default_branch(self, repository):
        return self.defaults.get(repository, "main")

    def branch_head(self, repository, branch="main"):
        return self.heads.get((repository, branch))


class CompilerHarness(ModelFabricCompilerV11):
    def __init__(self, reader):
        self.reader = reader
        self.manifest = {
            "schema": "janus.activator.model_manifest.v1",
            "model_id": "JANUS",
            "model_loading": {"routing_selects": "ACTIVITY_NOT_MEMBERSHIP"},
            "bootstrap_root": {"external_effect_authority": False},
        }


class ModelFabricV11Tests(unittest.TestCase):
    def test_non_bootstrap_members_lock_real_default_branch(self):
        compiler = CompilerHarness(BranchReader())
        entries = {
            "bootstrap_root": {
                "kind": "BOOTSTRAP_ROOT", "repository": "Hawkar-usls/Hawkar-usls",
                "branch": "main", "required": True,
            },
            "toolchain:old": {
                "kind": "TOOLCHAIN_DEPENDENCY", "repository": "Hawkar-usls/old-tool",
                "branch": "main", "required": False,
            },
            "toolchain:special": {
                "kind": "TOOLCHAIN_DEPENDENCY", "repository": "Hawkar-usls/special-tool",
                "branch": "main", "required": False,
            },
        }
        required, optional = compiler._resolve_heads(entries)
        self.assertEqual(required, [])
        self.assertEqual(optional, [])
        self.assertEqual(entries["bootstrap_root"]["branch"], "main")
        self.assertEqual(entries["toolchain:old"]["branch"], "master")
        self.assertEqual(entries["toolchain:special"]["branch"], "develop")
        self.assertEqual(entries["toolchain:old"]["branch_resolution"], "REPOSITORY_DEFAULT_BRANCH")
        self.assertEqual(entries["toolchain:special"]["head_status"], "LOCKED")

    def test_default_metadata_failure_falls_back_to_declared_branch(self):
        class Reader(BranchReader):
            def default_branch(self, repository):
                raise RuntimeError("metadata unavailable")

        compiler = CompilerHarness(Reader())
        entries = {
            "bootstrap_root": {
                "kind": "BOOTSTRAP_ROOT", "repository": "Hawkar-usls/Hawkar-usls",
                "branch": "main", "required": True,
            }
        }
        required, optional = compiler._resolve_heads(entries)
        self.assertEqual(required, [])
        self.assertEqual(optional, [])
        self.assertEqual(entries["bootstrap_root"]["head_status"], "LOCKED")


if __name__ == "__main__":
    unittest.main()
