"""class to compute technical lag"""
import json

class TechLag:
    def __init__(self, json_path):
        """Args:
        json_path: str, path to the json file containing the versions of the deps in the module
        """
        self.json_path = json_path
        self.deps = self.extract_deps()
        self.current_lag = [0,0,0,0,0,0,0,0,0,0,0,0]
        self.compute_current_lag()

    def extract_deps(self):
        """extract dep from json"""
        with open(self.json_path, 'r') as f:
            deps = json.load(f)
        ret_deps = []
        for dep in deps:
            if dep['Best_Version'] and dep['Dependents']:
                # consider the deps that are in graph actually
                # note: the deps that are in graph but has no best version all have classifier
                ret_deps.append(dep)
        return ret_deps

    def compute_current_lag(self):
        """compute the current lag of the module"""
        for dep in self.deps:
            if dep['Depth'] == 0:
                continue
            if 'Versions' not in dep or 'Best_Version' not in dep:
                # if the dep has no versions or best version, we skip it
                continue
            all_versions = dep['Versions']
            best_version = dep['Best_Version']
            idx = self.find_idx(all_versions, best_version)
            if idx is None:
                # if the version is not found, we skip it
                # this is the case when the best version is not in the versions list
                continue
            self.current_lag[0] += idx
            if dep['Depth'] <= 10:
                self.current_lag[dep['Depth']] += idx
            else:
                self.current_lag[11] += idx

    def find_idx(self, all_versions:list, version:str):
        """find the index of the version in all versions"""
        for idx, v in enumerate(all_versions):
            if v['version'] == version:
                return idx
        return None

    def compute_reduced_semver_lag(self):
        """compute the reduced semver lag of the module"""
        major_reduced_lag = 0
        minor_reduced_lag = 0
        patch_reduced_lag = 0
        for dep in self.deps:
            if dep['Depth'] == 0:
                continue
            if 'Versions' not in dep or 'Best_Version' not in dep:
                # if the dep has no versions or best version, we skip it
                continue
            all_versions = dep['Versions']
            best_version = dep['Best_Version']
            idx = self.find_idx(all_versions, best_version)
            if idx is None:
                # if the version is not found, we skip it
                # this is the case when the best version is not in the versions list
                continue
            # compute the semver lag
            if idx == 0:
                considered_versions = all_versions[-1::-1]
            else:
                considered_versions = all_versions[-1:idx-1:-1]
            # print(f"considered_versions: {considered_versions}")
            original_version = considered_versions[0]['version']
            major_version = original_version.split(".")[0]
            minor_version = original_version.split(".")[1] if len(original_version.split(".")) > 1 else '0'
            patch_version = original_version.split(".")[2] if len(original_version.split(".")) > 2 else '0'
            for version in considered_versions:
                version_number = version['version']
                # print(f"version_number: {version_number}")
                major = version_number.split(".")[0]
                # print(f"major: {major}")
                minor = version_number.split(".")[1] if len(version_number.split(".")) > 1 else '0'
                # print(f"minor: {minor}")
                patch = version_number.split(".")[2] if len(version_number.split(".")) > 2 else '0'
                # print(f"patch: {patch}")
                if major != major_version:
                    major_reduced_lag += 1
                if minor != minor_version:
                    minor_reduced_lag += 1
                if patch != patch_version:
                    patch_reduced_lag += 1
                major_version = major
                minor_version = minor
                patch_version = patch
        return [major_reduced_lag, minor_reduced_lag, patch_reduced_lag]
    