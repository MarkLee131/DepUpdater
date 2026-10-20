"""get and sort all versions of a dependency"""
import time
import os
from pathlib import Path
from functools import cmp_to_key, lru_cache
from computation.execution import run_checked, AnalysisError
from database.query import query_versions_from_mongo
from logger.logger import log_debug

import semver
import requests


def get_candidate_versions(groupId, artifactId, original_version, whether_rq3=False):
    """
        main function to get all versions of a dependency to be computed
        Args:
            groupId (str): groupId of the dependency
            artifactId (str): artifactId of the dependency
            original_version (str): original version of the dependency
            whether_rq3 (bool): whether to compute the versions for RQ3, just compute MMP, MmP, mmP versions
    """
    # all_versions are version from new to old
    all_versions = get_versions(groupId, artifactId)
    # the version to be computed are the versions after the original version
    original_version_idx = find_original_version_idx(all_versions, original_version)
    if original_version_idx == -1:
        # print(f"Fail to find the original version {original_version} in {groupId}:{artifactId}")
        log_debug(f"Fail to find the original version {original_version} in {groupId}:{artifactId}")
        # just return the original version
        return [original_version]
    # exclude pre-release versions
    candidate_versions = []
    for version in all_versions[:original_version_idx]:
        upper_version = version.upper()
        if 'SNAPSHOT' in upper_version or 'ALPHA' in upper_version or 'BETA' in upper_version or 'RC' in upper_version:
            continue
        candidate_versions.append(version)
    if original_version not in candidate_versions:
        candidate_versions.append(original_version)
    if whether_rq3:
        candidate_versions = get_MMP_MmP_mmP_versions(original_version, candidate_versions)
    return candidate_versions

def get_MMP_MmP_mmP_versions(original_version:str, candidate_versions:list):
    """get the MMP, MmP, mmP versions of the original version"""
    original_major = original_version.split(".")[0]
    original_minor = original_version.split(".")[1] if len(original_version.split(".")) > 1 else 0
    resulting_versions = []
    MMP_version = ""
    mMP_version = ""
    mmP_version = ""
    for version in reversed(candidate_versions):
        # reversed: from old to new
        major = version.split(".")[0]
        minor = version.split(".")[1] if len(version.split(".")) > 1 else 0
        MMP_version = version
        if major == original_major:
            mMP_version = version
        if major == original_major and minor == original_minor:
            mmP_version = version    
    resulting_versions.append(MMP_version)
    resulting_versions.append(mMP_version)
    resulting_versions.append(mmP_version)
    return resulting_versions

def find_original_version_idx(all_versions, original_version):
    """find the index of the original version in all versions"""
    for idx, version in enumerate(all_versions):
        if version == original_version:
            return idx
    return -1

def fetch_versions(groupId, artifactId):
    """fetch all versions of the dependency
    deprecated: use mongodb instead"""
    # Fetch all versions(up to 200) of the dependency from Maven Central
    url = f"http://search.maven.org/solrsearch/select?q=g:{groupId}+AND+a:{artifactId}&core=gav&rows=200&wt=json"
    all_versions = []
    try:
        response = get_resource_with_retry(url)
        if response:
            data = response.json()

            all_versions = []
            if 'docs' in data['response']:
                for doc in data['response']['docs']:
                    if 'timestamp' in doc:
                        all_versions.append({
                            'version': doc['v'],
                            'date': doc['timestamp']
                        })
    except Exception as e:
        print(f"Fail to handle {groupId}:{artifactId}, reason:{e}")

    # Sort versions using a custom comparison function
    all_versions = sort_versions(all_versions)

    # the versions in all_versions have been sorted by Maven Central
    # only return the version string
    all_versions = [version['version'] for version in all_versions]
    return all_versions

def get_versions(groupId, artifactId):
    """get all versions of an artifact"""
    all_versions = query_versions_from_mongo(groupId, artifactId)

    # Sort versions using a custom comparison function
    all_versions = sort_versions(all_versions)

    # the versions in all_versions have been sorted
    # only return the version string
    all_versions = [version['version'] for version in all_versions]
    return all_versions

@lru_cache(maxsize=256)
def _maven_order(versions):
    """Sort a batch using the bundled Maven 3.6.2 ComparableVersion class."""
    root = Path(__file__).resolve().parents[1]
    jar = root / 'utils/revapi-0.12.0/lib/maven-artifact-3.6.2.jar'
    helper = root / 'utils/SortVersions.java'
    if any(not v or '\n' in v or '\r' in v for v in versions):
        raise ValueError('Versions must be nonempty, single-line strings')
    if not versions:
        return ()
    output = run_checked(['java', '--class-path', str(jar), str(helper)],
                         input='\n'.join(versions) + '\n', timeout=60)
    ordered = tuple(output.splitlines())
    if sorted(ordered) != sorted(versions):
        raise AnalysisError('Maven version sorter returned incomplete output')
    return ordered


def sort_versions(records, policy=None):
    """Newest first; publication dates do not influence Maven ordering.

    legacy preserves the artifact comparator for comparison only. It retains
    its original non-transitive ordering and is not a correctness fix.
    """
    policy = policy or os.environ.get('DEPUPDATER_VERSION_ORDER', 'maven')
    if policy == 'legacy':
        return sorted(records, key=cmp_to_key(legacy_version_comparator))
    if policy != 'maven':
        raise ValueError(f'Unknown version order: {policy}')
    order = _maven_order(tuple(sorted({r['version'] for r in records})))
    rank = {version: index for index, version in enumerate(order)}
    return sorted(records, key=lambda r: rank[r['version']])


def version_comparator(a, b):
    """Deterministic Maven comparison; production sorting uses one batch call."""
    if a['version'] == b['version']:
        return 0
    order = _maven_order(tuple(sorted((a['version'], b['version']))))
    return -1 if order[0] == a['version'] else 1


def legacy_version_comparator(a, b):
    """Try to parse versions as SemVer and sort by SemVer if possible, otherwise sort by date
    arrange versions in descending order
    """
    try:
        a_semver = semver.VersionInfo.parse(a['version'])
        a_is_semver = True
    except ValueError:
        a_semver = None
        a_is_semver = False

    try:
        b_semver = semver.VersionInfo.parse(b['version'])
        b_is_semver = True
    except ValueError:
        b_semver = None
        b_is_semver = False

    # If both are SemVer compliant, sort by SemVer
    if a_is_semver and b_is_semver:
        if a_semver < b_semver:
            return 1
        elif a_semver > b_semver:
            return -1
        else:
            return 0

    # If either is not SemVer compliant, sort by date
    if a['date'] < b['date']:
        return 1
    elif a['date'] > b['date']:
        return -1
    else:
        return 0


def get_resource_with_retry(url, params=None, max_retries=5, backoff_factor=0.3):
    """get a resource with retry mechanism"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} failed to get {url} :{e}")
            time.sleep(backoff_factor * (2 ** attempt))  # Exponential backoff
            if attempt == max_retries - 1:
                raise  # Re-raise the last exception if all retries fail
