import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

STEPS_DIR = Path(__file__).resolve().parents[1] / "src" / "steps"
if str(STEPS_DIR) not in sys.path:
    sys.path.insert(0, str(STEPS_DIR))


class Step03GetPackageLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_root = Path(self.temp_dir.name)

        for name in (
            "step_03_get_package_lock",
            "cache_utils",
            "step_02_get_packagesjson",
            "step_01_get_repositories",
        ):
            sys.modules.pop(name, None)

        self.cache_utils = importlib.import_module("cache_utils")
        self.cache_utils.CACHE_ROOT = self.cache_root

        self.module = importlib.import_module("step_03_get_package_lock")

    def tearDown(self) -> None:
        for name in (
            "step_03_get_package_lock",
            "cache_utils",
            "step_02_get_packagesjson",
            "step_01_get_repositories",
        ):
            sys.modules.pop(name, None)

    def _store_package_entry(self, repo_item: dict) -> str:
        repo_key = self.module.build_repo_key(repo_item)
        package_content = {"name": "demo", "version": "1.0.0"}
        package_signature = self.module.signature_for_json(package_content)
        self.cache_utils.save_index(
            self.module.PACKAGES_REPO_INDEX_FILE,
            {
                repo_key: {
                    "signature": package_signature,
                    "repositoryId": repo_item["repository"]["id"],
                    "repositoryName": repo_item["repository"]["name"],
                    "project": repo_item["project"]["name"],
                    "path": repo_item["path"],
                    "branch": repo_item["versions"][0]["branchName"],
                }
            },
        )
        self.cache_utils.save_json_document(
            self.module.PACKAGE_JSON_SUBDIR,
            package_signature,
            package_content,
        )
        return package_signature

    def test_get_package_lock_downloads_and_updates_indexes(self) -> None:
        repo_item = {
            "project": {"name": "proj"},
            "repository": {"id": "1", "name": "Repo"},
            "path": "/src/package.json",
            "versions": [{"branchName": "main"}],
        }
        package_signature = self._store_package_entry(repo_item)
        repo_key = self.module.build_repo_key(repo_item)
        lock_content = {"name": "demo", "version": "1.0.0", "packages": {}}
        expected_lock_signature = self.module.signature_for_json(lock_content)

        with mock.patch.object(
            self.module,
            "load_repos_cache",
            return_value=[repo_item],
        ), mock.patch.object(
            self.module,
            "fetch_package_lock_from_repo",
            return_value=(lock_content, None),
        ) as mocked_fetch, mock.patch.object(
            self.module,
            "generate_lock_with_npm",
        ) as mocked_generate, mock.patch.object(
            self.module.click, "echo"
        ) as mocked_echo:
            self.module.get_package_lock(force=True)

        mocked_fetch.assert_called_once_with(repo_item)
        mocked_generate.assert_not_called()

        manifest = self.cache_utils.load_index(
            self.module.PACKAGE_LOCK_MANIFEST_FILE
        )
        self.assertIn(expected_lock_signature, manifest)
        manifest_entry = manifest[expected_lock_signature]
        self.assertEqual(manifest_entry["repos"], [repo_key])
        self.assertEqual(manifest_entry["packageSignatures"], [package_signature])
        self.assertEqual(manifest_entry["sources"], ["repository"])

        repo_index = self.cache_utils.load_index(
            self.module.PACKAGE_LOCK_REPO_INDEX_FILE
        )
        self.assertIn(repo_key, repo_index)
        metadata = repo_index[repo_key]
        self.assertEqual(metadata["lockSignature"], expected_lock_signature)
        self.assertEqual(metadata["packageSignature"], package_signature)
        self.assertEqual(metadata["source"], "repository")

        stored_lock = self.cache_utils.load_json_document(
            self.module.PACKAGE_LOCK_SUBDIR,
            expected_lock_signature,
        )
        self.assertEqual(stored_lock, lock_content)

        echoed = "".join(call.args[0] for call in mocked_echo.call_args_list)
        self.assertIn("Descargados: 1", echoed)
        self.assertIn("Generados: 0", echoed)

    def test_get_package_lock_generates_when_missing(self) -> None:
        repo_item = {
            "project": {"name": "proj"},
            "repository": {"id": "1", "name": "Repo"},
            "path": "/src/package.json",
            "versions": [{"branchName": "main"}],
        }
        package_signature = self._store_package_entry(repo_item)
        repo_key = self.module.build_repo_key(repo_item)
        generated_lock = {"name": "demo", "lockfileVersion": 2}
        expected_lock_signature = self.module.signature_for_json(generated_lock)

        with mock.patch.object(
            self.module,
            "load_repos_cache",
            return_value=[repo_item],
        ), mock.patch.object(
            self.module,
            "fetch_package_lock_from_repo",
            return_value=(None, "missing"),
        ), mock.patch.object(
            self.module,
            "generate_lock_with_npm",
            return_value=generated_lock,
        ) as mocked_generate, mock.patch.object(
            self.module.click, "echo"
        ) as mocked_echo:
            self.module.get_package_lock(force=True)

        mocked_generate.assert_called_once()

        manifest = self.cache_utils.load_index(
            self.module.PACKAGE_LOCK_MANIFEST_FILE
        )
        manifest_entry = manifest[expected_lock_signature]
        self.assertEqual(manifest_entry["repos"], [repo_key])
        self.assertEqual(manifest_entry["packageSignatures"], [package_signature])
        self.assertEqual(manifest_entry["sources"], ["generated"])

        echoed = "".join(call.args[0] for call in mocked_echo.call_args_list)
        self.assertIn("Generados: 1", echoed)

    def test_get_package_lock_reuses_cached_when_not_forced(self) -> None:
        repo_item = {
            "project": {"name": "proj"},
            "repository": {"id": "1", "name": "Repo"},
            "path": "/src/package.json",
            "versions": [{"branchName": "main"}],
        }
        package_signature = self._store_package_entry(repo_item)
        repo_key = self.module.build_repo_key(repo_item)
        lock_content = {"name": "demo", "lockfileVersion": 2}
        lock_signature = self.module.signature_for_json(lock_content)
        self.cache_utils.save_json_document(
            self.module.PACKAGE_LOCK_SUBDIR,
            lock_signature,
            lock_content,
        )
        self.cache_utils.save_index(
            self.module.PACKAGE_LOCK_REPO_INDEX_FILE,
            {
                repo_key: {
                    "lockSignature": lock_signature,
                    "packageSignature": package_signature,
                    "source": "repository",
                    "repositoryId": repo_item["repository"]["id"],
                    "repositoryName": repo_item["repository"]["name"],
                    "project": repo_item["project"]["name"],
                    "path": repo_item["path"],
                    "branch": repo_item["versions"][0]["branchName"],
                }
            },
        )
        self.cache_utils.save_index(
            self.module.PACKAGE_LOCK_MANIFEST_FILE,
            {
                lock_signature: {
                    "path": f"{self.module.PACKAGE_LOCK_SUBDIR}/{lock_signature}.json",
                    "repos": [repo_key],
                    "packageSignatures": [package_signature],
                    "sources": ["repository"],
                }
            },
        )

        with mock.patch.object(
            self.module,
            "load_repos_cache",
            return_value=[repo_item],
        ), mock.patch.object(
            self.module,
            "fetch_package_lock_from_repo",
            side_effect=AssertionError("fetch should not be called"),
        ), mock.patch.object(
            self.module.click, "echo"
        ) as mocked_echo:
            self.module.get_package_lock(force=False)

        echoed = "".join(call.args[0] for call in mocked_echo.call_args_list)
        self.assertIn("Reutilizados: 1", echoed)


if __name__ == "__main__":
    unittest.main()
