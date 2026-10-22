"""Resource and entry-point regressions for the package layout."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from depupdater import paths
from depupdater.database.config import SQLITE_PATH


ROOT = Path(__file__).resolve().parents[1]


class LayoutTests(unittest.TestCase):
    def test_snapshots_and_shared_caches_stay_at_repository_root(self):
        self.assertEqual(paths.PROJECT_ROOT, ROOT)
        self.assertEqual(Path(SQLITE_PATH), ROOT / 'reusable_data.sqlite')
        self.assertEqual(Path(paths.JAR_DIR), ROOT / 'data' / 'jar')

    def test_all_bundled_analyzers_resolve_to_existing_files(self):
        for name in ['SOOTCG_PATH', 'SOOT_TYPE_DG_PATH', 'REVAPI_SH_PATH',
                     'BCEL_METHOD_PATH', 'BCEL_TYPE_PATH', 'JAPICMP_PATH']:
            with self.subTest(resource=name):
                resource = Path(getattr(paths, name))
                self.assertTrue(resource.is_absolute())
                self.assertTrue(resource.is_file(), resource)
                self.assertTrue(resource.is_relative_to(ROOT / 'tools' / 'analyzers'))

    def test_entry_points_import_without_parsing_arguments_or_loading_pipeline(self):
        result = subprocess.run(
            [sys.executable, '-c',
             "import sys; sys.argv = ['tool', '--invalid']; "
             "import depupdater.cli, depupdater.__main__, MainProcess; "
             "assert 'depupdater.graph.traversal' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_legacy_launcher_works_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / 'MainProcess.py'), '--help'],
                cwd=directory, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--analyzer-timeout', result.stdout)
        self.assertIn('--version-order', result.stdout)

    def test_package_entry_point_keeps_cli_error_exit_code(self):
        result = subprocess.run(
            [sys.executable, '-m', 'depupdater', '--invalid'],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_java_version_helper_resolves_after_working_directory_changes(self):
        environment = {**os.environ, 'PYTHONPATH': str(ROOT)}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-c',
                 'from depupdater.analysis.versions import sort_versions; '
                 'records = [{"version": "1.9"}, {"version": "1.10"}]; '
                 'assert [r["version"] for r in sort_versions(records, policy="maven")] '
                 '== ["1.10", "1.9"]'],
                cwd=directory, env=environment, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
