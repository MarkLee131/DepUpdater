"""CLI entry point. Importing this module never starts a run."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


def expand_resolve_abspath(path):
    return str(Path(path).expanduser().resolve())


def build_parser():
    parser = argparse.ArgumentParser(description='Analyze upgrades in an isolated project copy.')
    parser.add_argument('-r', '--root', required=True, help='path to the project working tree')
    parser.add_argument('-m', '--module', required=True, help='module path relative to root; . for root')
    parser.add_argument('-j', '--jar', help='client JAR path relative to root')
    parser.add_argument('-l', '--local_dep_jar', nargs='+', help='local dependency JAR paths relative to root')
    parser.add_argument('--output', help='new output directory outside the input project')
    parser.add_argument('--version-order', choices=['maven', 'legacy'], default='maven',
                        help='Maven order (default), or the original artifact comparator for comparison')
    return parser


def _relative_path(parser, root, value, label, *, file=False):
    path = Path(value)
    resolved = (root / path).resolve()
    if path.is_absolute() or not resolved.is_relative_to(root):
        parser.error(f'{label} must be a relative path inside --root')
    if file and not resolved.is_file():
        parser.error(f'{label} does not exist: {value}')
    return os.path.normpath(value)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    source = Path(args.root).expanduser().resolve()
    if not (source / 'pom.xml').is_file():
        parser.error('--root must contain pom.xml')
    args.module = _relative_path(parser, source, args.module, '--module')
    if not (source / args.module / 'pom.xml').is_file():
        parser.error('--module must contain pom.xml')
    if args.jar:
        args.jar = _relative_path(parser, source, args.jar, '--jar', file=True)
    if args.local_dep_jar:
        args.local_dep_jar = [_relative_path(parser, source, p, '--local_dep_jar', file=True)
                              for p in args.local_dep_jar]
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if output == source or source in output.parents:
            parser.error('--output must be outside the input project')
        if output.exists():
            parser.error('--output must be a new directory (previous runs are preserved)')
    else:
        output = None
    # Set before importing the pipeline; spawned analysis workers inherit these.
    try:
        if output is None:
            output = Path(tempfile.mkdtemp(prefix='depupdater-'))
        else:
            output.mkdir(parents=True)
        os.environ['DEPUPDATER_RUN_DIR'] = str(output / 'analysis')
        os.environ['DEPUPDATER_VERSION_ORDER'] = args.version_order
        import constants
        constants.configure_run_paths(output / 'analysis')
        from preprocess.workspace import copy_project
        workspace = copy_project(source, output / 'workspace' / source.name)
        metadata = {'source': str(source), 'workspace': str(workspace),
                    'module': args.module, 'version_order': args.version_order,
                    'status': 'running'}
        (output / 'run.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        print(f'Workspace: {workspace}', flush=True)
        print(f'Results: {output}', flush=True)
        args.root = str(workspace)
        original_cwd = os.getcwd()
        try:
            # Some Java analyzers write relative outputs such as sootOutput/.
            os.chdir(workspace)
            code = run_pipeline(args)
        finally:
            os.chdir(original_cwd)
    except KeyboardInterrupt:
        code = 130
        print('Interrupted; the input project was not modified.', file=sys.stderr)
    except Exception as exc:
        code = 1
        print(f'Analysis failed: {exc}', file=sys.stderr)
        if output is not None and output.is_dir():
            (output / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
    if output is not None and output.is_dir():
        metadata_path = output / 'run.json'
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        metadata.update(status='success' if code == 0 else 'failed', exit_code=code)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return code


def run_pipeline(args):
    from preprocess import exec_maven_command
    from preprocess.Restore import Restore
    from traverse.traverse import Traverse
    from constants import set_log_path, set_soot_empty_cases_csv, RET_DIR, DATA_DIR
    from evaluation.tech_lag import TechLag
    from evaluation.dep_count import count_deps
    from preprocess import multiModule
    from logger.logger import log_debug


    path_to_folder = args.root
    relative_path_to_module = args.module
    # get all local module
    local_module_inform = {}
    if args.local_dep_jar:
        MULTI_MODULE_FLAG = True
    else:
        # no local dependencies, so no need to consider multi-module
        MULTI_MODULE_FLAG = False
    if MULTI_MODULE_FLAG:
        module_paths = multiModule.get_all_module(path_to_folder)
        for module_path in module_paths:
            # local_module_inform is a mapping from local module's gav to its relative path
            local_module_inform.update(multiModule.get_gav(module_path, path_to_folder))

    repo_name = os.path.basename(path_to_folder)
    data_dir = os.path.join(RET_DIR, repo_name, '_' if relative_path_to_module == '.' else relative_path_to_module)
    os.makedirs(data_dir, exist_ok=True)
    log_path = os.path.join(data_dir, 'log.txt')
    set_log_path(log_path)
    set_soot_empty_cases_csv(os.path.join(data_dir, 'soot_empty_cases.csv'))
    log_debug(f'Version ordering: {args.version_order}')
    print("\n****** preprocessing ... ******\n")
    log_debug(f"Start preprocessing for {repo_name}/{relative_path_to_module}")

    print("\n****** preprocess.package ... ******\n")
    exit_code = exec_maven_command.mvn_package(path_to_folder, relative_path_to_module)
    if exit_code != 0:
        print("\n****** module package fails. Please check the project ******\n")
        return 1
    print("\n****** preprocess.package done! ******\n")
    exit_code = exec_maven_command.mvn_test(path_to_folder, relative_path_to_module)
    if exit_code != 0:
        print("\n****** module test fails. Please check the project ******\n")
        return 1

    print("\n****** get tree ... ******\n")
    tree_file, exit_code = exec_maven_command.mvn_verbose_dependency_tree(path_to_folder, relative_path_to_module)
    if exit_code != 0:
        print("\n****** module dependency tree fails. Please check the project ******\n")
        return 1
    print("\n****** tree got! ******\n")
    print("\n****** restore dependency to graph ... ******\n")
    graph = Restore(path_to_folder, relative_path_to_module, tree_file, local_module_inform, args.local_dep_jar)
    json_path, original_json_path, original_tech_lag, local_dep_gav = graph.restore(args.jar)
    print("\n****** dependency graph got! ******\n")
    print("\n****** preprocess done! ******\n")
    log_debug('\npreprocess done\n')
    original_dep_count = count_deps(original_json_path)

    if original_tech_lag[0] == 0:
        print("\n ****** The module is already up-to-date ******\n")
        log_debug('The module is already up-to-date')
        print("\n****** result ******\n")
        print('compile success:', True)
        print('test pass:', True)
        print('original technical lag:', 0)
        print('current technical lag:', 0)
        print('reduced technical lag:', 0)
        print('original dependency count:', original_dep_count)
        print('current dependency count:', original_dep_count)
        print('reduced dependency count:', 0)
        return 0

    log_debug(f"Start traversing for {repo_name}/{relative_path_to_module}")
    tra = Traverse(json_path, path_to_folder, relative_path_to_module)
    compile_flag, test_flag = tra.traverse(local_dep_gav)

    print("\n****** compute technical lag ... ******\n")
    log_debug(f"Start computing tech lag for {repo_name}/{relative_path_to_module}")
    lag = TechLag(json_path)
    lag_csv_path = os.path.join(DATA_DIR, 'lag.csv')
    with open(lag_csv_path, 'a') as f:
        writer = csv.writer(f)
        writer.writerow([repo_name, relative_path_to_module, original_tech_lag[0], lag.current_lag[0], \
            original_tech_lag[0] - lag.current_lag[0]])

    current_dep_count = count_deps(json_path)
    print("\n****** result ******\n")
    print('compile success:', compile_flag)
    print('test pass:', test_flag)
    print('original technical lag:', original_tech_lag[0])
    print('current technical lag:', lag.current_lag[0])
    print('reduced technical lag:', original_tech_lag[0] - lag.current_lag[0])
    print('original dependency count:', original_dep_count)
    print('current dependency count:', current_dep_count)
    print('reduced dependency count:', original_dep_count - current_dep_count)
    return 0 if compile_flag and test_flag else 1


if __name__ == "__main__":
    sys.exit(main())
