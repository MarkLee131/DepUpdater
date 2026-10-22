"""
define the constants about the data location

data folder structure:
    {PROJECT_ROOT}/data/
    ├── jar/
    | ├── {group_id}/
    | | ├── {artifact_id}/
    | | | ├── {version}/
    | ...
    ├── tree/
    | ├── {repo_name}/
    | | ├── {relative_path_to_module}/
    | | | ├── verbose_tree.txt
    |  ...
    ├── result/
    | ├── {repo_name}/
    | | ├── {relative_path_to_module}/
    | | | ├── version.json
    | | | ├── log.txt
    | | | ├── soot_empty_cases.csv 
    | ...
    ├── reachableApi/
    | ├── {repo_name}/
    | | ├── {relative_path_to_module}/
    | | | | ├── {group_id}/
    | | | | | ├── {artifact_id}/
    | | | | | | ├── methods.txt
    | | | | | | ├── types.txt
    | ...
    ├── tqdm_log/
    | ├── {repo_name}/
    | | ├── {relative_path_to_module}/
    | | | ├── {groupId}_{artifactId}.tqdm_log.txt
    | ...
    ├── validation_log/
    | ├── {repo_name}/
    | | ├── {relative_path_to_module}/
    | | | ├── {group_id}/
    | | | | ├── {artifact_id}/
    | | | | | ├── {version}/
    | | | | | | ├── recompile.txt
    | | | | | | ├── binary_bc_api.json
    ├── pom/
    | ├── errored.csv
"""
import os
from pathlib import Path

# path to the root dir of this Tool
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANALYZER_DIR = PROJECT_ROOT / 'tools' / 'analyzers'
JAVA_SOURCE_DIR = PROJECT_ROOT / 'tools' / 'java'

# path to data/
DATA_DIR = os.environ.get('DEPUPDATER_RUN_DIR', os.path.join(PROJECT_ROOT, 'data/'))
# path to data/tree/
TREE_DIR = os.path.join(DATA_DIR, 'tree/')
# path to data/jar/
JAR_DIR = os.path.join(PROJECT_ROOT, 'data/jar/')
# path to data/result/
RET_DIR = os.path.join(DATA_DIR, 'result/')


# path to version.json in RQ3
# VERSIONS_DIR = os.path.join(DATA_DIR, 'rq3_result/')
VERSIONS_DIR = os.path.join(DATA_DIR, 'extended_rq3_result/')

# absolute to tqdm_log/
TQDM_LOG_PATH = os.path.join(DATA_DIR, 'tqdm_log/')
# path to data/reachableApi/
REACHABLE_API_DIR = os.path.join(DATA_DIR, 'reachableApi/')
# path to data/validation_log/
VALIDATION_LOG_DIR = os.path.join(DATA_DIR, 'validation_log/')
# path to pom, which store the pom.xml used to update mongodb temporarily
POM_PATH = os.path.join(DATA_DIR, 'pom/')

# path to sootCG
SOOTCG_PATH = os.path.join(ANALYZER_DIR, 'sootCG-1.0-SNAPSHOT-jar-with-dependencies.jar')
# path to soot_Type_DG
SOOT_TYPE_DG_PATH = os.path.join(ANALYZER_DIR, 'soot_Type_DG-1.0-SNAPSHOT-jar-with-dependencies.jar')
# path to revapi.sh
REVAPI_SH_PATH = os.path.join(ANALYZER_DIR, 'revapi-0.12.0', 'revapi.sh')
# path to BCELgetMethod
BCEL_METHOD_PATH = os.path.join(ANALYZER_DIR, 'BCELgetMethod-1.0-SNAPSHOT-jar-with-dependencies.jar')
# path to BCELgetType
BCEL_TYPE_PATH = os.path.join(ANALYZER_DIR, 'BCELgetType-1.0-SNAPSHOT-jar-with-dependencies.jar')
# path to japicmp-0.18.3-jar-with-dependencies.jar
JAPICMP_PATH = os.path.join(ANALYZER_DIR, 'japicmp-0.18.3-jar-with-dependencies.jar')
# path to local maven repository, '~/.m2/repository/' default
M2_PATH = os.path.expanduser('~') + '/.m2/repository/'

# path to the log file. set in process
LOG_PATH = os.environ.get('DEPUPDATER_LOG_PATH')
# path to the soot empty cases file. set in process
SOOT_EMPTY_CASES_CSV = os.environ.get('DEPUPDATER_SOOT_EMPTY_CSV')
# path to the csv file that stores the download error jar
DOWNLOAD_ERROR_CSV = os.path.join(JAR_DIR, 'download_fail_jar.csv')

def set_log_path(path:str):
    """lazy-initialize LOG_PATH"""
    global LOG_PATH
    LOG_PATH = path
    os.environ['DEPUPDATER_LOG_PATH'] = path

def set_soot_empty_cases_csv(path:str):
    """lazy-initialize SOOT_EMPTY_CASES_CSV"""
    global SOOT_EMPTY_CASES_CSV
    SOOT_EMPTY_CASES_CSV = path
    os.environ['DEPUPDATER_SOOT_EMPTY_CSV'] = path

def configure_run_paths(directory):
    """Set per-run output paths; analyzers spawned later inherit the same root."""
    global DATA_DIR, TREE_DIR, RET_DIR, VERSIONS_DIR, TQDM_LOG_PATH
    global REACHABLE_API_DIR, VALIDATION_LOG_DIR, POM_PATH
    DATA_DIR = os.path.abspath(directory)
    os.environ['DEPUPDATER_RUN_DIR'] = DATA_DIR
    TREE_DIR = os.path.join(DATA_DIR, 'tree')
    RET_DIR = os.path.join(DATA_DIR, 'result')
    VERSIONS_DIR = os.path.join(DATA_DIR, 'extended_rq3_result')
    TQDM_LOG_PATH = os.path.join(DATA_DIR, 'tqdm_log')
    REACHABLE_API_DIR = os.path.join(DATA_DIR, 'reachableApi')
    VALIDATION_LOG_DIR = os.path.join(DATA_DIR, 'validation_log')
    POM_PATH = os.path.join(DATA_DIR, 'pom')

def get_log_path():
    """get LOG_PATH after setting"""
    global LOG_PATH
    return LOG_PATH

# get SOOT_EMPTY_CASES_CSV after setting
def get_soot_empty_cases_csv():
    """get SOOT_EMPTY_CASES_CSV after setting"""
    global SOOT_EMPTY_CASES_CSV
    return SOOT_EMPTY_CASES_CSV
