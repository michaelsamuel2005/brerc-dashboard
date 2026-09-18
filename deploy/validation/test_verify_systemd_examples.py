from __future__ import annotations

import sys
import unittest
from pathlib import Path


VALIDATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = VALIDATION_DIR.parents[1]
sys.path.insert(0, str(VALIDATION_DIR))

import verify_systemd_examples as validator  # noqa: E402


class SystemdExampleContractTests(unittest.TestCase):
    def _spec(self, kind: str) -> validator.UnitSpec:
        return next(spec for spec in validator.UNIT_SPECS if spec.kind == kind)

    def _text(self, kind: str) -> str:
        spec = self._spec(kind)
        return (REPO_ROOT / spec.source).read_text(encoding="utf-8")

    def test_current_repository_examples_pass_the_contract(self) -> None:
        self.assertEqual(validator.validate_repository(REPO_ROOT), [])

    def test_public_api_cannot_bind_to_all_interfaces(self) -> None:
        spec = self._spec("public-api")
        unsafe = self._text("public-api").replace("--host 127.0.0.1", "--host 0.0.0.0")
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("loopback-only" in problem for problem in problems))

    def test_public_api_cannot_restore_a_credential_bearing_database_url(self) -> None:
        spec = self._spec("public-api")
        unsafe = self._text("public-api").replace(
            "UnsetEnvironment=PGPASSWORD DATABASE_URL",
            "UnsetEnvironment=PGPASSWORD",
        )
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("UnsetEnvironment" in problem for problem in problems))

    def test_environment_templates_cannot_override_fixed_production_mode(self) -> None:
        for source, fixed_name in validator.DEPLOYMENT_MODE_TEMPLATES:
            text = (REPO_ROOT / source).read_text(encoding="utf-8")
            self.assertNotIn(f"\n{fixed_name}=", f"\n{text}")

    def test_monitor_unit_unsets_the_legacy_direct_database_url(self) -> None:
        spec = self._spec("run-dashboard")
        unsafe = self._text("run-dashboard").replace(
            "UnsetEnvironment=PGPASSWORD RUN_DASHBOARD_DATABASE_URL",
            "UnsetEnvironment=PGPASSWORD",
        )
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("UnsetEnvironment" in problem for problem in problems))

    def test_mutable_current_release_path_is_rejected(self) -> None:
        spec = self._spec("initial")
        unsafe = self._text("initial").replace(
            f"releases/{validator.ARTIFACT_TOKEN}", "releases/current"
        )
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("mutable current paths" in problem for problem in problems))

    def test_refresh_must_quarantine_after_failure(self) -> None:
        spec = self._spec("refresh")
        unsafe = self._text("refresh").replace(
            "OnFailure=brerc-loader-refresh-quarantine.service\n", ""
        )
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("OnFailure" in problem for problem in problems))

    def test_initial_load_must_consume_approval_as_privileged_prestart(self) -> None:
        spec = self._spec("initial")
        unsafe = self._text("initial").replace("ExecStartPre=+", "ExecStartPre=")
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("ExecStartPre" in problem for problem in problems))

    def test_timer_cannot_silently_add_random_delay(self) -> None:
        spec = self._spec("timer")
        unsafe = self._text("timer").replace(
            "RandomizedDelaySec=0", "RandomizedDelaySec=30min"
        )
        problems = validator.validate_unit_text(spec, unsafe)
        self.assertTrue(any("RandomizedDelaySec" in problem for problem in problems))

    def test_duplicate_installed_names_are_rejected(self) -> None:
        original = validator.UNIT_SPECS
        duplicate = validator.UnitSpec(
            source=original[1].source,
            installed_name=original[0].installed_name,
            kind=original[1].kind,
        )
        try:
            validator.UNIT_SPECS = (*original, duplicate)
            problems = validator.validate_repository(REPO_ROOT)
        finally:
            validator.UNIT_SPECS = original
        self.assertTrue(any("duplicate installed unit name" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
