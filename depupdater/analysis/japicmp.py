"""use japicmp to check the binary compatibility of one version"""
import subprocess
import re


from depupdater.paths import JAPICMP_PATH
from depupdater.database.query import query_japicmp_bc_api, query_japicmp_report,\
    store_japicmp_report, store_japicmp_bc_api, query_to_get_jar_location
from depupdater.analysis.revapi import Revapi


class Japicmp:
    """japicmp tool class"""
    
    def __init__(self, old_jar:str, new_jar:str):
        """
        Args:
            old_jar (str): the path to the old jar file
            new_jar (str): the path to the new jar file
        """
        self.old_jar = old_jar
        self.new_jar = new_jar
        # the list following are the bin BC records in Japicmp report
        # the content are got from extract_bc_records method
        self.binary_bc_records = []
        # four dict following are bc_api -> bc_record
        # the content are got from extract_bc_api method
        self.binary_bc_method = {}
        self.binary_bc_type = {}

    def bc_api(self, groupId: str, artifactId: str, oldVersion: str, newVersion: str):
        """get the bin bc api in the format of dict"""
        # command to check the binary compatibility between two jars
        binary_bc_method, binary_bc_type = query_japicmp_bc_api(groupId, artifactId, oldVersion, newVersion)
        if binary_bc_method is not None \
            and binary_bc_type is not None:
            # bin bc api exists in the database
            return binary_bc_method, binary_bc_type
        # bin bc api not exists in the database
        report = self.compare(groupId, artifactId, oldVersion, newVersion)
        self.extract_bc_records(report)
        for record in self.binary_bc_records:
            # extract the bc api from the bc records
            self.extract_bc_api(record)
        store_japicmp_bc_api(groupId, artifactId, oldVersion, newVersion, self.binary_bc_method, self.binary_bc_type)
        return self.binary_bc_method, self.binary_bc_type

    def compare(self, groupId:str, artifactId:str, old_version:str, new_version:str):
        """get the binary compatibility report of two jar files
        query sqlite first, if not exists, use japicmp to get and store the report in sqlite
        """
        # print(f'Comparing {groupId}:{artifactId}:{old_version} -> {groupId}:{artifactId}:{new_version}')
        report = query_japicmp_report(groupId, artifactId, old_version, new_version)
        if report:
            # report exists in the database
            return report
        report = self.run()
        # store the report in the database
        store_japicmp_report(groupId, artifactId, old_version, new_version, report)
        return report

    def run(self):
        """run Japicmp to get the binary report"""
        command = f'java -jar {JAPICMP_PATH} --ignore-missing-classes --only-modified -b -n {self.new_jar} -o {self.old_jar}'
        result = subprocess.run(command, shell=True, text=True, capture_output=True)
        return result.stdout
    
    def extract_bc_records(self, report:str):
        """extract the binary bc records from the report
        and store then in self.binary_bc_records
        """
        record_pattern = r'(?:\n\*\*\*! |\n===! |\n---! |\n\+\+\+! ).*?(?=\n\*\*\*! |\n===! |\n---! |\n\+\+\+! |\Z)'
        records = re.findall(record_pattern, report, re.DOTALL)
        self.binary_bc_records = records

    def extract_bc_api(self, record:str):
        """extract the binary bc api from a record
        and store them in self.binary_bc_method and self.binary_bc_type
        
        Args:
            record (str): a bin bc record from japicmp report
        """
        # extract the type name
        type_pattern = r' ([^ ]*?)  \('
        bc_type_name = re.search(type_pattern, record).group(1).replace('$', '.')
        self.binary_bc_type.setdefault(bc_type_name, []).append(record)
        api_lines = record.split('\n')
        # method_pattern = r' ([^()]*?) ([^()]*?)(\([^()]*?\))\Z'
        method_pattern = r' ([^()]*?|\(<-.*?\)) ([^() ]*?)(\([^()]*?\))\Z'
        constructor_pattern = r' [^()]*?(\([^()]*?\))\Z'
        for api_line in api_lines:
            api_line = (Revapi.remove_angle_brackets(api_line)).replace('$', '.')
            # extract methods in record
            if 'METHOD:' in api_line:
                # # debug
                # print('method:', api_line)
                method_match = re.search(method_pattern, api_line)
                return_type = method_match.group(1)
                if return_type.startswith('(<-'):
                    return_type = return_type[3:-1]
                # # debug
                # print('return_type:', return_type)
                method_name = method_match.group(2)
                # # debug
                # print('method_name:', method_name)
                parameter_list = method_match.group(3)
                # # debug
                # print('parameter_list:', parameter_list)
                complete_method_name = f'{return_type} {bc_type_name}::{method_name}{parameter_list}'
                self.binary_bc_method.setdefault(complete_method_name, []).append(record)
                continue
            # extract constructors
            if 'CONSTRUCTOR:' in api_line:
                # # debug
                # print('constructor:', api_line)
                constructor_match = re.search(constructor_pattern, api_line)
                parameter_list = constructor_match.group(1)
                # # debug
                # print('parameter_list:', parameter_list)
                complete_constructor_name = f'void {bc_type_name}::<init>{parameter_list}'
                self.binary_bc_method.setdefault(complete_constructor_name, []).append(record)
                continue
