"""use soot to get the CG/type_DG of a jar file"""
import os
from depupdater.analysis.cache import run_cached
from depupdater.analysis.execution import AnalysisError
import csv
import zipfile

from depupdater.database.query import query_to_get_jar_location
from depupdater.paths import SOOTCG_PATH,SOOT_TYPE_DG_PATH,get_soot_empty_cases_csv,\
    BCEL_METHOD_PATH,BCEL_TYPE_PATH
from depupdater.preprocessing.restore import Restore

class Api:
    def __init__(self, groupId:str, artifactId:str, version:str):
        self.groupId = groupId
        self.artifactId = artifactId
        self.version = version
        self.jar_path = self.get_jar()
        self.can_download = Restore.get_dep_jar(self.groupId, self.artifactId, self.version)

    def _analyze(self, tool, kind):
        if not self.can_download:
            raise AnalysisError(f'JAR unavailable: {self.groupId}:{self.artifactId}:{self.version}')
        if not zipfile.is_zipfile(self.jar_path):
            raise AnalysisError(f'Invalid JAR: {self.jar_path}')
        return run_cached(['java', '-jar', tool, self.jar_path],
                          files=[tool, self.jar_path], namespace=f'{kind}-checked-v1',
                          reject_stderr=kind in ('methods', 'types'))

    def get_cg(self):
        """Return a successfully computed graph, which may be empty."""
        graph = self._analyze(SOOTCG_PATH, 'call-graph')
        if not graph:
            self.store_empty_cases('cg')
        return graph

    def get_type_dg(self):
        """Return a successfully computed type graph, which may be empty."""
        graph = self._analyze(SOOT_TYPE_DG_PATH, 'type-graph')
        if not graph:
            self.store_empty_cases('type_dg')
        return graph

    def get_methods(self):
        """Return (methods, success). Empty successful output is (set(), True).

        Missing JARs, execution failures and timeouts raise AnalysisError;
        they must not silently trigger the semantic-versioning fallback.
        """
        return self.split_text(self._analyze(BCEL_METHOD_PATH, 'methods')), True

    def get_types(self):
        """Return (types, success); failures raise instead of looking empty."""
        return self.split_text(self._analyze(BCEL_TYPE_PATH, 'types')), True

    @staticmethod
    def split_text(text:str):
        """split the text by '\n' and remove empty strings"""
        ret = set()
        for line in text.split('\n'):
            if line.strip():
                ret.add(line.strip())
        return ret

    def store_empty_cases(self, _type:str):
        """store the gav of the jar file which has empty cg or dg
        Args:
            type (str): 'cg' or 'type_dg'
        """
        csv_path = get_soot_empty_cases_csv()
        if csv_path is None:
            return
        header_written = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
        with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not header_written:
                writer.writerow(['groupId', 'artifactId', 'version', 'type'])
            writer.writerow([self.groupId, self.artifactId, self.version, _type])

    def get_jar(self):
        """get the jar file"""
        jar_path = query_to_get_jar_location(self.groupId, self.artifactId, self.version)
        return jar_path
    
    def extract_methods_from_cg(self, cg:str):
        """extract methods from call graph"""
        methods = set()
        for line in cg.split('\n'):
            # caller -> callee in one line, extract caller and callee
            if '->' in line:
                caller, callee = line.split(' -> ')
                if self.filter_method(caller):
                    methods.add(caller.strip())
                if self.filter_method(callee):
                    methods.add(callee.strip())
        return methods
    
    def extract_types_from_dg(self, dg:str):
        """extract types from dependency graph"""
        types = set()
        for line in dg.split('\n'):
            # caller -> callee in one line, extract caller and callee
            if '->' in line:
                caller, callee = line.split(' -> ')
                if self.filter_type(caller):
                    types.add(caller.strip())
                if self.filter_type(callee):
                    types.add(callee.strip())
        return types

    def filter_method(self, method:str):
        """filter built-in methods
        if methods are built-in methods, return False
        """
        # extract class name from method
        # class name is between the first ' ' and '::'
        class_name = method.split(' ')[1].split('::')[0]
        return self.filter_type(class_name)
            
    def filter_type(self, type:str):
        """filter built-in types
        if types are built-in types, return False
        """
        return type.startswith('java.') is False \
            and type.startswith('javax.') is False \
                and type.startswith('sun.') is False \
                    and type.startswith('com.sun.') is False \
                        and type.startswith('sunw.') is False \
                            and type.startswith('com.ibm.') is False \
                                and type.startswith('com.apple.') is False \
                                    and type.startswith('apple.awt.') is False \
                                        and type.startswith('jdk.internal.') is False

    @staticmethod
    def parse_call_relations(call_relations_str:str):
        """Parse a string of caller -> callee relations
        Args:
            call_relations_str (str): A string of caller -> callee relations\n
            can be cg ,type_dg or reachable_api_pair from file
        Returns:
            call_relations (dict): A dictionary of caller -> callees relations\n
            key: caller, value: a set of the corresponding callees\n
        """
        call_relations = {}
        if not call_relations_str:
            # empty string, so call_relations is empty as well
            return call_relations

        # Split the string by lines
        lines = call_relations_str.strip().split('\n')
        
        # Process each line
        for line in lines:
            caller, callee = line.strip().split(' -> ')
            if caller in call_relations:
                call_relations[caller].add(callee)
            else:
                call_relations[caller] = {callee}
        return call_relations
    
    @staticmethod
    def find_matching_relations(call_relations: dict, target_callers:set):
        """Filter caller -> callee relations in call_relations that callee in target_callers
        Args:
            call_relations (dict): A dictionary of caller -> callees relations\n
            key: caller, value: a set of the corresponding callees\n
            target_callers (set): A set of target callers\n
        Returns:
            matching_relations (set): A set of matching caller -> callee relations tuple\n
            [0] is caller while [1] is callee
        """
        matching_relations = set()
        
        for caller, callees in call_relations.items():
            for callee in callees:
                if callee in target_callers:
                    matching_relations.add((caller, callee))
        return matching_relations
    
    @staticmethod
    def find_reachable_calls(entry_points:set, call_relations:dict):
        """Recursively find all reachable call relations starting from entry points
        Returns:
            reachable (dict): A caller -> set of the corresponding callees\n
        """
        reachable = {}
        visited = set()
        
        def dfs(caller):
            if caller in visited:
                return
            visited.add(caller)
            if caller in call_relations:
                for callee in call_relations[caller]:
                    # relation = (caller, callee)
                    # if relation not in reachable:
                    #     reachable.add(relation)
                    reachable.setdefault(caller, set()).add(callee)
                    dfs(callee)
        for entry in entry_points:
            dfs(entry)
        
        return reachable
