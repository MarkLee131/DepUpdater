"""all operation on Revapi tool"""
import re
from pathlib import Path
from depupdater.analysis.cache import run_cached
from depupdater.paths import REVAPI_SH_PATH
class Revapi:
    """Revapi tool class"""

    def __init__(self, old_jar:str, new_jar:str):
        """
        Args:
            old_jar (str): the path to the old jar file
            new_jar (str): the path to the new jar file
        """
        self.old_jar = old_jar
        self.new_jar = new_jar
        # two list following are the BC records in Revapi report
        # the content are got from extract_bc_records method
        self.binary_bc_records = []
        self.source_bc_records = []
        # four dict following are bc_api -> bc_record
        # the content are got from extract_bc_api method
        self.binary_bc_method = {}
        self.binary_bc_type = {}
        self.source_bc_method = {}
        self.source_bc_type = {}

    def bc_api(self, groupId:str, artifactId:str, old_version:str, new_version:str):
        """main method of this file, get the bc api in the format of dict
        Returns:
            4 dict: binary_bc_method, binary_bc_type, source_bc_method, source_bc_type
            each dict is a bc api -> bc record mapping
        """
        # Legacy cached reports have no execution status and cannot establish success.
        self.binary_bc_records.clear()
        self.source_bc_records.clear()
        self.binary_bc_method.clear()
        self.binary_bc_type.clear()
        self.source_bc_method.clear()
        self.source_bc_type.clear()
        report = self.compare(groupId, artifactId, old_version, new_version)
        self.extract_bc_records(report)
        for record in self.binary_bc_records:
            self.extract_bc_api(record, 'binary')
        for record in self.source_bc_records:
            self.extract_bc_api(record, 'source')
        return self.binary_bc_method, self.binary_bc_type, self.source_bc_method, self.source_bc_type

    def compare(self, groupId:str, artifactId:str, old_version:str, new_version:str):
        """get the compatibility report between two jar files\n
        Reuse only the checked-execution cache; legacy reports have no status.
        """
        return self.run()

    def run(self):
        """Return a verified report, or raise on failure/timeout (never cache it)."""
        command = [REVAPI_SH_PATH,
                   '--extensions=org.revapi:revapi-java:0.28.1,org.revapi:revapi-reporter-text:0.15.0',
                   f'--old={self.old_jar}', f'--new={self.new_jar}',
                   '-D', 'revapi.reporter.text.minSeverity=BREAKING']
        tool_dir = Path(REVAPI_SH_PATH).parent
        binaries = sorted(tool_dir.rglob('*.jar'))
        return run_cached(command, files=[self.old_jar, self.new_jar, REVAPI_SH_PATH, *binaries],
                          namespace='revapi-checked-v1')

    def extract_bc_records(self, report:str):
        """extract the binary and source breaking change records from the report
        and store them in self.binary_bc_records and self.source_bc_records respectively
        """
        record_pattern = r"old: .*?(?=\n\n)"
        records = re.findall(record_pattern, report, re.DOTALL)
        for record in records:
            if 'BINARY: BREAKING' in record:
                self.binary_bc_records.append(record)
            if 'SOURCE: BREAKING' in record:
                self.source_bc_records.append(record)

    def extract_bc_api(self, record:str, binary_or_source:str):
        """extract the BC api from a Revapi record
        Args:
            record (str): a bc record from Revapi report
            binary_or_source (str): 'binary' or 'source' to distinguish the type of the bc record
        """
        if binary_or_source == 'binary':
            bc_method = self.binary_bc_method
            bc_type = self.binary_bc_type
        elif binary_or_source == 'source':
            bc_method = self.source_bc_method
            bc_type = self.source_bc_type
        else:
            raise ValueError('binary_or_source should be binary or source')
        if 'old: <none>' in record:
            # old api is None, so extract the type from new api
            api_pattern = r"new: .+? .+? (.+?)::.+?\n"
            match = re.search(api_pattern, record)
            api = match.group(1)
            api = self.transform_type(api)
            bc_type.setdefault(api, []).append(record)
        else:
            api_pattern = r"old: (.+?) (.+?)\n"
            match = re.search(api_pattern, record)
            api_type = match.group(1)
            api = match.group(2)
            if api_type == 'class' or api_type == 'interface' \
                or api_type == 'enum' or api_type == '@interface':
                # api is the bc type
                api = self.transform_type(api)
                bc_type.setdefault(api, []).append(record)
            elif api_type == 'field':
                # api is the filed of a the bc type
                # remove inherited class
                if ' @' in api:
                    api = api[:api.find(' @')]
                # restore it to the type, means ignore the last . and the field name
                api = api[:api.rfind('.')]
                api = self.transform_type(api)
                bc_type.setdefault(api, []).append(record)
            elif api_type == 'method':
                # remove inherited class
                if ' @' in api:
                    api = api[:api.find(' @')]
                # remove throws
                if ' throws ' in api:
                    api = api[:api.find(' throws ')]
                api = self.transform_method(api)
                bc_method.setdefault(api, []).append(record)
            elif api_type == 'parameter':
                # remove inherited class
                if ' @' in api:
                    api = api[:api.find(' @')]
                # remove === === in the ParameterType
                api = api.replace('===', '')
                api = self.transform_method(api)
                bc_method.setdefault(api, []).append(record)

    @staticmethod
    def transform_type(_type:str):
        """transform the type to the format in the type dependency graph
        remove <> to disregard generic
        """
        _type = Revapi.remove_angle_brackets(_type)
        return _type

    @staticmethod
    def transform_method(method:str):
        """transform the method to the format in the call graph
        1. change a generic type to its upper bound
        2. remove <> to disregard generic
        """
        # handle generic type defined in the class
        class_generic_type_pattern = r'<([^<>]*)>::'
        class_generic_match = re.search(class_generic_type_pattern, method)
        if class_generic_match:
            # generic type exists in the class
            class_generic_declaration = class_generic_match.group(1)
            generic_letter_and_type = Revapi.handle_generic_declaration(class_generic_declaration)
            method = Revapi.replace_letter_with_upper_bound(method, generic_letter_and_type)
        # # handle generic type defined in the method
        method_generic_type_pattern = r'^<(.*?)>'
        method_generic_match = re.search(method_generic_type_pattern, method)
        if method_generic_match:
            # generic type exists in the method
            method_generic_declaration = method_generic_match.group(1)
            generic_letter_and_type = Revapi.handle_generic_declaration(method_generic_declaration)
            method = Revapi.replace_letter_with_upper_bound(method, generic_letter_and_type)
        # remove <> to disregard generic
        method = Revapi.remove_angle_brackets(method).strip()
        return method

    @staticmethod
    def handle_generic_declaration(generic_declaration:str):
        """handle the generic type
        Args:
            generic_declaration (str): the generic declaration, like <S extends java.lang.annotation.Annotation, T>
        Returns:
            generic_letter_and_type (list): a list of tuple, each tuple contains the generic letter and its upper bound\n
            generic_letter is the letter representing generic type, like S and T
            generic_type is the upper bound of the generic type, like java.lang.annotation.Annotation and java.lang.Object
        """
        # may have multiple generic types
        individual_declarations = generic_declaration.split(', ')
        generic_letter_and_type = []
        for declaration in individual_declarations:
            if ' extends ' in declaration:
                # upper bound is defined after 'extends'
                generic_letter = declaration[:declaration.find(' extends ')]
                generic_type = declaration[declaration.find(' extends ')+9:]
                generic_letter_and_type.append((generic_letter, generic_type))
            else:
                # upper bound is java.lang.Object
                generic_letter = declaration
                generic_letter_and_type.append((generic_letter, 'java.lang.Object'))
        # print(generic_letter_and_type)
        return generic_letter_and_type

    @staticmethod
    def replace_letter_with_upper_bound(method:str, generic_letter_and_type:list):
        """replace the generic letter with its upper bound
        in parameter, return type"""
        for generic_letter, upper_bound in generic_letter_and_type:
            # letter_pattern = r'\b' + generic_letter + r'\b'
            letter_pattern = r'\b' + re.escape(generic_letter) + r'\b'
            method = re.sub(letter_pattern, upper_bound, method)
        return method

    @staticmethod
    def remove_angle_brackets(text:str):
        """remove <> in the text"""
        while re.search(r'<[^<>]*>', text):
            text = re.sub(r'<[^<>]*>', '', text)
        return text

