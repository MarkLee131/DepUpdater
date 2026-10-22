"""Resource, persistence and concurrent-download regressions; all fixtures are local."""
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import redirect_stderr
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import depupdater.cli as MainProcess
from depupdater.analysis.cache import run_cached
from depupdater.analysis.candidates import Computation
from depupdater.analysis.execution import AnalysisError
from depupdater.analysis.parallel import bounded_map
from depupdater.database import query
from depupdater.database.sqlite import Sqlite
from depupdater.preprocessing.download import download_jar, valid_jar
from depupdater.preprocessing.restore import Restore
from depupdater.runtime import default_workers, worker_count


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)


class FixtureComputation(Computation):
    """Picklable fixture exercising the real scheduling code under spawn."""
    def get_client_gav(self):
        return 'client:app:1'

    def __getstate__(self):
        self.transfers = getattr(self, 'transfers', 0) + 1
        return self.__dict__.copy()

    def version_compatibility_checker(self, version, client_gav):
        if version == 'pruned':
            raise AssertionError('pruned candidates must not be analyzed')
        if version == 'error':
            raise AnalysisError('fixture analysis failed')
        return {'version': version, 'breaking_reason': ['incompatible'] if version == 'bad' else []}


class WorkerTests(unittest.TestCase):
    def fixture(self, versions):
        node = {'GroupId': 'g', 'ArtifactId': 'a', 'Dependents': [],
                'Versions': [{'version': v, 'breaking_reason': ['software debloating'] if v == 'pruned' else []}
                             for v in versions]}
        return FixtureComputation(node, [], 'project', '.', [])

    def test_cpu_defaults_and_task_limits(self):
        with patch('depupdater.runtime.os.cpu_count', return_value=None):
            self.assertEqual(default_workers(), 1)
        with patch('depupdater.runtime.os.cpu_count', return_value=128):
            self.assertEqual(default_workers(), 4)
        with patch.dict(os.environ, {'DEPUPDATER_WORKERS': '60'}):
            self.assertEqual(worker_count(3), 3)
            self.assertEqual(worker_count(0), 1)

    def test_cli_rejects_invalid_limits(self):
        parser = MainProcess.build_parser()
        for flag, value in [('--workers', '0'), ('--workers', '-1'), ('--workers', '1.5'),
                            ('--analyzer-timeout', '0'), ('--analyzer-timeout', 'nan'),
                            ('--analyzer-timeout', 'inf')]:
            with self.subTest(flag=flag, value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(['-r', '.', '-m', '.', flag, value])

    def test_serial_execution_does_not_create_pool(self):
        fixture = self.fixture(['good', 'bad', 'pruned'])
        with patch.dict(os.environ, {'DEPUPDATER_WORKERS': '1'}), \
                patch('depupdater.analysis.candidates.tqdm'), \
                patch('depupdater.analysis.candidates.concurrent.futures.ProcessPoolExecutor') as pool:
            fixture.filter_version_by_compatibility(['good', 'bad', 'pruned'])
        pool.assert_not_called()
        self.assertEqual([v['breaking_reason'] for v in fixture.cur_node['Versions']],
                         [[], ['incompatible'], ['software debloating']])

    def test_spawn_matches_serial_and_transfers_graph_once_per_worker(self):
        versions = [str(i) for i in range(15)] + ['bad', 'pruned']
        serial = self.fixture(versions)
        parallel = self.fixture(versions)
        with patch.dict(os.environ, {'DEPUPDATER_WORKERS': '1'}), patch('depupdater.analysis.candidates.tqdm'):
            serial.filter_version_by_compatibility(versions)
        def spawn_pool(**kwargs):
            return ProcessPoolExecutor(mp_context=multiprocessing.get_context('spawn'), **kwargs)
        with patch.dict(os.environ, {'DEPUPDATER_WORKERS': '2'}), \
                patch('depupdater.analysis.candidates.tqdm'), \
                patch('depupdater.analysis.candidates.concurrent.futures.ProcessPoolExecutor', side_effect=spawn_pool):
            parallel.filter_version_by_compatibility(versions)
        self.assertEqual(serial.cur_node['Versions'], parallel.cur_node['Versions'])
        self.assertEqual(parallel.transfers, 2)

    def test_parallel_failure_propagates(self):
        fixture = self.fixture(['error', 'good'])
        with patch.dict(os.environ, {'DEPUPDATER_WORKERS': '2'}), patch('depupdater.analysis.candidates.tqdm'):
            with self.assertRaisesRegex(AnalysisError, 'fixture analysis failed'):
                fixture.filter_version_by_compatibility(['error', 'good'])

    def test_pruned_only_candidates_do_not_start_pool(self):
        fixture = self.fixture(['pruned'])
        with patch('depupdater.analysis.candidates.concurrent.futures.ProcessPoolExecutor') as pool:
            fixture.filter_version_by_compatibility(['pruned'])
        pool.assert_not_called()

    def test_pending_work_is_bounded_and_ordered(self):
        executor = MagicMock()
        def submit(function, value):
            future = Future()
            future.set_result(function(value))
            return future
        executor.submit.side_effect = submit
        results = bounded_map(executor, lambda value: value * 2, range(100), limit=3)
        self.assertEqual(next(results), 0)
        self.assertEqual(executor.submit.call_count, 4)  # initial 3 + one refill
        self.assertEqual(list(results), list(range(2, 200, 2)))

    def test_error_cancels_queued_tasks(self):
        failed, queued = Future(), Future()
        failed.set_exception(AnalysisError('failed'))
        executor = MagicMock()
        executor.submit.side_effect = [failed, queued]
        with self.assertRaises(AnalysisError):
            list(bounded_map(executor, str, [1, 2], limit=2))
        self.assertTrue(queued.cancelled())

    def test_dependency_preprocessing_does_not_mutate_serial_input(self):
        restore = Restore.__new__(Restore)
        dependency = {'GroupId': 'g', 'ArtifactId': 'a', 'Version': '1', 'Type': 'jar',
                      'Depth': 1, 'isoptional': False, 'Dependents': []}
        omitted = [{'GroupId': 'g', 'ArtifactId': 'a', 'Version': '2',
                    'Dependents': [{'GroupId': 'client', 'ArtifactId': 'app'}]}]
        with patch.object(restore, 'get_dep_jar', return_value=True):
            result = restore.process_a_valid_dep(dependency, omitted)
        self.assertIn('isoptional', dependency)
        self.assertEqual(dependency['Dependents'], [])
        self.assertEqual(result['Dependents'], omitted[0]['Dependents'])


class DatabaseTests(TemporaryCase):
    def database(self, schema):
        path = self.path / 'db.sqlite'
        with sqlite3.connect(path) as db:
            db.executescript(schema)
        return path

    def test_missing_snapshot_fails_without_creating_empty_database(self):
        path = self.path / 'missing.sqlite'
        with patch('depupdater.database.query.SQLITE_PATH', str(path)), self.assertRaises(sqlite3.OperationalError):
            query.query_call_graph('g', 'a', '1')
        self.assertFalse(path.exists())

    def test_missing_table_is_not_reported_as_cache_miss(self):
        path = self.database('CREATE TABLE other (id INTEGER);')
        with Sqlite(path) as db, self.assertRaises(sqlite3.OperationalError):
            db.query_data('missing')

    def test_multi_write_context_rolls_back_on_failure(self):
        # Intentionally missing callGraph: the insert must roll back if the update fails.
        path = self.database('CREATE TABLE api (groupId TEXT, artifactId TEXT, version TEXT);')
        with patch('depupdater.database.query.SQLITE_PATH', str(path)), self.assertRaises(sqlite3.OperationalError):
            query.store_call_graph('g', 'a', '1', 'graph')
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM api').fetchone()[0], 0)

    def test_successful_context_commits_and_closes(self):
        path = self.database('CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT);')
        db = Sqlite(path)
        with db:
            db.insert_data('records', {'id': 1, 'value': 'before'})
            db.update_data('records', {'value': 'after'}, [('id', '=', 1)])
        self.assertIsNone(db.conn)
        db.close()  # idempotent
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute('SELECT value FROM records').fetchone()[0], 'after')

    def test_no_connection_leak_on_early_return_or_bad_cached_json(self):
        path = self.database('CREATE TABLE Revapi (groupId TEXT, artifactId TEXT, oldVersion TEXT, '
                             'newVersion TEXT, binaryBcMethod TEXT, binaryBcType TEXT, '
                             'sourceBcMethod TEXT, sourceBcType TEXT);')
        instances = []
        class ObservedSqlite(Sqlite):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                instances.append(self)
        with patch('depupdater.database.query.SQLITE_PATH', str(path)), patch('depupdater.database.query.Sqlite', ObservedSqlite):
            self.assertEqual(query.query_revapi_bc_api('g', 'a', '1', '2'), (None,) * 4)
            self.assertIsNone(instances[-1].conn)
            with sqlite3.connect(path) as db:
                db.execute('INSERT INTO Revapi VALUES (?,?,?,?,?,?,?,?)', ('g', 'a', '1', '2', 'invalid', '{}', '{}', '{}'))
            with self.assertRaises(json.JSONDecodeError):
                query.query_revapi_bc_api('g', 'a', '1', '2')
            self.assertIsNone(instances[-1].conn)

    def test_sqlite_failure_is_not_hidden_as_download_failure(self):
        with patch('depupdater.preprocessing.restore.query_to_get_jar_location', side_effect=sqlite3.OperationalError('locked')), \
                patch('depupdater.preprocessing.restore.download_jar') as download:
            with self.assertRaises(sqlite3.OperationalError):
                Restore.get_dep_jar('g', 'a', '1', whether_log=False)
        download.assert_not_called()

    def test_mongo_identical_duplicates_are_read_without_deletion(self):
        client = MagicMock()
        collection = client.__getitem__.return_value.__getitem__.return_value
        collection.find.return_value = [{'dependencies': []}, {'dependencies': []}]
        with patch('depupdater.database.mongodb.pymongo.MongoClient', return_value=client):
            self.assertEqual(query.query_dependencies_from_mongo('g', 'a', '1'), [])
        collection.delete_many.assert_not_called()
        client.close.assert_called_once()

    def test_mongo_conflicts_fail_without_deletion_and_close_client(self):
        client = MagicMock()
        collection = client.__getitem__.return_value.__getitem__.return_value
        collection.find.return_value = [{'dependencies': []}, {'dependencies': [{'dep': 'g:b:2'}]}]
        with patch('depupdater.database.mongodb.pymongo.MongoClient', return_value=client):
            with self.assertRaisesRegex(ValueError, 'Conflicting dependency metadata'):
                query.query_dependencies_from_mongo('g', 'a', '1')
        collection.delete_many.assert_not_called()
        client.close.assert_called_once()

    def test_configured_analyzer_timeout_reaches_runner(self):
        with patch.dict(os.environ, {'DEPUPDATER_ANALYZER_TIMEOUT': '7.5',
                                    'DEPUPDATER_ANALYSIS_CACHE': str(self.path / 'cache.sqlite')}), \
                patch('depupdater.analysis.cache.run_checked', return_value='') as run:
            run_cached(['tool'], files=[], namespace='fixture')
        self.assertEqual(run.call_args.kwargs['timeout'], 7.5)


class Response:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self.chunks


class DownloadTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as jar:
            jar.writestr('content.txt', 'complete jar content')
        self.archive = data.getvalue()
        self.destination = self.path / 'artifact.jar'

    def test_valid_cache_skips_network(self):
        self.destination.write_bytes(self.archive)
        with patch('depupdater.preprocessing.download.requests.get') as get:
            download_jar('url', self.destination)
        get.assert_not_called()

    def test_streaming_does_not_publish_partial_archive(self):
        def chunks():
            yield self.archive[:10]
            self.assertFalse(self.destination.exists())
            yield self.archive[10:]
        response = Response(chunks())
        with patch('depupdater.preprocessing.download.requests.get', return_value=response):
            download_jar('url', self.destination)
        self.assertTrue(response.closed)
        self.assertEqual(self.destination.read_bytes(), self.archive)
        self.assertEqual(list(self.path.glob('*.part')), [])

    def test_interrupted_download_cleans_temporary_and_preserves_existing_file(self):
        self.destination.write_bytes(b'old corrupt archive')
        def chunks():
            yield self.archive[:10]
            raise OSError('connection interrupted')
        response = Response(chunks())
        with patch('depupdater.preprocessing.download.requests.get', return_value=response), self.assertRaises(OSError):
            download_jar('url', self.destination, retries=1)
        self.assertEqual(self.destination.read_bytes(), b'old corrupt archive')
        self.assertEqual(list(self.path.glob('*.part')), [])
        self.assertTrue(response.closed)

    def test_corrupt_response_is_retried_and_corrupt_cache_repaired(self):
        self.destination.write_bytes(b'bad cache')
        responses = [Response([b'not a jar']), Response([self.archive])]
        with patch('depupdater.preprocessing.download.requests.get', side_effect=responses) as get, \
                patch('depupdater.preprocessing.download.time.sleep'):
            download_jar('url', self.destination, retries=2)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(valid_jar(self.destination))
        self.assertEqual(list(self.path.glob('*.part')), [])

    def test_concurrent_downloads_publish_only_complete_files(self):
        barrier = threading.Barrier(2)
        def chunks():
            yield self.archive[:10]
            self.assertFalse(self.destination.exists())
            barrier.wait(timeout=5)
            yield self.archive[10:]
        def get(*args, **kwargs):
            return Response(chunks())
        with patch('depupdater.preprocessing.download.requests.get', side_effect=get), ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(download_jar, 'url', self.destination) for _ in range(2)]
            for task in tasks:
                task.result(timeout=10)
        self.assertEqual(self.destination.read_bytes(), self.archive)
        self.assertEqual(list(self.path.glob('*.part')), [])


if __name__ == '__main__':
    unittest.main()
