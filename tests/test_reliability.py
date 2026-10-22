"""Offline reliability regressions (no Maven/MongoDB downloads)."""
from collections import deque
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import itertools
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import Mock, patch

from lxml import etree

import depupdater.cli as MainProcess
import depupdater.paths as constants
from depupdater.analysis.cache import run_cached
from depupdater.analysis.api import Api
from depupdater.analysis.execution import AnalysisError, AnalysisTimeout, run_checked
from depupdater.analysis.revapi import Revapi
from depupdater.analysis.validation import Validation
from depupdater.analysis.versions import sort_versions, version_comparator
from depupdater.preprocessing.workspace import copy_project
from depupdater.graph.traversal import Traverse

ROOT = Path(__file__).resolve().parents[1]
NS = {'m': 'http://maven.apache.org/POM/4.0.0'}


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'DEPUPDATER_ANALYSIS_CACHE': str(self.path / 'verified.sqlite')})
        self.env.start()
        self.addCleanup(self.env.stop)


class WorkspaceTests(TemporaryCase):
    def git(self, path, *args):
        return subprocess.run(['git', '-C', str(path), *args], check=True,
                              capture_output=True, text=True).stdout

    def make_repository(self):
        source = self.path / 'input project'
        source.mkdir()
        self.git(source, 'init')
        self.git(source, 'config', 'user.email', 'test@example.invalid')
        self.git(source, 'config', 'user.name', 'Test')
        (source / 'pom.xml').write_text('<project/>')
        self.git(source, 'add', '.')
        self.git(source, 'commit', '-m', 'initial')
        (source / 'pom.xml').write_text('saved stash')
        self.git(source, 'stash', 'push', '-m', 'keep me')
        (source / 'pom.xml').write_text('staged content')
        self.git(source, 'add', 'pom.xml')
        (source / 'pom.xml').write_text('current uncommitted content')
        (source / 'untracked.txt').write_text('keep untracked')
        return source

    def test_copy_preserves_working_tree_index_stashes_and_untracked_files(self):
        source = self.make_repository()
        before = [self.git(source, *args) for args in [
            ('status', '--porcelain'), ('diff',), ('diff', '--cached'), ('stash', 'list')]]
        workspace = copy_project(source, self.path / 'output' / source.name)
        self.assertEqual((workspace / 'pom.xml').read_text(), 'current uncommitted content')
        self.assertEqual((workspace / 'untracked.txt').read_text(), 'keep untracked')
        (workspace / 'pom.xml').write_text('updated by tool')
        self.git(workspace, 'add', 'pom.xml')
        after = [self.git(source, *args) for args in [
            ('status', '--porcelain'), ('diff',), ('diff', '--cached'), ('stash', 'list')]]
        self.assertEqual(before, after)
        self.assertEqual((source / 'pom.xml').read_text(), 'current uncommitted content')

    def test_symlink_is_copied_as_independent_content(self):
        source = self.path / 'input'
        source.mkdir()
        external = self.path / 'external.txt'
        external.write_text('original')
        (source / 'linked.txt').symlink_to(external)
        workspace = copy_project(source, self.path / 'workspace')
        self.assertFalse((workspace / 'linked.txt').is_symlink())
        (workspace / 'linked.txt').write_text('modified')
        self.assertEqual(external.read_text(), 'original')

    def test_linked_git_worktree_gets_independent_git_directory(self):
        source = self.make_repository()
        linked = self.path / 'linked'
        self.git(source, 'worktree', 'add', '--detach', str(linked))
        workspace = copy_project(linked, self.path / 'copy')
        self.assertTrue((workspace / '.git').is_dir())
        self.assertNotEqual(self.git(workspace, 'rev-parse', '--git-common-dir').strip(),
                            self.git(linked, 'rev-parse', '--git-common-dir').strip())

    def test_refuses_recursive_copy(self):
        source = self.path / 'source'
        source.mkdir()
        with self.assertRaises(ValueError):
            copy_project(source, source / 'inside')


class EntryPointTests(TemporaryCase):
    def test_import_has_no_cli_or_pipeline_side_effects(self):
        result = subprocess.run([sys.executable, '-c',
                                 "import sys; sys.argv=['tool','--invalid']; import MainProcess; "
                                 "assert 'depupdater.graph.traversal' not in sys.modules; print('imported')"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'imported')

    def test_missing_arguments_exit_two(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            MainProcess.main([])
        self.assertEqual(error.exception.code, 2)

    def project(self):
        source = self.path / 'project'
        source.mkdir()
        (source / 'pom.xml').write_text('<project/>')
        return source

    def test_rejects_escaping_module(self):
        source = self.project()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            MainProcess.main(['-r', str(source), '-m', '..'])
        self.assertEqual(error.exception.code, 2)

    def test_exception_preserves_input_and_reports_failure(self):
        source = self.project()
        output = self.path / 'run'
        def fail(args):
            self.assertNotEqual(Path(args.root), source)
            self.assertEqual(Path.cwd(), Path(args.root))
            (Path(args.root) / 'pom.xml').write_text('candidate')
            Path('relative-analyzer-output').write_text('output')
            raise AnalysisTimeout('test timeout')
        original_cwd = Path.cwd()
        with patch.object(MainProcess, 'run_pipeline', side_effect=fail), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = MainProcess.main(['-r', str(source), '-m', '.', '--output', str(output)])
        self.assertEqual(code, 1)
        self.assertEqual(Path.cwd(), original_cwd)
        self.assertFalse((source / 'relative-analyzer-output').exists())
        self.assertEqual((source / 'pom.xml').read_text(), '<project/>')
        self.assertEqual(json.loads((output / 'run.json').read_text())['status'], 'failed')
        self.assertIn('test timeout', (output / 'error.txt').read_text())

    def test_interrupt_is_130(self):
        source = self.project()
        with patch.object(MainProcess, 'run_pipeline', side_effect=KeyboardInterrupt), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = MainProcess.main(['-r', str(source), '-m', '.', '--output', str(self.path / 'run')])
        self.assertEqual(code, 130)

    def test_existing_output_is_not_overwritten(self):
        source = self.project()
        output = self.path / 'run'
        output.mkdir()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            MainProcess.main(['-r', str(source), '-m', '.', '--output', str(output)])

    def test_run_paths_follow_repeated_calls_even_after_importing_pipeline(self):
        source = self.project()
        seen = []
        def run(args):
            import depupdater.preprocessing.maven as commands
            seen.append(commands.constants.TREE_DIR)
            return 0
        for number in range(2):
            with patch.object(MainProcess, 'run_pipeline', side_effect=run), redirect_stdout(io.StringIO()):
                self.assertEqual(MainProcess.main(['-r', str(source), '-m', '.', '--output',
                                                   str(self.path / f'run{number}')]), 0)
        self.assertNotEqual(*seen)
        self.assertTrue(seen[1].startswith(str((self.path / 'run1').resolve())))

    def test_pipeline_build_test_and_tree_failures_are_nonzero(self):
        source = self.project()
        args = SimpleNamespace(root=str(source), module='.', jar=None, local_dep_jar=None, version_order='maven')
        for failed_stage in ['mvn_package', 'mvn_test', 'mvn_verbose_dependency_tree']:
            with self.subTest(stage=failed_stage), ExitStack() as stack:
                constants.configure_run_paths(self.path / failed_stage)
                stack.enter_context(patch('depupdater.log.log_debug'))
                for name in ['mvn_package', 'mvn_test', 'mvn_verbose_dependency_tree']:
                    value = ('tree.txt', 1 if name == failed_stage else 0) if name.endswith('tree') else (1 if name == failed_stage else 0)
                    stack.enter_context(patch('depupdater.preprocessing.maven.' + name, return_value=value))
                stack.enter_context(redirect_stdout(io.StringIO()))
                self.assertEqual(MainProcess.run_pipeline(args), 1)

    def test_failed_final_validation_returns_nonzero(self):
        source = self.project()
        args = SimpleNamespace(root=str(source), module='.', jar=None, local_dep_jar=None, version_order='maven')
        for outcome in [(False, True), (True, False), (True, True)]:
            with self.subTest(outcome=outcome), ExitStack() as stack:
                constants.configure_run_paths(self.path / 'analysis')
                stack.enter_context(patch('depupdater.log.log_debug'))
                for name in ['mvn_package', 'mvn_test']:
                    stack.enter_context(patch('depupdater.preprocessing.maven.' + name, return_value=0))
                stack.enter_context(patch('depupdater.preprocessing.maven.mvn_verbose_dependency_tree', return_value=('tree', 0)))
                restore = stack.enter_context(patch('depupdater.preprocessing.restore.Restore'))
                restore.return_value.restore.return_value = ('graph', 'original', [1], [])
                traverse = stack.enter_context(patch('depupdater.graph.traversal.Traverse'))
                traverse.return_value.traverse.return_value = outcome
                lag = stack.enter_context(patch('depupdater.metrics.technical_lag.TechLag'))
                lag.return_value.current_lag = [0]
                stack.enter_context(patch('depupdater.metrics.dependency_count.count_deps', return_value=1))
                stack.enter_context(redirect_stdout(io.StringIO()))
                self.assertEqual(MainProcess.run_pipeline(args), 0 if all(outcome) else 1)

    def test_maven_paths_are_arguments_not_shell_commands(self):
        from depupdater.preprocessing.maven import mvn_package
        with patch('depupdater.preprocessing.maven.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            mvn_package('/project with spaces', 'module;touch sentinel')
        self.assertEqual(run.call_args.kwargs['cwd'], '/project with spaces/module;touch sentinel')
        self.assertNotIn('shell', run.call_args.kwargs)


class AnalyzerTests(TemporaryCase):
    def cache_count(self):
        with sqlite3.connect(self.path / 'verified.sqlite') as db:
            return db.execute('SELECT count(*) FROM successful_analysis').fetchone()[0]

    def test_nonzero_output_is_not_a_result(self):
        with self.assertRaisesRegex(AnalysisError, 'exited with 7'):
            run_checked([sys.executable, '-c', "import sys; print('partial'); sys.exit(7)"])

    def test_missing_executable_is_explicit_failure(self):
        with self.assertRaises(AnalysisError):
            run_checked([str(self.path / 'missing')])

    def test_timeout_is_distinct_and_not_cached(self):
        with self.assertRaises(AnalysisTimeout):
            run_cached([sys.executable, '-c', 'import time; time.sleep(5)'],
                       files=[], namespace='timeout', timeout=0.05)
        self.assertEqual(self.cache_count(), 0)

    def test_failure_is_not_cached(self):
        with self.assertRaises(AnalysisError):
            run_cached([sys.executable, '-c', 'raise RuntimeError("failure")'], files=[], namespace='failure')
        self.assertEqual(self.cache_count(), 0)

    def test_successful_empty_output_is_cached(self):
        with patch('depupdater.analysis.cache.run_checked', return_value='') as run:
            for _ in range(2):
                self.assertEqual(run_cached(['tool'], files=[], namespace='empty'), '')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.cache_count(), 1)

    def test_changed_jar_invalidates_cache(self):
        jar = self.path / 'local.jar'
        jar.write_bytes(b'version one')
        with patch('depupdater.analysis.cache.run_checked', return_value='result') as run:
            run_cached(['tool'], files=[jar], namespace='jar')
            jar.write_bytes(b'version two')
            run_cached(['tool'], files=[jar], namespace='jar')
        self.assertEqual(run.call_count, 2)

    def api(self):
        api = Api.__new__(Api)
        api.groupId, api.artifactId, api.version = 'g', 'a', '1'
        api.jar_path = str(self.path / 'artifact.jar')
        with zipfile.ZipFile(api.jar_path, 'w') as jar:
            jar.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
        api.can_download = True
        return api

    def test_empty_types_are_success_only_after_checked_execution(self):
        api = self.api()
        with patch('depupdater.analysis.api.run_cached', return_value='') as run:
            self.assertEqual(api.get_types(), (set(), True))
            run.assert_called_once()

    def test_type_analysis_failure_propagates_instead_of_returning_empty(self):
        api = self.api()
        with patch('depupdater.analysis.api.run_cached', side_effect=AnalysisError('BCEL failed')):
            with self.assertRaises(AnalysisError):
                api.get_types()

    def test_missing_jar_does_not_trigger_semver_fallback(self):
        api = self.api()
        api.can_download = False
        for method in [api.get_cg, api.get_type_dg, api.get_methods, api.get_types]:
            with self.subTest(method=method.__name__), self.assertRaises(AnalysisError):
                method()

    def test_bcel_zero_exit_with_error_diagnostics_is_not_cached(self):
        with self.assertRaises(AnalysisError):
            run_cached([sys.executable, '-c', "import sys; print('Failed to read JAR', file=sys.stderr)"],
                       files=[], namespace='bcel', reject_stderr=True)
        self.assertEqual(self.cache_count(), 0)

    def test_real_bcel_rejects_malformed_class_even_with_zero_exit(self):
        api = self.api()
        with zipfile.ZipFile(api.jar_path, 'a') as jar:
            jar.writestr('Broken.class', b'not bytecode')
        with self.assertRaises(AnalysisError):
            api.get_types()
        self.assertEqual(self.cache_count(), 0)

    def test_invalid_jar_fails_before_analyzer_execution(self):
        api = self.api()
        Path(api.jar_path).write_text('broken archive')
        with patch('depupdater.analysis.api.run_cached') as run, self.assertRaises(AnalysisError):
            api.get_types()
        run.assert_not_called()

    def test_real_bcel_accepts_valid_empty_jar(self):
        api = self.api()
        self.assertEqual(api.get_types(), (set(), True))
        self.assertEqual(api.get_methods(), (set(), True))

    def test_revapi_ignores_legacy_empty_results_and_never_caches_failure(self):
        old = self.path / 'old.jar'
        new = self.path / 'new.jar'
        old.write_bytes(b'old')
        new.write_bytes(b'new')
        script = self.path / 'rev api.sh'
        script.write_text('#!/bin/sh\necho failed >&2\nexit 9\n')
        script.chmod(0o755)
        with patch('depupdater.analysis.revapi.REVAPI_SH_PATH', str(script)), \
                patch('depupdater.database.query.query_revapi_bc_api', return_value=({}, {}, {}, {})) as legacy:
            with self.assertRaisesRegex(AnalysisError, 'exited with 9'):
                Revapi(str(old), str(new)).bc_api('g', 'a', '1', '2')
            legacy.assert_not_called()
        self.assertEqual(self.cache_count(), 0)

    def test_revapi_empty_success_yields_empty_changes(self):
        with patch('depupdater.analysis.revapi.run_cached', return_value=''):
            result = Revapi('old', 'new').bc_api('g', 'a', '1', '2')
        self.assertEqual(result, ({}, {}, {}, {}))

    def test_revapi_preserves_breaking_changes_on_success(self):
        report = 'old: class example.Removed\nnew: <none>\nBINARY: BREAKING\n\n'
        with patch('depupdater.analysis.revapi.run_cached', return_value=report):
            result = Revapi('old', 'new').bc_api('g', 'a', '1', '2')
        self.assertIn('example.Removed', result[1])


class PomTests(TemporaryCase):
    def validator(self, content):
        (self.path / 'pom.xml').write_text('<project xmlns="http://maven.apache.org/POM/4.0.0">' + content + '</project>')
        return Validation(str(self.path), '.')

    def tree(self):
        return etree.parse(str(self.path / 'pom.xml')).getroot()

    def test_direct_dependency_does_not_modify_bom_parent_profile_or_plugin(self):
        dep = '<dependency><groupId>g</groupId><artifactId>a</artifactId><version>1</version></dependency>'
        val = self.validator('''<parent><groupId>parent</groupId><artifactId>p</artifactId><version>1</version></parent>
            <dependencyManagement><dependencies>''' + dep + '''<dependency><groupId>g</groupId><artifactId>bom</artifactId>
            <version>1</version><type>pom</type><scope>import</scope></dependency></dependencies></dependencyManagement>
            <profiles><profile><id>test</id><dependencies>''' + dep + '''</dependencies></profile></profiles>
            <build><plugins><plugin><artifactId>plugin</artifactId><dependencies>''' + dep + '''</dependencies></plugin></plugins></build>
            <dependencies>''' + dep + '</dependencies>')
        val.add_direct_dependency('g', 'a', 'chosen')
        root = self.tree()
        self.assertEqual(root.findtext('m:dependencies/m:dependency/m:version', namespaces=NS), '${chosen}')
        for xpath in ['m:parent/m:version', 'm:dependencyManagement/m:dependencies/m:dependency/m:version',
                      'm:profiles/m:profile/m:dependencies/m:dependency/m:version',
                      'm:build/m:plugins/m:plugin/m:dependencies/m:dependency/m:version']:
            self.assertEqual(root.findtext(xpath, namespaces=NS), '1')
        self.assertEqual(root.findtext('m:dependencyManagement/m:dependencies/m:dependency[m:artifactId="bom"]/m:scope', namespaces=NS), 'import')

    def test_missing_direct_container_is_created_at_project_root(self):
        val = self.validator('<profiles><profile><dependencies/></profile></profiles>')
        val.add_direct_dependency('g', 'a', 'chosen')
        root = self.tree()
        self.assertIsNotNone(root.find('m:dependencies/m:dependency', NS))
        self.assertEqual(len(root.find('m:profiles/m:profile/m:dependencies', NS)), 0)

    def test_transitive_and_property_edits_do_not_target_profiles(self):
        val = self.validator('<profiles><profile><dependencyManagement><dependencies/></dependencyManagement>'
                             '<properties><g_a_version>old</g_a_version></properties></profile></profiles>')
        prop = val.set_pom_property_value('g', 'a', '2')
        val.add_transitive_dependency('g', 'a', prop)
        root = self.tree()
        self.assertEqual(root.findtext('m:properties/m:g_a_version', namespaces=NS), '2')
        self.assertEqual(root.findtext('m:profiles/m:profile/m:properties/m:g_a_version', namespaces=NS), 'old')
        self.assertIsNotNone(root.find('m:dependencyManagement/m:dependencies/m:dependency', NS))
        self.assertEqual(len(root.find('m:profiles/m:profile/m:dependencyManagement/m:dependencies', NS)), 0)

    def test_traversal_restores_original_on_analyzer_error(self):
        original = b'<project>\r\n  original\r\n</project>\r\n'
        pom = self.path / 'pom.xml'
        pom.write_bytes(original)
        traversal = Traverse.__new__(Traverse)
        traversal.path_to_project_folder = str(self.path)
        traversal.relative_path_to_module = '.'
        traversal.queue = deque([{'Depth': 1, 'GroupId': 'g', 'ArtifactId': 'a', 'Count': 0, 'Original_Version': '1'}])
        def fail(*args):
            pom.write_text('candidate')
            raise AnalysisError('failure')
        with patch('depupdater.graph.traversal.log_debug'), patch.object(traversal, 'compute_and_validate', side_effect=fail):
            with self.assertRaises(AnalysisError):
                traversal.traverse([])
        self.assertEqual(pom.read_bytes(), original)
        self.assertEqual((self.path / '_backed_up_pom.xml').read_text(), 'candidate')

    def test_restore_still_happens_when_candidate_export_fails(self):
        original, current = self.path / 'original.xml', self.path / 'pom.xml'
        original.write_bytes(b'original\r\n')
        current.write_bytes(b'candidate')
        with self.assertRaises(OSError):
            Validation.restore_pom(str(original), str(current), str(self.path / 'missing' / 'candidate.xml'))
        self.assertEqual(current.read_bytes(), b'original\r\n')


class OutputPathTests(TemporaryCase):
    def test_download_fallback_uses_configured_directory_without_trailing_slash(self):
        from depupdater.database.download_pom import download_pom_one
        output = self.path / 'output with spaces'
        constants.configure_run_paths(output)
        Path(constants.POM_PATH).mkdir(parents=True)
        local_repo = self.path / 'm2'
        artifact = local_repo / 'example/group/a/1/a-1.pom'
        artifact.parent.mkdir(parents=True)
        artifact.write_text('<project/>')
        with patch('depupdater.database.download_pom.M2_PATH', str(local_repo) + '/'), \
                patch('depupdater.database.download_pom.subprocess.check_output', return_value=b'') as mvn, \
                redirect_stdout(io.StringIO()):
            self.assertTrue(download_pom_one('example.group|a|1'))
        self.assertEqual((Path(constants.POM_PATH) / 'a-1.pom').read_text(), '<project/>')
        self.assertIn(f'-Ddest={constants.POM_PATH}', mvn.call_args.args[0])
        self.assertNotIn('shell', mvn.call_args.kwargs)


class VersionTests(unittest.TestCase):
    def records(self, versions):
        return [{'version': v, 'date': i} for i, v in enumerate(versions)]

    def test_original_cycle_has_one_order_for_all_permutations(self):
        records = [{'version': '2.0.0', 'date': 1}, {'version': '1.0.0', 'date': 3}, {'version': '1.5', 'date': 2}]
        orders = {tuple(r['version'] for r in sort_versions(list(p), policy='maven'))
                  for p in itertools.permutations(records)}
        self.assertEqual(orders, {('2.0.0', '1.5', '1.0.0')})
        self.assertLess(version_comparator(records[0], records[2]), 0)
        self.assertLess(version_comparator(records[2], records[1]), 0)
        self.assertLess(version_comparator(records[0], records[1]), 0)

    def test_maven_qualifiers_and_numeric_order(self):
        ascending = ['1.0-alpha1', '1.0-beta1', '1.0-m1', '1.0-rc1', '1.0-SNAPSHOT', '1.0', '1.0-sp1', '1.9', '1.10']
        result = sort_versions(self.records(ascending), policy='maven')
        self.assertEqual([r['version'] for r in result], list(reversed(ascending)))

    def test_equivalent_spellings_have_deterministic_tiebreaker(self):
        versions = ['1.0.0', '1.0-final', '1.0', '1']
        self.assertEqual([r['version'] for r in sort_versions(self.records(versions), policy='maven')], sorted(versions))

    def test_timestamps_do_not_affect_maven_order(self):
        records = self.records(['1.0', '2.0'])
        records[0]['date'] = 99999999
        original = [dict(r) for r in records]
        self.assertEqual([r['version'] for r in sort_versions(records, policy='maven')], ['2.0', '1.0'])
        self.assertEqual(records, original)

    def test_legacy_order_remains_explicitly_available(self):
        records = [{'version': '1.0', 'date': 2}, {'version': '2.0', 'date': 1}]
        self.assertEqual([r['version'] for r in sort_versions(records, policy='legacy')], ['1.0', '2.0'])

    def test_unknown_policy_fails(self):
        with self.assertRaises(ValueError):
            sort_versions([], policy='typo')


if __name__ == '__main__':
    unittest.main()
