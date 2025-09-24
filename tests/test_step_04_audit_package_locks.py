import csv
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODULE_NAME = "src.steps.step_04_audit_package_locks"
CACHE_UTILS_MODULE = "src.steps.cache_utils"
STEPS_DIR = PROJECT_ROOT / "src" / "steps"


class Step04AuditPackageLocksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._orig_pat = os.environ.get('AZURE_PAT')
        os.environ['AZURE_PAT'] = 'test-token'
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_root = Path(self.temp_dir.name)

        for name in (
            MODULE_NAME,
            CACHE_UTILS_MODULE,
            "step_04_audit_package_locks",
            "cache_utils",
        ):
            sys.modules.pop(name, None)

        self.cache_utils = importlib.import_module(CACHE_UTILS_MODULE)
        self.cache_utils.CACHE_ROOT = self.cache_root

        self.repo_item = {
            "project": {"name": "proj"},
            "repository": {"id": "1", "name": "Repo"},
            "path": "/src/package.json",
            "versions": [{"branchName": "main"}],
        }
        self.repo_key = self.cache_utils.build_repo_key(self.repo_item)
        package_content = {"name": "demo", "version": "1.0.0"}
        self.package_signature = self.cache_utils.signature_for_json(package_content)

        self.lock_content = {
            "name": "demo",
            "version": "1.0.0",
            "packages": {
                "": {
                    "name": "demo",
                    "version": "1.0.0",
                    "dependencies": {"left-pad": "^1.3.0"},
                },
                "node_modules/left-pad": {"version": "1.3.0"},
                "node_modules/foo": {
                    "name": "foo",
                    "version": "2.0.0",
                    "peerDependencies": {"bar": "^3.0.0"},
                },
            },
        }
        self.lock_signature = self.cache_utils.signature_for_json(self.lock_content)

        self.cache_utils.save_json_document(
            "package_lock",
            self.lock_signature,
            self.lock_content,
        )
        self.cache_utils.save_index(
            "package_lock_manifest.json",
            {
                self.lock_signature: {
                    "path": f"package_lock/{self.lock_signature}.json",
                    "repos": [self.repo_key],
                    "packageSignatures": [self.package_signature],
                    "sources": ["repository"],
                }
            },
        )
        self.cache_utils.save_index(
            "package_lock_repo_index.json",
            {
                self.repo_key: {
                    "project": "proj",
                    "repositoryName": "Repo",
                    "branch": "main",
                    "path": "/src/package.json",
                    "lockSignature": self.lock_signature,
                    "packageSignature": self.package_signature,
                    "source": "repository",
                }
            },
        )

        import click  # local import to patch echo only during module import

        self._original_click_echo = click.echo
        click.echo = lambda *args, **kwargs: None
        try:
            spec = importlib.util.spec_from_file_location(
                MODULE_NAME,
                STEPS_DIR / "step_04_audit_package_locks.py",
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("Cannot load step_04_audit_package_locks")
            module = importlib.util.module_from_spec(spec)
            sys.modules[MODULE_NAME] = module
            try:
                spec.loader.exec_module(module)
            except SystemExit:
                pass
            self.module = module
        finally:
            click.echo = self._original_click_echo

        default_output = self.cache_root / "package_lock_audit.csv"
        if default_output.exists():
            default_output.unlink()

    def tearDown(self) -> None:
        if self._orig_pat is None:
            os.environ.pop('AZURE_PAT', None)
        else:
            os.environ['AZURE_PAT'] = self._orig_pat

        for name in (
            MODULE_NAME,
            CACHE_UTILS_MODULE,
            "step_04_audit_package_locks",
            "cache_utils",
        ):
            sys.modules.pop(name, None)

    def test_flatten_package_lock_content_extracts_packages(self) -> None:
        flat = self.module.flatten_package_lock_content(self.lock_content)
        self.assertTrue(
            any(
                entry["name"] == "demo"
                and entry["entry_type"] == "installed"
                and entry["path"] == "."
                for entry in flat
            )
        )
        self.assertTrue(
            any(
                entry["name"] == "left-pad"
                and entry["entry_type"] == "dependency"
                and entry["path"] == "."
                for entry in flat
            )
        )
        self.assertTrue(
            any(
                entry["name"] == "left-pad"
                and entry["entry_type"] == "installed"
                and entry["path"] == "node_modules/left-pad"
                for entry in flat
            )
        )
        self.assertTrue(
            any(
                entry["name"] == "bar"
                and entry["entry_type"] == "peer"
                and entry["path"] == "node_modules/foo"
                for entry in flat
            )
        )

    def test_filter_and_evaluate_packages(self) -> None:
        flat = self.module.flatten_package_lock_content(self.lock_content)
        targets_idx = {"left-pad": "1.3.0", "bar": "2.0.0"}
        filtered = self.module.filter_packages(flat, targets_idx, include_all=False)
        evaluations = self.module.evaluate_packages(filtered, targets_idx)
        mapping = {
            (row["name"], row["path"], row["entry_type"]): row
            for row in evaluations
        }
        left_pad_dep = mapping[("left-pad", ".", "dependency")]
        self.assertEqual(left_pad_dep["status"], "covered")
        self.assertTrue(left_pad_dep["covered"])
        bar_peer = mapping[("bar", "node_modules/foo", "peer")]
        self.assertEqual(bar_peer["status"], "not_covered")
        self.assertFalse(bar_peer["covered"])

    def test_run_callback_generates_csv_with_expected_rows(self) -> None:
        packages_file = self.cache_root / "targets.txt"
        packages_file.write_text("left-pad@1.3.0\nbar@2.0.0\n", encoding="utf-8")
        output_path = self.cache_root / "audit.csv"

        with unittest.mock.patch.object(self.module.click, "echo") as mocked_echo:
            self.module.run.callback(
                packages_file=str(packages_file),
                output=str(output_path),
                include_all=False,
                force=False,
            )

        self.assertTrue(output_path.exists())
        with output_path.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 1)
        left_pad_rows = [
            row
            for row in rows
            if row["package_name"] == "left-pad" and row["entry_type"] == "dependency"
        ]
        self.assertTrue(left_pad_rows)
        self.assertEqual(left_pad_rows[0]["status"], "covered")
        self.assertEqual(left_pad_rows[0]["covered"], "true")
        self.assertEqual(left_pad_rows[0]["lock_signature"], self.lock_signature)
        self.assertEqual(left_pad_rows[0]["repo_key"], self.repo_key)
        bar_rows = [row for row in rows if row["package_name"] == "bar"]
        self.assertTrue(bar_rows)
        self.assertEqual(bar_rows[0]["covered"], "false")

        echoed = "".join(call.args[0] for call in mocked_echo.call_args_list)
        self.assertIn(str(output_path), echoed)


if __name__ == "__main__":
    unittest.main()
