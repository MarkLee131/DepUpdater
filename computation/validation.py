"""all operations for validating the best version got by the computation module"""
import os
import subprocess
import json
import concurrent.futures
import time

from lxml import etree
from tqdm import tqdm

import constants
from computation.japicmp import Japicmp
from computation.computation import Computation
from preprocess.Restore import Restore
from database.query import query_to_get_jar_location
class Validation:
    def __init__(self, path_to_cloned_folder: str, relative_path_to_module: str) -> None:
        self.path_to_cloned_folder = path_to_cloned_folder
        self.repo_name = os.path.basename(path_to_cloned_folder)
        self.relative_path_to_module = relative_path_to_module
        self.pom_path = os.path.join(path_to_cloned_folder, relative_path_to_module, 'pom.xml')

    def validate(self, group_id: str, artifact_id: str, versions: list, best_version: str, method_entry_points: dict, \
        type_entry_points:dict, direct_or_transitive:str)->str:
        """main method: validating the best version of the dependency got by the computation module. If the best version is different from the actual best version, exit"""
        # get the actual best version
        actual_best_version = self.get_actual_best_version(group_id, artifact_id, versions, method_entry_points, type_entry_points, direct_or_transitive)
        if best_version != actual_best_version:
            print(f"Error: the best version of {group_id}:{artifact_id} got by tool is {best_version}, but the actual best version is {actual_best_version}")
            exit(1)


    @staticmethod
    def backup_pom(path_to_backed_up_pom: str, path_to_pom: str):
        """backup the pom.xml before validation phase
        path_to_pom -> path_to_backed_up_pom
        Args:
            path_to_backed_up_pom (str): the path to the backed up pom.xml
            path_to_pom (str): the path to the pom.xml
        """
        with open(path_to_pom, 'rb') as f:
            content = f.read()
        with open(path_to_backed_up_pom, 'wb') as f:
            f.write(content)

    @staticmethod
    def restore_pom(path_to_backed_up_pom: str, path_to_pom: str, path_to_validation_pom:str):
        """store the pom.xml and restore the original pom.xml after validation phase
        path_to_pom -> path_to_validation_pom ; path_to_backed_up_pom -> path_to_pom
        Args:
            path_to_backed_up_pom (str): the path to the original pom.xml(which is backed up before validation phase)
            path_to_pom (str): the path to the pom.xml
            path_to_validation_pom (str): the path to the pom.xml which is used for validation
        """
        try:
            with open(path_to_pom, 'rb') as f:
                content = f.read()
            with open(path_to_validation_pom, 'wb') as f:
                f.write(content)
        finally:
            # Restore even if preserving the candidate fails.
            with open(path_to_backed_up_pom, 'rb') as f:
                content = f.read()
            with open(path_to_pom, 'wb') as f:
                f.write(content)

    def get_actual_best_version(self, group_id: str, artifact_id: str, versions: list, method_entry_points: dict, \
        type_entry_points:dict, direct_or_transitive:str)->str:
        """validate project from the initial version to the newest version of the dependency
        to get the actual best version
        Args:
            versions (list): all versions of the dependency
            direct_or_transitive (str): 'direct' or 'transitive'
            method_entry_points (dict): the method entry points of the dependency(by the computation module;used to binary compatibility validation)
            type_entry_points (dict): the type entry points of the dependency(by the computation module;used to binary compatibility validation)
        Return:
            best_version (str): the actual best version of the dependency
        """
        # add the property about version of the dependency into the pom.xml
        # and set the version to the property
        # direct_dependency and transitive_dependency are not in the same format
        initial_version = versions[len(versions)-1]
        if direct_or_transitive == 'direct':
            property_tag_name = self.set_pom_property_value(group_id, artifact_id, initial_version)
            self.add_direct_dependency(group_id, artifact_id, property_tag_name)
        elif direct_or_transitive == 'transitive':
            property_tag_name = self.set_pom_property_value(group_id, artifact_id, initial_version)
            self.add_transitive_dependency(group_id, artifact_id, property_tag_name)

        # store the actual compatibility(source and binary) of each version
        # the key is the version, the value is a tuple of source compatibility and binary compatibility
        version_compatibility = {}
        for version in versions:
            # [0] is whether the version is source compatible
            # [1] is whether the version is binary compatible
            version_compatibility[version] = [False, False]
        # recompile the module from the initial version to the newest version of the dependency
        # to get the actual best version(source compatible)
        num_workers = os.cpu_count() // 4 * 3
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            # initializing the progress bar of recompilation
            pbar = tqdm(total=len(versions), desc=f'Recompiling versions of {group_id}:{artifact_id}', position=0, leave=True)
            # recompile the module with the specific version of the dependency
            source_validate_tasks = {executor.submit(self.recompile, property_tag_name, version): version for version in versions}

            # get the situation of the recompilation of each version, which is used to judge source compatibility
            for future in concurrent.futures.as_completed(source_validate_tasks):
                is_success,result,version = future.result()
                pbar.update(1)
                # store the result of the recompilation despite of the success or failure
                self.store_validation_log(group_id, artifact_id, version, result.stdout, 'recompile')
                # store the recompilation result in versions_compatibility
                version_compatibility[version][0] = is_success
            pbar.close()
            
            # initialize the progress bar of japicmp validation
            pbar = tqdm(total=len(versions), desc=f'Checking binary compatibility of {group_id}:{artifact_id}', position=0, leave=True)
            # check the binary compatibility of each version by japicmp
            binary_validate_tasks = {executor.submit(self.check_binary_compatibility, group_id, artifact_id, version, method_entry_points, type_entry_points): version for version in versions}

            # get the situation of the binary compatibility of each version, which is used to judge binary compatibility
            for future in concurrent.futures.as_completed(binary_validate_tasks):
                is_compatible, bin_bc_api, version = future.result()
                pbar.update(1)
                # store the binary BC api
                self.store_validation_log(group_id, artifact_id, version, bin_bc_api, 'binary_bc_api')
                # store the binary compatibility result in versions_compatibility
                version_compatibility[version][1] = is_compatible
            pbar.close()

        # get the actual newest , source compatible and binary compatible version
        # for version in reversed(version_compatibility.keys()):
        for version, compatibility in version_compatibility.items():
            if compatibility[0] and compatibility[1]:
                best_version = version
                break
        # store the actual best version in <properties>
        self.set_pom_property_value(group_id, artifact_id, best_version)


        return best_version

    def recompile(self, property_tag_name:str, version: str):
        """recompile the module with the specific version of the dependency to check the source compatibility
        Args:
            property_tag_name (str): the name of the property tag
            version (str): the version of the dependency
        Return:
            success (bool): whether the recompilation is successful
            result (str): the result of the recompilation
            version (str): the version of the dependency
        """
        # note: skip maven-enforcer-plugin , flatten-maven-plugin, maven-checkstyle-plugin
        command = f"cd {self.path_to_cloned_folder} && mvn -Dmaven.test.skip=true -Dcheckstyle.skip=true -Denforcer.skip=true -Dflatten.skip=true -D{property_tag_name}={version}  -pl {self.relative_path_to_module} compile -am"
        try:
            result = subprocess.run(command, shell=True, text=True, capture_output=True)
            if result.returncode != 0:
                return False, result, version
            return True, result, version
        except subprocess.SubprocessError as e:
            print(f"An error occured while executing the command: {e}")
            return False, result, version

    def check_binary_compatibility(self, groupId: str, artifactId: str, version: str, method_entry_points: dict, type_entry_points: dict):
        """check the binary compatibility of the version
        Returns:
            flag (bool): whether the version is binary compatible
            api_list (list): a list of dict. One dict represent one client impacting binary bc api\n
            {
                'api': client_impacting_api,
                'dependent: gav of the dependent jar,
                'callers': callers of the client impacting api in the dependent jar,
                'record': the bc record of the client impacting api in Japicmp report
            }\n
            version (str): the version under checking
        """
        api_list = []
        for method_entry_point in method_entry_points:
            dependent_gav = method_entry_point['dependent']
            baselineVersion = method_entry_point['baselineVersion']
            if baselineVersion == version:
                continue
            old_jar = query_to_get_jar_location(groupId, artifactId, baselineVersion)
            Restore.get_dep_jar(groupId, artifactId, baselineVersion)
            new_jar = query_to_get_jar_location(groupId, artifactId, version)
            Restore.get_dep_jar(groupId, artifactId, version)
            japicmp = Japicmp(old_jar, new_jar)
            print(f'extract bin bc api of {groupId}:{artifactId}:{baselineVersion} -> {version} by Japicmp')
            bin_bc_method, _ = japicmp.bc_api(groupId, artifactId, baselineVersion, version)

            print(f'validate bin method compatibility of {groupId}:{artifactId}:{baselineVersion} -> {version}')
            client_impacting_bin_methods = Computation.intersect_api(bin_bc_method, method_entry_point['api'])
            for client_impacting_bin_method in client_impacting_bin_methods:
                api_list.append({
                    'api': client_impacting_bin_method,
                    'dependent': dependent_gav,
                    'callers': [caller for caller in method_entry_point['api'][client_impacting_bin_method]],
                    'record': bin_bc_method[client_impacting_bin_method]
                })

        for type_entry_point in type_entry_points:
            dependent_gav = type_entry_point['dependent']
            baselineVersion = type_entry_point['baselineVersion']
            if baselineVersion == version:
                continue
            old_jar = query_to_get_jar_location(groupId, artifactId, baselineVersion)
            Restore.get_dep_jar(groupId, artifactId, baselineVersion)
            new_jar = query_to_get_jar_location(groupId, artifactId, version)
            Restore.get_dep_jar(groupId, artifactId, version)
            print(f'extract bin bc api of {groupId}:{artifactId}:{baselineVersion} -> {version} by Japicmp')
            japicmp = Japicmp(old_jar, new_jar)
            _, bin_bc_type = japicmp.bc_api(groupId, artifactId, baselineVersion, version)

            print(f'validate bin type compatibility of {groupId}:{artifactId}:{baselineVersion} -> {version}')
            client_impacting_bin_types = Computation.intersect_api(bin_bc_type, type_entry_point['api'])
            for client_impacting_bin_type in client_impacting_bin_types:
                api_list.append({
                    'api': client_impacting_bin_type,
                    'dependent': dependent_gav,
                    'callers': [caller for caller in type_entry_point['api'][client_impacting_bin_type]],
                    'record': bin_bc_type[client_impacting_bin_type]
                })

        if api_list:
            flag = False
        else:
            flag = True

        return flag, api_list, version

    def add_direct_dependency(self, group_id: str, artifact_id: str, property_tag_name:str):
        """add the direct dependency into the pom.xml
        update the <dependencies>
        Args:
            property_tag_name (str): the name of the property tag, from set_pom_property_value method
        Return:
            property_tag_name (str): the name of the property tag
        """
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(self.pom_path, parser)
        root = tree.getroot()
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}

        # Check if dependency exists and create/update as necessary
        dependencies = root.find('m:dependencies', namespaces=ns)
        if dependencies is None:
            dependencies = etree.SubElement(root, '{http://maven.apache.org/POM/4.0.0}dependencies')

        dependency = None
        for dep in dependencies.findall('m:dependency', namespaces=ns):
            g_id = dep.find('m:groupId', namespaces=ns)
            a_id = dep.find('m:artifactId', namespaces=ns)
            # if g_id is not None and a_id is not None and g_id.text == group_id and a_id.text == artifact_id:
            if g_id is not None and a_id is not None and a_id.text == artifact_id:
                # set version to the property
                if g_id.text == group_id or g_id.text == '${project.groupId}':
                    version = dep.find('m:version', namespaces=ns)
                    if version is None:
                        version = etree.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}version')
                    version.text = f'${{{property_tag_name}}}'
                    dependency = dep
                    break

        if dependency is None:
            dependency = etree.SubElement(dependencies, '{http://maven.apache.org/POM/4.0.0}dependency')
            gid = etree.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}groupId')
            gid.text = group_id
            aid = etree.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}artifactId')
            aid.text = artifact_id
            version = etree.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}version')
            version.text = f'${{{property_tag_name}}}'

        # write back
        tree.write(self.pom_path, pretty_print=True, xml_declaration=True, encoding='utf-8')
        
        # return the name of the property tag
        return property_tag_name

    def add_transitive_dependency(self, group_id: str, artifact_id: str, property_tag_name:str):
        """add the transitive dependency into the pom.xml
        update the <dependencyManagement>;
        Args:
            property_tag_name (str): the name of the property tag, from set_pom_property_value method
        Return:
            property_tag_name (str): the name of the property tag
        """
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(self.pom_path, parser)
        root = tree.getroot()
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        
        # Check if dependency exists and create/update as necessary
        dependencyManagement = root.find('m:dependencyManagement', namespaces=ns)
        if dependencyManagement is None:
            dependencyManagement = etree.SubElement(root, '{http://maven.apache.org/POM/4.0.0}dependencyManagement')
            
        dependencies = dependencyManagement.find('m:dependencies', namespaces=ns)
        if dependencies is None:
            dependencies = etree.SubElement(dependencyManagement, '{http://maven.apache.org/POM/4.0.0}dependencies')

        dependency = None
        for dep in dependencies.findall('m:dependency', namespaces=ns):
            g_id = dep.find('m:groupId', namespaces=ns)
            a_id = dep.find('m:artifactId', namespaces=ns)
            # if g_id is not None and a_id is not None and g_id.text == group_id and a_id.text == artifact_id:
            if g_id is not None and a_id is not None and a_id.text == artifact_id:
                # set version to the property
                if g_id.text == group_id or g_id.text == '${project.groupId}':
                    version = dep.find('m:version', namespaces=ns)
                    if version is None:
                        version = etree.SubElement(dep, '{http://maven.apache.org/POM/4.0.0}version')
                    version.text = f'${{{property_tag_name}}}'
                    dependency = dep
                    break

        if dependency is None:
            dependency = etree.SubElement(dependencies, '{http://maven.apache.org/POM/4.0.0}dependency')
            gid = etree.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}groupId')
            gid.text = group_id
            aid = etree.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}artifactId')
            aid.text = artifact_id
            version = etree.SubElement(dependency, '{http://maven.apache.org/POM/4.0.0}version')
            version.text = f'${{{property_tag_name}}}'

        # write back
        tree.write(self.pom_path, pretty_print=True, xml_declaration=True, encoding='utf-8')

        # return the name of the property tag
        return property_tag_name

    def set_pom_property_value(self, group_id:str, artifact_id:str, version:str):
        """set the value of the property in the pom.xml
        Return:
            property_tag_name (str): the name of the property tag
        """
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(self.pom_path, parser)
        root = tree.getroot()
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}

        property_tag_name = f'{group_id}_{artifact_id}_version'
        # add {group_id}_{artifact_id}_version into the properties
        properties = root.find('m:properties', namespaces=ns)
        if properties is None:
            properties = etree.SubElement(root, '{http://maven.apache.org/POM/4.0.0}properties')
        property_tag = properties.find(f'm:{property_tag_name}', namespaces=ns)
        if property_tag is None:
            property_tag = etree.SubElement(properties, f'{{http://maven.apache.org/POM/4.0.0}}{property_tag_name}')
        property_tag.text = version

        # write back
        tree.write(self.pom_path, pretty_print=True, xml_declaration=True, encoding='utf-8')

        return property_tag_name

    def store_validation_log(self, group_id:str, artifact_id:str, version:str, log, log_type:str):
        """store the recompilation log and binary BC api got by japicmp
        Args:
            group_id (str): the group id of the dependency
            artifact_id (str): the artifact id of the dependency
            version (str): the version of the dependency
            log : the log content. str for recompile log, dict for binary BC api
            log_type (str): the type of the log, 'recompile' or 'binary_bc_api'
        """
        # create the folder to store the log
        log_folder = os.path.join(constants.VALIDATION_LOG_DIR, self.repo_name, self.relative_path_to_module, group_id, artifact_id, version)
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)
        # store the log
        if log_type == 'recompile':
            log_file = os.path.join(log_folder, 'recompile.txt')
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(log)
        elif log_type == 'binary_bc_api':
            log_file = os.path.join(log_folder, 'binary_bc_api.json')
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(log, f, indent=4)
