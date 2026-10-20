"""Copy the current working tree without changing its files, index, or stashes."""
from pathlib import Path
import shutil
import subprocess


def copy_project(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError('The workspace must be outside the input project')
    if destination.exists():
        raise ValueError(f'Workspace already exists: {destination}')
    # A new Git directory avoids worktree/submodule .git files pointing back at
    # the user's repository. --no-hardlinks also isolates Git object storage.
    if (source / '.git').exists():
        subprocess.run(['git', 'clone', '--no-hardlinks', '--no-checkout', '--',
                        str(source), str(destination)], check=True, capture_output=True, text=True)
        head = subprocess.run(['git', '-C', str(destination), 'rev-parse', '--verify', 'HEAD'],
                              capture_output=True)
        if head.returncode == 0:
            subprocess.run(['git', '-C', str(destination), 'read-tree', 'HEAD'], check=True)
    # Materialize symlinks rather than leaving paths back into the original tree.
    # Copy untracked/ignored files too: supplied local JARs may live in target/.
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False,
                    ignore=shutil.ignore_patterns('.git'))
    return destination
