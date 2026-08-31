from __future__ import annotations

import base64
import unittest

from janus_spi.repo_audit_service import RepoAuditError, audit_public_repository, digest, verify_result


class FakeReader:
    def __init__(self):
        self.blobs = {
            "1" * 40: b"# Demo\nA repository claim.\n",
            "2" * 40: b"MIT License\n",
            "3" * 40: b"requests==2.32.0\npytest>=8\n",
            "4" * 40: b"name: ci\non: [push]\njobs: {}\n",
        }

    def get(self, path):
        if path == "/repos/acme/demo":
            return {"default_branch": "main", "private": False, "archived": False, "fork": False, "license": {"spdx_id": "MIT"}}
        if path.startswith("/repos/acme/demo/commits/"):
            return {"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
        if path.startswith("/repos/acme/demo/git/trees/"):
            return {
                "truncated": False,
                "tree": [
                    {"path": "README.md", "type": "blob", "sha": "1" * 40, "size": len(self.blobs["1" * 40])},
                    {"path": "LICENSE", "type": "blob", "sha": "2" * 40, "size": len(self.blobs["2" * 40])},
                    {"path": "requirements.txt", "type": "blob", "sha": "3" * 40, "size": len(self.blobs["3" * 40])},
                    {"path": ".github/workflows/ci.yml", "type": "blob", "sha": "4" * 40, "size": len(self.blobs["4" * 40])},
                    {"path": "tests/test_demo.py", "type": "blob", "sha": "5" * 40, "size": 10},
                    {"path": "src/demo.py", "type": "blob", "sha": "6" * 40, "size": 10},
                ]
            }
        if "/git/blobs/" in path:
            sha = path.rsplit("/", 1)[-1]
            raw = self.blobs[sha]
            return {"encoding": "base64", "content": base64.b64encode(raw).decode("ascii")}
        raise AssertionError(path)


def request():
    body = {
        "schema": "janus.market_service.repo_audit_request.v1",
        "request_id": "repo-audit-test-1",
        "sku": "JANUS.REPO_AUDIT",
        "buyer_actor_id": "internal-test:buyer",
        "repository": "acme/demo",
        "ref": "main",
        "audit_scope": "BOUNDED_STATIC_REPOSITORY_SURFACE",
        "bounds": {"max_tree_entries": 1000, "max_blob_files": 20, "max_total_blob_bytes": 500000},
        "read_only": True,
        "execute_repository_code": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }
    body["request_hash"] = digest(body)
    return body


class RepoAuditServiceTest(unittest.TestCase):
    def test_audit_is_exact_bound_and_read_only(self):
        req = request()
        result = audit_public_repository(req, reader=FakeReader())
        self.assertTrue(verify_result(result, request=req))
        self.assertEqual(result["target"]["resolved_commit_sha"], "a" * 40)
        self.assertTrue(result["architecture_map"]["has_tests"])
        self.assertTrue(result["architecture_map"]["has_ci"])
        self.assertTrue(result["license_observations"]["license_file_observed"])
        self.assertEqual(result["license_observations"]["license_metadata_from_github"], "MIT")
        self.assertFalse(result["authority"]["repository_code_executed"])
        self.assertFalse(result["authority"]["external_effect_authorized"])
        self.assertFalse(result["claim_audit"]["readme_semantic_claims_verified"])

    def test_dependency_observation_does_not_claim_execution(self):
        result = audit_public_repository(request(), reader=FakeReader())
        obs = result["dependency_observations"]["selected_manifest_observations"]
        req = next(x for x in obs if x["path"] == "requirements.txt")
        self.assertEqual(req["dependency_entry_count"], 2)
        self.assertEqual(req["pinned_exact_count"], 1)
        self.assertFalse(result["claim_audit"]["code_executed"])

    def test_tampered_request_fails_closed(self):
        req = request()
        req["repository"] = "other/repo"
        with self.assertRaisesRegex(RepoAuditError, "REPO_AUDIT_REQUEST_INVALID"):
            audit_public_repository(req, reader=FakeReader())

    def test_execution_authority_fails_closed(self):
        req = request()
        req["command_authority_granted"] = True
        req["request_hash"] = digest({k:v for k,v in req.items() if k != "request_hash"})
        with self.assertRaisesRegex(RepoAuditError, "REPO_AUDIT_REQUEST_INVALID"):
            audit_public_repository(req, reader=FakeReader())


if __name__ == "__main__":
    unittest.main()
