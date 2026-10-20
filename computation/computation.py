"""get the newest compatible version of a dependency"""
import os
import concurrent.futures
import csv

from tqdm import tqdm
import pymaven
import constants
from constants import DOWNLOAD_ERROR_CSV
from computation.versions import get_candidate_versions
from computation.api import Api
from computation.revapi import Revapi
from database.query import query_to_get_jar_location, query_dependencies_from_mongo,\
    insert_dependencies_into_mongo
from preprocess.Restore import Restore
from update.updateDB import populate_dep
from logger.logger import log_debug
class Computation:
    def __init__(self, cur_node:dict, graph:list, repo_name:str, relative_path_to_module:str,\
            local_dep_jar:list):
        """
        Args:
            cur_node : the dependency to be computed
            graph : the dependency graph
            local_dep_jar: a list of gav of local deps
        """
        self.cur_node = cur_node
        self.graph = graph
        self.repo_name = repo_name
        self.relative_path_to_module = relative_path_to_module
        self.local_dep_jar = local_dep_jar
        # method_caller_callee_pair and type_caller_callee_pair are used to compare with the Revapi result
        # these two list are got by get_entry_points_and_caller method
        # self.method_entry_points = []
        # self.type_entry_points = []
        self.api_entry_points = []

    def get_old_deps(self):
        """get the old dependencies of the current dependency
        just return groupId and artifactId of the old dependencies
        """
        old_deps = []
        for dep in self.graph:
            dependents = dep['Dependents']
            for dependent in dependents:
                if dependent['GroupId'] == self.cur_node['GroupId'] and dependent['ArtifactId'] == self.cur_node['ArtifactId']:
                    old_deps.append({'GroupId': dep['GroupId'], 'ArtifactId': dep['ArtifactId']})
        return old_deps

    def compute_best_version(self):
        """main function to compute the newest compatible version of the dependency
        Returns:
            best_version (str) : best version
            local_dep_flag (bool) : whether cur_node is a local dep
        """
        # get all versions
        # if self.cur_node has Versions, then use it, else fetch from maven repository
        local_dep_flag = False
        if f"{self.cur_node['GroupId']}:{self.cur_node['ArtifactId']}:{self.cur_node['Original_Version']}"\
                in self.local_dep_jar:
                    local_dep_flag = True
        if 'Versions' in self.cur_node:
            # the versions are already fetched
            all_versions = [Version['version'] for Version in self.cur_node['Versions']]
        else:
            if local_dep_flag:
                # current node is a local dep
                all_versions = [self.cur_node['Original_Version']]
            else:
                all_versions = get_candidate_versions(self.cur_node['GroupId'], self.cur_node['ArtifactId'], self.cur_node['Original_Version'])

        if not local_dep_flag:
            # initialize breaking_reason of all versions(some versions may not be computed as software debloating)
            self.initialize_breaking_reason(all_versions)

            # method to judge versions' compatibility
            self.filter_version_by_compatibility(all_versions)

            # find the newest compatible version from self.cur_node['Versions']
            best_version = self.get_best_version(self.cur_node['Versions'])
        else:
            best_version = self.cur_node['Original_Version']

        # record the best version in self.cur_node
        self.cur_node['Best_Version'] = best_version

        return best_version, local_dep_flag

    def initialize_breaking_reason(self, all_versions:list):
        """initialize breaking_reason of all versions to exclude the versions that are not software debloating
        Args:
            all_versions (list) : all versions of the dependency
        """
        self.cur_node['Versions'] = []
        # original_version = self.cur_node['Original_Version']
        # original_dep_count = self.count_amount_of_a_version(self.cur_node['GroupId'], self.cur_node['ArtifactId'], original_version)
        for version in all_versions:
            self.cur_node['Versions'].append({'version': version, 'breaking_reason':[]})

        # # consider debloating to filter versions
        # for version in all_versions:
        #     if version == original_version:
        #         self.cur_node['Versions'].append({'version': version, 'breaking_reason':[]})
        #         break
        #     dep_count, dependencies = self.count_amount_of_a_version(self.cur_node['GroupId'], \
        #         self.cur_node['ArtifactId'], version)
        #     if dep_count > original_dep_count:
        #         # not following software debloating as the number of direct dependencies has exceeded the original number
        #         self.cur_node['Versions'].append({'version': version, 'breaking_reason':['software debloating']})
        #     else:
        #         # consider the new dependencies introduced globally first
        #         graph_set = self.graph_to_set()
        #         new_dict = {}
        #         for dependency in dependencies:
        #             gav = dependency['dep']
        #             g,a,v = gav.split(':',2)
        #             if f'{g}:{a}' not in graph_set:
        #                 new_dict[f"{g}:{a}"] = v

        #         self.count_dependencies_recursive(graph_set, new_dict, dep_count)
        #         if dep_count > original_dep_count:
        #             self.cur_node['Versions'].append({'version': version, 'breaking_reason':['software debloating']})
        #         else:
        #             self.cur_node['Versions'].append({'version': version, 'breaking_reason':[]})

        self.filter_version_by_debloating()

    def filter_version_by_debloating(self):
        """filter the versions not follow software debloating"""
        original_version = self.cur_node['Original_Version']
        original_dep_count, original_dependencies = self.count_amount_of_a_version(self.cur_node['GroupId'], self.cur_node['ArtifactId'], original_version)
        for Version in self.cur_node['Versions']:
            version = Version['version']
            if version == original_version:
                # original_version is the last version
                break
            dep_count, dependencies = self.count_amount_of_a_version(self.cur_node['GroupId'], \
                self.cur_node['ArtifactId'], version)
            if dep_count > original_dep_count:
                # not following software debloating as the number of direct dependencies has exceeded the original number
                Version['breaking_reason'] = ['software debloating']
            else:
                # consider the new dependencies introduced globally first
                graph_set = self.graph_to_set()
                new_dict = {}
                for dependency in dependencies:
                    gav = dependency['dep']
                    g,a,v = gav.split(':',2)
                    if f'{g}:{a}' not in graph_set:
                        new_dict[f"{g}:{a}"] = v
                # minus the new deps as they will be added in count_dependencies_recursive
                dep_count -= len(new_dict)
                dep_count = self.count_dependencies_recursive(graph_set, new_dict, dep_count)
                if dep_count > original_dep_count:
                    Version['breaking_reason'] = ['software debloating']

    def filter_version_by_compatibility(self, all_versions:list):
        """method to judge versions' compatibility"""
        # get entry points and caller of the dependency
        for dependent in self.cur_node['Dependents']:
            # handle the version range defined by dependant
            if '[' in dependent['Define_Version'] or ']' in dependent['Define_Version'] \
                or '(' in dependent['Define_Version'] or ')' in dependent['Define_Version']:
                # version range
                for version in all_versions:
                    if self.check_in_range(version, dependent['Define_Version']):
                        dependent['Define_Version'] = version
                        break
            self.get_entry_points_and_caller(dependent['GroupId'], dependent['ArtifactId'], dependent['Version'], dependent['Define_Version'])

        # get gav of client
        client_gav = self.get_client_gav()

        # compute the newest compatible version
        # use process pool to compute the versions in all_versions in parallel
        # I'll compute all versions, finally choose the newest compatible version
        
        # num_workers = os.cpu_count() // 2
        # num_workers = 2 # memory is limited, so use 2 workers for testing
        # num_workers = 3 # memory is limited, so use 3 workers for testing
        num_workers = 60

        # # clear breaking_reason of all versions except the version not following software debloating
        # for version_dict in self.cur_node['Versions']:
        #     if version_dict['breaking_reason'] != ['software debloating']:
        #         version_dict['breaking_reason'] = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            # initializing the progress bar
            pbar = tqdm(total=len(all_versions), desc=f"analyze versions of {self.cur_node['GroupId']}:{self.cur_node['ArtifactId']}", position=0, leave=True)
            # submit the tasks to the executor
            tasks = {executor.submit(self.version_compatibility_checker, version, client_gav): version for version in all_versions}

            for breaking_reason in concurrent.futures.as_completed(tasks):
                # update the breaking_reason of the version in self.cur_node['Versions']
                for version_dict in self.cur_node['Versions']:
                    if version_dict['version'] == breaking_reason.result()['version']:
                        # print(f'update breaking_reason of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]}:{version_dict["version"]}')
                        version_dict['breaking_reason'] = breaking_reason.result()['breaking_reason']
                        break
                # update the progress bar
                pbar.update(1)
        pbar.close()
        
        # # serial to debug
        # pbar = tqdm(total=len(all_versions), desc=f"analyze versions of {self.cur_node['GroupId']}:{self.cur_node['ArtifactId']}", position=0, leave=True)
        # for version in all_versions:
        #     breaking_reason = self.version_compatibility_checker(version, client_gav)
        #     for version_dict in self.cur_node['Versions']:
        #         if version_dict['version'] == breaking_reason['version']:
        #             version_dict['breaking_reason'] = breaking_reason['breaking_reason']
        #             break
        #     pbar.update(1)
        # pbar.close()

    def graph_to_set(self):
        """transform the node in self.graph into g:a set"""
        graph_set = set()
        graph_set.update([f"{node['GroupId']}:{node['ArtifactId']}" for node in self.graph])
        return graph_set

    @staticmethod
    def count_dependencies_recursive(graph_set:set, new_dict:dict, dep_count:int):
        """count the new transitive dependencies as well
        Args:
            graph_set (set): the g:a set of current graph;
            new_dict (list): a dict of the new dep and the map is g:a -> v
            dep_count (int): current total count
        """
        # # debug
        # print('--------')
        # print(new_dict)
        # print(dep_count)
        # print('--------')
        for ga, version in new_dict.items():
            # note: the nodes in new_dict may not be the new node as they may be added in recursive process
            if ga not in graph_set:
                # # debug
                # print(f'{ga}:{version}')

                # ga is a new dep will be introduced
                graph_set.add(ga)
                dep_count += 1
                gid, aid = ga.split(':')
                _ , dependencies = Computation.count_amount_of_a_version(gid, aid, version)
                
                # # debug
                # print(dependencies)

                # dependencies is the direct dependencies of ga
                transitive_new_dict = {}
                for dependency in dependencies:
                    gav = dependency['dep']
                    g,a,v = gav.split(':',2)
                    if f'{g}:{a}' not in graph_set:
                        transitive_new_dict[f"{g}:{a}"] = v
                dep_count = Computation.count_dependencies_recursive(graph_set, transitive_new_dict, dep_count)
        return dep_count

    @staticmethod
    def count_amount_of_a_version(groupId:str, artifactId:str, version:str):
        """count the amount of the version in the graph
        just count the compile or runtime dependencies
        Returns:
            count (int): number of the actual direct dependencies
            actual_dependencies (list): list of dicts containing the actual direct dependencies
        """
        count = 0
        dependencies = query_dependencies_from_mongo(groupId, artifactId, version)
        if dependencies is None:
            # not in db yet
            dependencies = populate_dep(groupId, artifactId, version)
            insert_dependencies_into_mongo(groupId, artifactId, version, dependencies)
        actual_dependencies = []
        for dependency in dependencies:
            if dependency['isoptional'] == 'false' and (dependency['dScope'] == 'compile' or dependency['dScope'] == 'runtime'):
                count += 1
                actual_dependencies.append(dependency)
        return count, actual_dependencies

    @staticmethod
    def check_in_range(version, range):
        version_range = pymaven.versioning.VersionRange(range)
        return version in version_range

    def get_client_gav(self):
        """get the groupId, artifactId and version of the client"""
        for dep in self.graph:
            if dep['Depth'] == 0:
                return f"{dep['GroupId']}:{dep['ArtifactId']}:{dep['Original_Version']}"

    def get_best_version(self, Versions:list):
        """find the newest compatible version from Versions"""
        # Iterate to find the first version without breaking_reason(newest version is the first version)
        # for version in reversed(Versions):
        print(f'every version of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]} has been analyzed!')
        for version in Versions:
            if not version['breaking_reason']:
                print(f'best version of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]} is {version["version"]}')
                return version['version']
        # all version have breaking_reason, which is not expected, then use the original version
        # print(f"Fail to find the newest compatible version of {self.cur_node['GroupId']}:{self.cur_node['ArtifactId']}")
        log_debug(f"Fail to find the newest compatible version of {self.cur_node['GroupId']}:{self.cur_node['ArtifactId']}, so use the original version!")
        # exit()
        return self.cur_node['Original_Version']

    def version_compatibility_checker(self, version:str, client_gav:str):
        """check if the version is compatible 
        Return:
            version (dict) : {'version': version, 'breaking_reason': breaking_reason}\n
            if breaking_reason is empty, then the version is compatible\n
            this dict is extracted from the self.cur_node['Versions'], and will be updated in the self.cur_node['Versions']\n
            as well as the graph
        """
        # find the dict in self.cur_node['Versions'] with the version
        for version_dict in self.cur_node['Versions']:
            if version_dict['version'] == version:
                ret_dict = version_dict
                break

        if ret_dict['breaking_reason'] == ['software debloating']:
            # the version is not following software debloating, which is the primary objective
            # so just return the breaking_reason
            return ret_dict

        # traverse all dependents of the current dependency
        for entry_point in self.api_entry_points:
            dependent_gav = entry_point['dependent']
            if client_gav != dependent_gav:
                depended_by_client = False
            else:
                depended_by_client = True

            baselineVersion = entry_point['baselineVersion']
            if baselineVersion == version:
                continue
            if 'methods' not in entry_point and 'types' not in entry_point:
                # use semantic versioning to judge compatibility
                if not Computation.semantic_versioning(baselineVersion, version):
                    # incompatible by semantic versioning
                    breaking_reason = f"incompatible with {dependent_gav} by semantic versioning"
                    ret_dict['breaking_reason'].append(breaking_reason)
                continue

            # judge compatibility by api matching
            old_jar = query_to_get_jar_location(self.cur_node['GroupId'], self.cur_node['ArtifactId'], baselineVersion)
            flag = Restore.get_dep_jar(self.cur_node['GroupId'], self.cur_node['ArtifactId'], baselineVersion)
            if not flag:
                self.record_download_failed(self.cur_node['GroupId'], self.cur_node['ArtifactId'], baselineVersion, self.repo_name, self.relative_path_to_module)
            new_jar = query_to_get_jar_location(self.cur_node['GroupId'], self.cur_node['ArtifactId'], version)
            flag = Restore.get_dep_jar(self.cur_node['GroupId'], self.cur_node['ArtifactId'], version)
            if not flag:
                self.record_download_failed(self.cur_node['GroupId'], self.cur_node['ArtifactId'], version, self.repo_name, self.relative_path_to_module)
                # the jar of the version is not downloaded, so just return the breaking_reason
                ret_dict['breaking_reason'] = ['jar is unavailable']
                return ret_dict

            revapi = Revapi(old_jar, new_jar)
            # print(f'extract bc method and type of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]}:{baselineVersion} -> {version} by Revapi')
            bin_bc_method, bin_bc_type, src_bc_method, src_bc_type = revapi.bc_api(self.cur_node['GroupId'], self.cur_node['ArtifactId'], baselineVersion, version)
            # binary compatibility must be considered
            bc_method = bin_bc_method
            bc_type = bin_bc_type
            if depended_by_client:
                # judge source compatibility as well
                Computation.merge_bc_api_dict(bc_method, src_bc_method)
                Computation.merge_bc_api_dict(bc_type, src_bc_type)

            client_impacting_methods = self.intersect_api(bc_method, entry_point['methods'])
            client_impacting_types = self.intersect_api(bc_type, entry_point['types'])
            for client_impacting_method in client_impacting_methods:
                breaking_reason = {
                    'api': client_impacting_method,
                    'dependent': dependent_gav,
                    'callers': [caller for caller in entry_point['methods'][client_impacting_method]],
                    'record': bc_method[client_impacting_method]
                }
                ret_dict['breaking_reason'].append(breaking_reason)
            for client_impacting_type in client_impacting_types:
                breaking_reason = {
                    'api': client_impacting_type,
                    'dependent': dependent_gav,
                    'callers': [caller for caller in entry_point['types'][client_impacting_type]],
                    'record': bc_type[client_impacting_type]
                }
                ret_dict['breaking_reason'].append(breaking_reason)

        return ret_dict

    @staticmethod
    def semantic_versioning(baselineVersion:str, version:str):
        """judge whether version is compatible baselineVersion by semver
        Args:
            baselineVersion : the baseline version
            version : the version to be judged
        Return:
            compatible (bool): True or False
        """
        def extract_major_version(version:str):
            return version.split('.')[0]
        baseMajor = extract_major_version(baselineVersion)
        versionMajor = extract_major_version(version)
        if baseMajor == versionMajor:
            return True
        return False

    @staticmethod
    def merge_bc_api_dict(target, source):
        """merge source to target
        Args:
            target : the dict to be merged, key is bc api while value is a list of Revapi records
            source : the dict to merge, key is bc api while value is a list of Revapi records
        """
        for key, value in source.items():
            if key in target:
                target[key].extend(record for record in value if record not in target[key])
            else:
                target[key] = value

    def return_entry_points(self):
        """return entry points api for validating by Japicmp afterwards"""
        method_entry_points = []
        type_entry_points = []
        for entry_point in self.api_entry_points:
            method_entry_points.append({
                'dependent': entry_point['dependent'],
                'baselineVersion': entry_point['baselineVersion'],
                'api': entry_point['methods']
            })
            type_entry_points.append({
                'dependent': entry_point['dependent'],
                'baselineVersion': entry_point['baselineVersion'],
                'api': entry_point['types']
            })
        return method_entry_points, type_entry_points
        # return self.method_entry_points, self.type_entry_points

    @staticmethod
    def intersect_api(api1:dict, api2:dict):
        """intersect two api dicts to get the common api
        Args:
            api1 : the first api dict, its key is an api
            api2 : the second api dict, its key is an api
        """
        common_apis = set(api1.keys() & api2.keys())
        return common_apis

    def get_and_record_reachable_api(self, best_version = None):
        """record all reachable caller_callee_pairs of the dependency at the best version\n"""
        if best_version is None:
            # if best_version is None , then it is the client, and all methods are reachable
            # its actual best_version is the Original_Version
            # note : this branch is executed only once
            client_groupId = self.cur_node['GroupId']
            client_artifactId = self.cur_node['ArtifactId']
            client_api = Api(client_groupId, client_artifactId, self.cur_node['Original_Version'])
            client_cg = client_api.get_cg()
            client_cg_dict = Api.parse_call_relations(client_cg)
            self.record_reachable_apis(client_cg_dict, 'methods')
            client_dg = client_api.get_type_dg()
            client_dg_dict = Api.parse_call_relations(client_dg)
            self.record_reachable_apis(client_dg_dict, 'types')
        else:
            best_version_api = Api(self.cur_node['GroupId'], self.cur_node['ArtifactId'], best_version)
            best_version_cg = best_version_api.get_cg()
            entry_point_methods = self.get_entry_points_set('methods')
            method_call_relations = Api.parse_call_relations(best_version_cg)
            reachable_method_pairs = Api.find_reachable_calls(entry_point_methods, method_call_relations)
            self.record_reachable_apis(reachable_method_pairs, 'methods')
            entry_point_types = self.get_entry_points_set('types')
            best_version_dg = best_version_api.get_type_dg()
            type_call_relations = Api.parse_call_relations(best_version_dg)
            reachable_type_pairs = Api.find_reachable_calls(entry_point_types, type_call_relations)
            self.record_reachable_apis(reachable_type_pairs, 'types')

    def get_entry_points_and_caller(self, dependent_groupId:str, dependent_artifactId:str, dependent_version:str, defined_version:str):
        """get the entry points in the dependency and the corresponding caller in the dependent\n
        dict in reachable_method_callee or reachable_type_callee is like:\n
            {
                'dependent': dependent_groupId:dependent_artifactId:dependent_version,
                'baselineVerison': defined_version,
                'api': {
                    callee : the set of corresponding callers
                }
            }
        the callee is the entry point; 'api' is a dict of callee -> set of callers
        """
        defined_version_api = Api(self.cur_node['GroupId'], self.cur_node['ArtifactId'], defined_version)
        dependent_reachable_methods = self.read_reachable_apis(dependent_groupId, dependent_artifactId, 'methods')
        dependent_reachable_types = self.read_reachable_apis(dependent_groupId, dependent_artifactId, 'types')

        # defined_version_cg = defined_version_api.get_cg()
        # all_methods = defined_version_api.extract_methods_from_cg(defined_version_cg)
        all_methods, method_flag = defined_version_api.get_methods()
        all_types, type_flag = defined_version_api.get_types()
        if not method_flag and not type_flag:
            # judge compatibility by semantic versioning afterwards
            entry_point_dict = {
                'dependent': f'{dependent_groupId}:{dependent_artifactId}:{dependent_version}',
                'baselineVersion': defined_version
            }
        else:
            # judge compatibility by api matching
            # match method
            method_entry_point_dict = {}
            matching_method_pairs = Api.find_matching_relations(dependent_reachable_methods, all_methods)
            for pair in matching_method_pairs:
                method_entry_point_dict.setdefault(pair[1], set()).add(pair[0])
            # match type
            type_entry_point_dict = {}
            matching_type_pairs = Api.find_matching_relations(dependent_reachable_types, all_types)
            for pair in matching_type_pairs:
                type_entry_point_dict.setdefault(pair[1], set()).add(pair[0])
            # record the entry points and caller
            entry_point_dict = {
                'dependent': f'{dependent_groupId}:{dependent_artifactId}:{dependent_version}',
                'baselineVersion': defined_version,
                'methods': method_entry_point_dict,
                'types': type_entry_point_dict
            }

        self.api_entry_points.append(entry_point_dict)

    def get_entry_points_set(self, api_type:str):
        """get the set of entry points of the dependency for reachable api"""
        entry_points = set()
        if api_type == 'methods':
            for method_entry_point in self.api_entry_points:
                if 'methods' in method_entry_point:
                    entry_points.update(method_entry_point['methods'].keys())
            return entry_points
        elif api_type == 'types':
            for type_entry_point in self.api_entry_points:
                if 'types' in type_entry_point:
                    entry_points.update(type_entry_point['types'].keys())
            return entry_points

    def create_folder(self, folder:str):
        """create a folder if not exists"""
        if not os.path.exists(folder):
            os.makedirs(folder)
    
    def record_reachable_apis(self, reachable_apis:set , apis_type:str):
        """record the reachable apis (methods or types) of the dependency in this module\n
        usually record the reachable apis of this dependency at the best version
        Args:
            reachable_apis (set) : A set of (caller,callee) tuples\n
            apis_type (str) : 'methods' or 'types'
        """
        module_folder = os.path.join(constants.REACHABLE_API_DIR, self.repo_name, self.relative_path_to_module, f'{self.cur_node["GroupId"]}', f'{self.cur_node["ArtifactId"]}')
        self.create_folder(module_folder)
        if apis_type == 'methods':
            module_file = os.path.join(module_folder, 'methods.txt')
        elif apis_type == 'types':
            module_file = os.path.join(module_folder, 'types.txt')
        else:
            raise ValueError("Invalid apis_type. Must be 'methods' or 'types'.")
        # write the reachable apis into the file
        with open(module_file, 'w', encoding='utf-8') as f:
            for caller, callees in reachable_apis.items():
                for callee in callees:
                    f.write(f'{caller} -> {callee}\n')

    def read_reachable_apis(self, group_id:str, artifact_id:str, apis_type:str):
        """read the reachable caller_callee_pairs (methods or types) of the dependency in this module\n
        usually read the reachable apis of the dependent of cur_node
        Return:
            reachable_apis : A dictionary of caller -> callees relations tuple\n
            key: caller, value: a set of the corresponding callees\n
        """
        module_folder = os.path.join(constants.REACHABLE_API_DIR, self.repo_name, self.relative_path_to_module, group_id, artifact_id)
        if apis_type == 'methods':
            module_file = os.path.join(module_folder, 'methods.txt')
        elif apis_type == 'types':
            module_file = os.path.join(module_folder, 'types.txt')
        else:
            raise ValueError("Invalid apis_type. Must be 'methods' or 'types'.")
        # read the reachable apis from the file
        with open(module_file, 'r', encoding='utf-8') as f:
            call_relations_str = f.read()
        reachable_apis = Api.parse_call_relations(call_relations_str)
        return reachable_apis

    @staticmethod
    def record_download_failed(group_id:str, artifact_id:str, version:str, repo_name:str, relative_path_to_module:str):
        """record the download failed of the jar"""
        download_error_csv = DOWNLOAD_ERROR_CSV
        with open(download_error_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([group_id, artifact_id, version, repo_name, relative_path_to_module])

    def judge_dependent_empty(self):
        """judge if the dependent is empty"""
        if not self.cur_node['Dependents']:
            return True
        return False
