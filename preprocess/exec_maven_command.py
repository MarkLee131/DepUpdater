"""Execute Maven with argument lists so project paths are never shell code."""
import os
import subprocess

import constants


def create_folder(folder_path):
    os.makedirs(folder_path, exist_ok=True)


def _build(path_to_folder, module, flags, goals):
    module_dir = os.path.join(path_to_folder, module)
    result = subprocess.run(['mvn', *flags, *goals], cwd=module_dir)
    if result.returncode and module != '.':
        result = subprocess.run(['mvn', *flags, '-pl', module, '-am', *goals], cwd=path_to_folder)
    if result.returncode:
        result = subprocess.run(['mvn', *flags, *goals], cwd=path_to_folder)
    return result.returncode


def mvn_package(path_to_folder, relative_path_to_module):
    return _build(path_to_folder, relative_path_to_module,
                  ['-Dmaven.test.skip=true', '-Dcheckstyle.skip=true'], ['clean', 'package'])


def mvn_test(path_to_folder, relative_path_to_module):
    return _build(path_to_folder, relative_path_to_module,
                  ['-Dcheckstyle.skip=true', '-Denforcer.skip=true', '-Dflatten.skip=true'], ['test'])


def mvn_verbose_dependency_tree(path_to_folder, relative_path_to_module):
    result = subprocess.run(['mvn', 'dependency:tree', '-pl', relative_path_to_module,
                             '-am', '-Dverbose', '-fae'], cwd=path_to_folder,
                            text=True, capture_output=True)
    repo_name = os.path.basename(path_to_folder)
    tree_folder = os.path.join(constants.TREE_DIR, repo_name,
                               '_' if relative_path_to_module == '.' else relative_path_to_module)
    create_folder(tree_folder)
    tree_file = os.path.join(tree_folder, 'verbose_tree.txt')
    with open(tree_file, 'w', encoding='utf-8') as stream:
        stream.write(result.stdout)
    with open(os.path.join(tree_folder, 'stderr.txt'), 'w', encoding='utf-8') as stream:
        stream.write(result.stderr)
    return tree_file, result.returncode
