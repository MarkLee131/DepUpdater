"""main file for traversing in the dependency graph"""
import os
import json
from collections import deque
import subprocess

from depupdater.analysis.candidates import Computation
from depupdater.analysis.validation import Validation
from depupdater.graph.update import Update
from depupdater.log import log_debug
import depupdater.paths as constants
class Traverse:
    def __init__(self, json_path:str, path_to_project_folder:str, relative_path_to_module:str):
        """
        Args:
            json_path (str): path to json
            path_to_project_folder (str): path to root dir
            relative_path_to_module (str): relative path to module
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            self.graph = json.load(f)
        self.json_path = json_path
        self.queue = deque()
        self.repo_name = os.path.basename(path_to_project_folder)
        self.path_to_project_folder = path_to_project_folder
        self.relative_path_to_module = relative_path_to_module
        self.init_queue()
        self.compute_api_of_client()

    def init_queue(self):
        """put all direct dependencies of client jar into queue
        note: only the dependencies have only one dependent(client) are put into queue
        """
        for dep in self.graph:
            if dep['Depth'] == 1 and len(dep['Dependents']) == 1:
                log_debug(f"{dep['GroupId']}:{dep['ArtifactId']} enqueue.")
                self.queue.append(dep)

    def compute_api_of_client(self):
        """get the methods and types of client jar first"""
        for dep in self.graph:
            if dep['Depth'] == 0:
                client_com = Computation(dep, self.graph, self.repo_name, self.relative_path_to_module, None)
                client_com.get_and_record_reachable_api()
                dep['Best_Version'] = dep['Original_Version']
                break

    def traverse(self, local_dep_jar:list):
        """traverse the graph to compute the newest compatible version of each dependency in order
        Args:
            local_dep_jar (list): a list of gav of local deps
        """
        # back up the original pom.xml
        pom_path = os.path.join(self.path_to_project_folder, self.relative_path_to_module, 'pom.xml')
        original_pom_path = os.path.join(self.path_to_project_folder, self.relative_path_to_module, '_original_pom.xml')
        Validation.backup_pom(original_pom_path, pom_path)

        try:
            while self.queue:
                cur_dep = self.queue.popleft()

                # no need to compute client anymore
                if cur_dep['Depth'] == 0:
                    continue

                log_debug(f"Computing {cur_dep['GroupId']}:{cur_dep['ArtifactId']}")

                if cur_dep['Count'] >= 3:
                    # print(f"Dependency {cur_dep['GroupId']}:{cur_dep['ArtifactId']} has been computed for 3 times. Something may goes wrong.")
                    log_debug(f'=== Dependency {cur_dep["GroupId"]}:{cur_dep["ArtifactId"]} has been computed for {cur_dep["Count"]} times ===')
                    # exit(1)

                old_best_version = self.get_old_best_version(cur_dep)

                # find the newest compatible version of cur_dep,
                # and return its new dependencies and old dependencies to update the graph,
                # record the graph in version.json in real time
                # --> new_deps = compute_newest_version(cur_dep, self.graph, self.json_path)
                old_deps, local_dep_flag = self.compute_and_validate(cur_dep, local_dep_jar)
                cur_dep['Count'] += 1

                log_debug(f"{cur_dep['GroupId']}:{cur_dep['ArtifactId']} has been computed, best version is {cur_dep['Best_Version']}.")

                if not local_dep_flag:
                    # update the graph and queue,
                    # record the graph in version.json in real time
                    # --> update_graph(cur_dep, old_deps, new_deps, self.graph, self.queue, self.json_path)
                    up = Update(cur_dep, self.graph, self.queue, old_deps)
                    up.update(old_best_version)

            # recompile the project
            compile_flag = self.recompile()
            # test the project
            test_flag = self.test()
            return compile_flag, test_flag
        finally:
            # Preserve the candidate and restore even after analyzer/build failure.
            backed_up_pom_path = os.path.join(self.path_to_project_folder, self.relative_path_to_module, '_backed_up_pom.xml')
            Validation.restore_pom(original_pom_path, pom_path, backed_up_pom_path)


    def compute_and_validate(self, cur_dep:dict, local_dep_jar:list):
        """compute the newest compatible version of the dependency and validate it
        Args:
            cur_dep (dict): the dependency to be computed and validated
            local_dep_jar (list): a list of gav of local deps
        Returns:
            old_deps (list): the old dependencies of cur dep
            local_dep_flag (bool) : whether cur_dep is a local dep
        """
        com = Computation(cur_dep, self.graph, self.repo_name, self.relative_path_to_module, local_dep_jar)
        old_deps = com.get_old_deps()
        local_dep_flag = False
        # compute the newest compatible version of cur_dep
        best_version, local_dep_flag = com.compute_best_version()
        # method_entry_points, type_entry_points = com.return_entry_points()
        # # validate. If the actually best version is different from the best version got by tool, exit
        # self.validate(cur_dep, best_version, method_entry_points, type_entry_points)

        # change the pom.xml
        self.change_pom(cur_dep, best_version)
        com.get_and_record_reachable_api(best_version)
        cur_dep['Best_Version'] = best_version
        # #debug
        # print(self.graph)
        self.record_graph(self.graph, self.json_path)
        return old_deps, local_dep_flag

    def validate(self, cur_dep, best_version, method_entry_points, type_entry_points):
        """get the actually best version and compare it with the best version got by tool. If they are different, exit
        Args:
            cur_dep (dict): the dependency to be validated
            best_version (str): the best version got by tool
            method_entry_points (list): the entry points of methods(from computation phase)
            type_entry_points (list): the entry points of types(from computation phase)
        """
        val = Validation(self.path_to_project_folder, self.relative_path_to_module)
        group_id = cur_dep['GroupId']
        artifact_id = cur_dep['ArtifactId']
        versions = [version['version'] for version in cur_dep['Versions']]
        if cur_dep['Depth'] == 1:
            direct_or_transitive = 'direct'
        else:
            direct_or_transitive = 'transitive'
        val.validate(group_id, artifact_id, versions, best_version, method_entry_points, type_entry_points, direct_or_transitive)

    def change_pom(self, cur_dep, best_version):
        """
            change the pom.xml to the best version of the dependency
            by set the value of the property tag in pom.xml and add the property in the corresponding tag\
            in <dependencies> or <dependencyManagement>
        """
        val = Validation(self.path_to_project_folder, self.relative_path_to_module)
        group_id = cur_dep['GroupId']
        artifact_id = cur_dep['ArtifactId']
        property_tag_name = val.set_pom_property_value(group_id, artifact_id, best_version)
        # way1: set the direct dependencies in <dependencies> while transitive dependencies in <dependencyManagement>
        if cur_dep['Depth'] == 1:
            # direct dependency
            val.add_direct_dependency(group_id, artifact_id, property_tag_name)
        else:
            # transitive dependency
            val.add_transitive_dependency(group_id, artifact_id, property_tag_name)

        # way2: set all dependencies in <dependencies>
        # val.add_direct_dependency(group_id, artifact_id, property_tag_name)

    def _validate_build(self, goal):
        flags = ['-Dcheckstyle.skip=true', '-Denforcer.skip=true',
                 '-Dflatten.skip=true', '-Dspotless.check.skip=true']
        if goal == 'compile':
            flags.append('-Dmaven.test.skip=true')
        module_dir = os.path.join(self.path_to_project_folder, self.relative_path_to_module)
        result = subprocess.run(['mvn', *flags, goal], cwd=module_dir,
                                text=True, capture_output=True)
        if result.returncode != 0:
            result = subprocess.run(['mvn', *flags, '-pl', self.relative_path_to_module,
                                     '-am', goal], cwd=self.path_to_project_folder,
                                    text=True, capture_output=True)
        log = result.stdout + '\n' + result.stderr
        if goal == 'compile':
            self.store_compile_log(log)
        else:
            self.store_test_log(log)
        return result.returncode == 0

    def recompile(self):
        return self._validate_build('compile')

    def get_old_best_version(self, cur_dep):
        """get the old best version of the dependency"""
        if cur_dep['Count'] == 0:
            # the first time to compute the dependency
            return cur_dep['Original_Version']
        if cur_dep['Best_Version']:
            # the dependency has been computed before
            return cur_dep['Best_Version']
        # the dependency has been computed before, but the best version is cleared in update phase
        return None

    def store_compile_log(self, log:str):
        """store the compile log"""
        repo_name = os.path.basename(self.path_to_project_folder)
        log_folder = os.path.join(constants.VALIDATION_LOG_DIR, repo_name, self.relative_path_to_module)
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)
        # store the log
        log_path = os.path.join(log_folder, 'recompile.txt')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(log)

    def test(self):
        return self._validate_build('test')

    def store_test_log(self, log:str):
        """store the test log"""
        repo_name = os.path.basename(self.path_to_project_folder)
        log_folder = os.path.join(constants.VALIDATION_LOG_DIR, repo_name, self.relative_path_to_module)
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)
        # store the log
        log_path = os.path.join(log_folder, 'test.txt')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(log)

    @staticmethod
    def record_graph(graph, json_path):
        """record the graph in version.json"""
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(graph, f, ensure_ascii=False, indent=4)
