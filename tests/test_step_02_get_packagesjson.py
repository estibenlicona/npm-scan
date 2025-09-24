import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

STEPS_DIR = Path(__file__).resolve().parents[1] / "src" / "steps"
if str(STEPS_DIR) not in sys.path:
    sys.path.insert(0, str(STEPS_DIR))


class Step02GetPackagesJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._orig_pat = os.environ.get('AZURE_PAT')
        os.environ['AZURE_PAT'] = 'test-token'
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_root = Path(self.temp_dir.name)

        for name in (
            "step_02_get_packagesjson",
            "cache_utils",
            "step_01_get_repositories",
        ):
            sys.modules.pop(name, None)

        self.cache_utils = importlib.import_module("cache_utils")
        self.cache_utils.CACHE_ROOT = self.cache_root

        self.module = importlib.import_module("step_02_get_packagesjson")

    def tearDown(self) -> None:
        if self._orig_pat is None:
            os.environ.pop('AZURE_PAT', None)
        else:
            os.environ['AZURE_PAT'] = self._orig_pat

        for name in (
            "step_02_get_packagesjson",
            "cache_utils",
            "step_01_get_repositories",
        ):
            sys.modules.pop(name, None)

    def test_load_packages_manifest_migrates_legacy_payloads(self) -> None:
        legacy_signature = "legacy"
        structured_signature = "structured"
        legacy_payload = {"name": "legacy-pkg"}
        structured_payload = {
            "path": f"{self.module.PACKAGE_JSON_SUBDIR}/structured.json",
            "repos": ["repo-a"],
        }
        self.cache_utils.save_index(
            self.module.PACKAGES_MANIFEST_FILE,
            {
                legacy_signature: legacy_payload,
                structured_signature: structured_payload,
            },
        )

        manifest = self.module.load_packages_manifest()

        self.assertIn(legacy_signature, manifest)
        migrated_entry = manifest[legacy_signature]
        self.assertEqual(
            migrated_entry["path"],
            f"{self.module.PACKAGE_JSON_SUBDIR}/{legacy_signature}.json",
        )
        self.assertEqual(migrated_entry["repos"], [])
        legacy_path = (
            self.cache_root
            / self.module.PACKAGE_JSON_SUBDIR
            / f"{legacy_signature}.json"
        )
        self.assertTrue(legacy_path.exists())

        self.assertIn(structured_signature, manifest)
        self.assertEqual(
            manifest[structured_signature]["path"],
            structured_payload["path"],
        )
        self.assertEqual(
            manifest[structured_signature]["repos"],
            structured_payload["repos"],
        )

        stored_manifest = self.cache_utils.load_index(
            self.module.PACKAGES_MANIFEST_FILE
        )
        self.assertEqual(manifest, stored_manifest)

    def test_get_packagesjson_downloads_and_updates_indexes(self) -> None:
        repo_item = {
            "project": {"name": "proj"},
            "repository": {"id": "1", "name": "Repo"},
            "path": "/src/package.json",
            "versions": [{"branchName": "main"}],
        }
        package_content = {"name": "demo", "version": "1.0.0"}
        repo_key = self.module.build_repo_key(repo_item)
        expected_signature = self.module.signature_for_json(package_content)

        with mock.patch.object(
            self.module,
            "load_repos_cache",
            return_value=[repo_item],
        ), mock.patch.object(
            self.module,
            "fetch_package_json",
            return_value=package_content,
        ) as mocked_fetch, mock.patch.object(
            self.module.click, "echo"
        ) as mocked_echo:
            self.module.get_packagesjson(force=True)

        mocked_fetch.assert_called_once_with(repo_item)
        manifest = self.cache_utils.load_index(
            self.module.PACKAGES_MANIFEST_FILE
        )
        self.assertIn(expected_signature, manifest)
        manifest_entry = manifest[expected_signature]
        self.assertEqual(manifest_entry["repos"], [repo_key])
        self.assertEqual(
            manifest_entry["path"],
            f"{self.module.PACKAGE_JSON_SUBDIR}/{expected_signature}.json",
        )

        repo_index = self.cache_utils.load_index(
            self.module.PACKAGES_REPO_INDEX_FILE
        )
        self.assertIn(repo_key, repo_index)
        metadata = repo_index[repo_key]
        self.assertEqual(metadata["signature"], expected_signature)
        self.assertEqual(metadata["project"], "proj")
        self.assertEqual(metadata["repositoryName"], "Repo")
        self.assertEqual(metadata["branch"], "main")

        stored_package = self.cache_utils.load_json_document(
            self.module.PACKAGE_JSON_SUBDIR,
            expected_signature,
        )
        self.assertEqual(stored_package, package_content)

        echoed = "".join(call.args[0] for call in mocked_echo.call_args_list)
        self.assertIn("Nuevos: 1", echoed)
        self.assertIn("Reutilizados: 0", echoed)

    def test_get_packagesjson_reuses_existing_when_not_forced(self) -> None:
        repo_item = {
            "project": {"name": "proj"},
            "repository": {"id": "1", "name": "Repo"},
            "path": "/src/package.json",
            "versions": [{"branchName": "main"}],
        }
        repo_key = self.module.build_repo_key(repo_item)
        signature = "sig-123"
        self.cache_utils.save_index(
            self.module.PACKAGES_REPO_INDEX_FILE,
            {
                repo_key: {
                    "signature": signature,
                    "repositoryId": "1",
                    "repositoryName": "Repo",
                    "project": "proj",
                    "path": "/src/package.json",
                    "branch": "main",
                }
            },
        )
        self.cache_utils.save_index(
            self.module.PACKAGES_MANIFEST_FILE,
            {
                signature: {
                    "path": f"{self.module.PACKAGE_JSON_SUBDIR}/{signature}.json",
                    "repos": [repo_key],
                }
            },
        )

        with mock.patch.object(
            self.module,
            "load_repos_cache",
            return_value=[repo_item],
        ), mock.patch.object(
            self.module,
            "fetch_package_json",
        ) as mocked_fetch, mock.patch.object(
            self.module.click, "echo"
        ) as mocked_echo:
            self.module.get_packagesjson(force=False)

        mocked_fetch.assert_not_called()
        echoed = "".join(call.args[0] for call in mocked_echo.call_args_list)
        self.assertIn("Reutilizados: 1", echoed)


if __name__ == "__main__":
    unittest.main()
