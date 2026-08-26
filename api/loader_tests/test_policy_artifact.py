"""Approval-bound publication-policy artifact tests."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from brerc_loader.errors import LoaderPolicyInvalid
from brerc_loader.policy_artifact import (
    load_publication_policy_artifact,
    parse_publication_policy_artifact,
    policy_artifact_sha256,
)
from connector_tests.test_postgres_connector import approved_policy


class TestPolicyArtifact(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = approved_policy()
        self.secret = self.policy.public_id_salt.encode("utf-8")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "publication-policy.json"

    def write(self, document: object | None = None) -> bytes:
        payload = self.policy.approval_artifact() if document is None else document
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        self.path.write_bytes(raw)
        return raw

    def load(self, raw: bytes, *, secret: bytes | None = None):
        return load_publication_policy_artifact(
            self.path,
            expected_sha256=policy_artifact_sha256(raw),
            public_id_secret=self.secret if secret is None else secret,
        )

    def test_exact_artifact_and_secret_reconstruct_the_approved_policy(self):
        raw = self.write()
        loaded = self.load(raw)
        self.assertEqual(loaded, self.policy)
        self.assertNotIn(self.policy.public_id_salt, repr(loaded.approval_artifact()))
        self.assertEqual(
            parse_publication_policy_artifact(
                raw,
                expected_sha256=policy_artifact_sha256(raw),
                public_id_secret=self.secret,
            ),
            self.policy,
        )

    def test_wrong_artifact_digest_or_public_id_secret_fails(self):
        raw = self.write()
        with self.assertRaises(LoaderPolicyInvalid):
            load_publication_policy_artifact(
                self.path,
                expected_sha256="0" * 64,
                public_id_secret=self.secret,
            )
        with self.assertRaises(LoaderPolicyInvalid):
            self.load(raw, secret=b"different-public-id-secret-material-32bytes")

    def test_any_decision_mutation_invalidates_the_approval(self):
        document = self.policy.approval_artifact()
        document["decisions"]["ordinaryResolutionMetres"] = 1000
        raw = self.write(document)
        with self.assertRaises(LoaderPolicyInvalid):
            self.load(raw)

    def test_digest_consistent_but_semantically_invalid_policy_is_rejected(self):
        invalid = dataclasses.replace(
            self.policy,
            suppression_mode="none",
            min_records_per_cell=3,
            approval_digest=None,
        )
        invalid = dataclasses.replace(
            invalid,
            approval_digest=invalid._expected_approval_digest(),
        )
        document = self.policy.approval_artifact()
        document["decisions"] = invalid._decision_document()
        document["approval"]["approvalDigest"] = invalid.approval_digest
        raw = self.write(document)
        with self.assertRaises(LoaderPolicyInvalid):
            self.load(raw)

    def test_duplicate_json_keys_and_unknown_fields_are_rejected(self):
        duplicate = b'{"artifactFormat":"a","artifactFormat":"b"}'
        self.path.write_bytes(duplicate)
        with self.assertRaises(LoaderPolicyInvalid):
            self.load(duplicate)

        document = self.policy.approval_artifact()
        document["unexpected"] = True
        raw = self.write(document)
        with self.assertRaises(LoaderPolicyInvalid):
            self.load(raw)

    def test_reversible_original_ids_are_not_supported_by_the_loader(self):
        document = self.policy.approval_artifact()
        document["decisions"]["publishOriginalRecordIds"] = True
        document["decisions"]["publicIdScheme"] = "original"
        document["decisions"]["publicIdKeyFingerprint"] = None
        raw = self.write(document)
        with self.assertRaises(LoaderPolicyInvalid):
            self.load(raw)


if __name__ == "__main__":
    unittest.main()
