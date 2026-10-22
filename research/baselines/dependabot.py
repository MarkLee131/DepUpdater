"""evaluate the performance of Dependabot
this script should be executed after Dataset.py
"""
import pandas as pd
import json
import concurrent.futures
import subprocess
import os
import logging
import re
from tqdm import tqdm
from depupdater.paths import DATA_DIR, RET_DIR, set_log_path
from depupdater.preprocessing.restore import Restore
from depupdater.metrics.dependency_count import count_deps



def main():
    """main function"""
    log_path = os.path.join(DATA_DIR, 'dependabot_log.txt')
    # clear log
    if os.path.exists(log_path):
        os.remove(log_path)
    # set log
    logging.basicConfig(filename=log_path,level=logging.INFO,format='%(asctime)s - %(message)s')

    csv_path = os.path.join(DATA_DIR, 'dependabot_dataset.csv')
    # Create or load CSV file
    if os.path.exists(csv_path):
        dataset_df = pd.read_csv(csv_path)
    else:
        # Create a DataFrame with the header if the CSV does not exist
        dataset_df = pd.DataFrame(columns=['repo', 'module', 'dependabot_compile_success', 'dependabot_test_pass',
                                           'original_tech_lag', 'dependabot_current_tech_lag', 'dependabot_reduced_tech_lag', \
                                               'original_dep_count', 'dependabot_current_dep_count', 'dependabot_reduced_dep_count'])
        dataset_df.to_csv(csv_path, index=False)

    # set module
    modules = dataset()

    with tqdm(total=len(modules)) as pbar:
        for module in modules:
            print(module)
            repo_name, module_name = module[0], module[1]
            # Check if this module has already been processed
            # if ((dataset_df['repo'] == repo_name) & (dataset_df['module'] == module_name)).any():
            #     logging.info(f"{repo_name} : {module_name} done")
            #     pbar.update(1)
            #     continue

            logging.info(f"processing {repo_name} : {module_name}")
            row_value = evaluate_dependabot(module)
            row_df = pd.DataFrame([row_value], columns=['repo', 'module', 'compile_success', 'test_pass',\
                                                    'original_tech_lag', 'current_tech_lag', 'reduced_tech_lag', \
                                                        'original_dep_count', 'current_dep_count', 'reduced_dep_count'])
            numeric_cols = ['original_tech_lag', 'current_tech_lag', 'reduced_tech_lag', 'original_dep_count', 'current_dep_count', 'reduced_dep_count']
            for col in numeric_cols:
                row_df[col] = pd.to_numeric(row_df[col], errors='coerce')
            row_df.to_csv(csv_path, mode='a', header=False, index=False)
            logging.info(f"{repo_name} : {module_name} done")
            pbar.update(1)

def evaluate_dependabot(module):
    """evaluate the performance of Dependabot
    Return:
        row_value: list which is a row in the dataset
    """
    repo_name, module_name = module[0], module[1]
    dependabot_dir_path = os.path.join(DATA_DIR, 'dependabot', repo_name, module_name)
    if not os.path.exists(dependabot_dir_path):
        os.makedirs(dependabot_dir_path)
    set_log_path(os.path.join(dependabot_dir_path, 'dependabot_evaluation.txt'))
    # read original_version.json to get the original tech lag and original dep count
    original_json_path = os.path.join(RET_DIR, repo_name, module_name, 'original_version.json')
    if not os.path.exists(original_json_path):
        return [repo_name, module_name, '?', '?', '?', '?', '?', '?', '?', '?']
    with open(original_json_path, 'r') as f:
        original_graph = json.load(f)
    original_tech_lag = Restore.compute_original_tech_lag(original_graph,[])
    original_dep_count = count_deps(original_json_path)

    # # recompie and test
    # compile_log_path = os.path.join(dependabot_dir_path, 'compile_log.txt')
    # test_log_path = os.path.join(dependabot_dir_path, 'test_log.txt')
    # if not os.path.exists(compile_log_path):
    #     # compile to judge whether the module can compile after update
    #     compile_flag = recompile(repo_name, module_name)
    # else:
    #     with open(compile_log_path, 'r') as f:
    #         log = f.read()
    #         if "BUILD FAILURE" in log:
    #             compile_flag = False
    #         else :
    #             compile_flag = True
    # if not os.path.exists(test_log_path):
    #     # test to judge whether the module can pass the test after update
    #     test_flag = test(repo_name, module_name)
    # else:
    #     with open(test_log_path, 'r') as f:
    #         log = f.read()
    #         if "BUILD FAILURE" in log:
    #             test_flag = False
    #         else :
    #             test_flag = True

    # compute the current tech lag and current dep count
    tree_path = os.path.join(dependabot_dir_path, 'verbose_tree.txt')
    json_path = tree_to_json(tree_path, os.path.join('/home1/kaixuan/ray/Dependabot_Snyk_dataset/Dependabot/', repo_name), module_name)
    if not json_path:
        # cann't generate dependency graph
        
        return [repo_name, module_name, compile_flag, test_flag, int(original_tech_lag[0]), '?', '?', int(original_dep_count), '?', '?']
        # return [repo_name, module_name, True, True, int(original_tech_lag[0]), '?', '?', int(original_dep_count), '?', '?']
    with open(json_path, 'r') as f:
        current_graph = json.load(f)
    current_tech_lag = Restore.compute_original_tech_lag(current_graph,[])
    current_dep_count = count_deps(json_path)
    
    return [repo_name, module_name, compile_flag, test_flag, int(original_tech_lag[0]), int(current_tech_lag[0]), int(original_tech_lag[0]-current_tech_lag[0]), int(original_dep_count), int(current_dep_count), int(original_dep_count-current_dep_count)]
    # return [repo_name, module_name, True, True, int(original_tech_lag[0]), int(current_tech_lag[0]), int(original_tech_lag[0]-current_tech_lag[0]), int(original_dep_count), int(current_dep_count), int(original_dep_count-current_dep_count)]


def recompile(repo_name, module_path):
    """recompile the module"""
    compile_log_path = os.path.join(DATA_DIR, 'dependabot', repo_name, module_path, 'compile_log.txt')
    path_to_cloned_folder = os.path.join('/home1/kaixuan/ray/Dependabot_Snyk_dataset/Dependabot/', repo_name)
    command = f"cd {os.path.join(path_to_cloned_folder, module_path)} &&\
        mvn -Dmaven.test.skip=true -Dcheckstyle.skip=true -Denforcer.skip=true -Dflatten.skip=true \
                -Dspotless.check.skip=true compile"
    try:
        result = subprocess.run(command, shell=True, text=True, capture_output=True)
        if result.returncode != 0:
            # second, mvn compile in root folder with -pl -am
            command = f"cd {path_to_cloned_folder} && mvn -Dmaven.test.skip=true -Dcheckstyle.skip=true -Denforcer.skip=true \
                -Dflatten.skip=true -Dspotless.check.skip=true \
                    -pl {module_path} compile -am"
            result = subprocess.run(command, shell=True, text=True, capture_output=True)
            if result.returncode != 0:
                # recompile fails
                with open(compile_log_path, 'w') as f:
                    f.write(result.stdout)
                return False
        with open(compile_log_path, 'w') as f:
            f.write(result.stdout)
        return True
    except subprocess.SubprocessError as e:
        print(f"An error occured while execute the command: {e}")
        return False

def test(repo_name, module_path):
    """test the module"""
    test_log_path = os.path.join(DATA_DIR, 'dependabot', repo_name, module_path, 'test_log.txt')
    path_to_cloned_folder = os.path.join('/home1/kaixuan/ray/Dependabot_Snyk_dataset/Dependabot/', repo_name)
    path_to_project_folder = os.path.join('/home1/kaixuan/ray/Dependabot_Snyk_dataset/Dependabot/', repo_name)
    command = f"cd {os.path.join(path_to_project_folder, module_path)} && \
            mvn -Dcheckstyle.skip=true -Denforcer.skip=true -Dflatten.skip=true -Dspotless.check.skip=true test"
    try:
        result = subprocess.run(command, shell=True, text=True, capture_output=True)
        if result.returncode != 0:
            command = f"cd {path_to_cloned_folder} && mvn -Dcheckstyle.skip=true -Denforcer.skip=true -Dflatten.skip=true -Dspotless.check.skip=true \
                    -pl {module_path} test -am"
        result = subprocess.run(command, shell=True, text=True, capture_output=True)
        if result.returncode != 0:
            # test fails
            with open(test_log_path, 'w') as f:
                f.write(result.stdout)
            return False
        with open(test_log_path, 'w') as f:
            f.write(result.stdout)
        return True
    except subprocess.SubprocessError as e:
        print(f"An error occured while execute the command: {e}")
        return False

def tree_to_json(tree_path:str, path_to_cloned_folder:str, relative_path_to_module:str):
    """parse verbose_tree.txt to get the dependency graph and store it in the json file"""
    json_path = os.path.join(DATA_DIR, 'dependabot', os.path.basename(path_to_cloned_folder), relative_path_to_module, 'current_version.json')
    if os.path.exists(json_path):
        return json_path

    if not os.path.exists(tree_path):
        # mvn dependency:tree to generate dependency graph
        tree = mvn_tree(path_to_cloned_folder, relative_path_to_module)
        if tree is None:
            # cannlt generate dependency graph
            return None
        with open(tree_path, 'w', encoding='utf-8') as f:
            f.write(tree)
    else:
        with open(tree_path, 'r', encoding='utf-8') as f:
            tree = f.read()

    res = Restore(path_to_cloned_folder, relative_path_to_module, tree_path,[],[])
    # extract the original dependency graph from verbose_tree.txt
    # inspired by preprocess/Restore.py
    block_pattern = r'\[INFO\] Building .+?\n\[INFO\].+?from (.*?)pom.xml\n\[INFO\] -+?\[ (.+?) \]-+?\n.*?\[INFO\] (\S+?):(\S+?):\S+?:(\S+?)\n(.+?)\[INFO\] -'
    blocks = re.finditer(block_pattern, tree, flags=re.DOTALL)
    deps = None
    for block in blocks:
        if relative_path_to_module == '.':
            flag = (block.group(1) == '')
        elif relative_path_to_module.endswith('/'):
            # the second parameter represents the relative path to the module ends with '/'
            # block.group(1) endswith '/'
            flag = (block.group(1) == relative_path_to_module)
        else :
            flag = (block.group(1) == relative_path_to_module+'/')
        if block.group(2) == 'jar' and flag:
            res.client_groupId = block.group(3)
            res.client_artifactId = block.group(4)
            res.client_version = block.group(5)
            deps = res.parse_all_dep(block.group(6))
            break
    valid_deps, omitted_deps = res.filter_dep(deps)
    res.change_valid_deps(valid_deps)
    res.change_omitted_deps(omitted_deps)
    mappings = [{'GroupId':res.client_groupId, 'ArtifactId':res.client_artifactId,\
            'Original_Version':res.client_version, 'Best_Version':'', 'Type':'',\
                'Depth':0, 'Count':0, 'Dependents':[]}] # add client at first
    num_workers = os.cpu_count()
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for valid_dep in valid_deps:
            futures.append(executor.submit(res.process_a_valid_dep, valid_dep, omitted_deps))
    for future in futures:
        mappings.append(future.result())

    res.process_omitted_deps(valid_deps, omitted_deps, mappings)
    res.prune_graph(mappings, False)
    mappings = [node for node in mappings if node['Dependents'] or node['Depth'] == 0]
    
    with open(json_path, 'w') as f:
        json.dump(mappings, f, indent=4)
    return json_path

def mvn_tree(path_to_folder:str, relative_path_to_module:str):
    """execute mvn dependency:tree"""
    command = f"cd {path_to_folder} && mvn dependency:tree -pl {relative_path_to_module} -am -Dverbose -fae"
    result = subprocess.run(command, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        # cann't generate dependency graph
        return None
    return result.stdout

def dataset():
    """set modules in the dataset"""
    modules = [
        # 226 modules
        ('mall','mall-common'),
        ('mall','mall-security'),
        # ('guava','guava'),
        # ('guava','guava-testlib'),
        ('dubbo','dubbo-test/dubbo-test-common'),
        # ('dubbo','dubbo-test/dubbo-test-check'),
        ('dubbo','dubbo-test/dubbo-test-modules'),
        # ('dubbo','dubbo-serialization/dubbo-serialization-api'),
        # ('dubbo','dubbo-serialization/dubbo-serialization-fastjson2'),
        ('dubbo','dubbo-serialization/dubbo-serialization-hessian2'),
        # ('dubbo','dubbo-maven-plugin'),
        ('dubbo','dubbo-spring-boot/dubbo-spring-boot-3-autoconfigure'),
        # ('dubbo','dubbo-configcenter/dubbo-configcenter-apollo'),
        # ('dubbo','dubbo-configcenter/dubbo-configcenter-nacos'),
        # ('dubbo','dubbo-configcenter/dubbo-configcenter-file'),
        # ('dubbo','dubbo-configcenter/dubbo-configcenter-zookeeper'),
        # ('dubbo','dubbo-metrics/dubbo-metrics-api'),
        ('dubbo','dubbo-metrics/dubbo-metrics-event'),
        # ('dubbo','dubbo-metrics/dubbo-metrics-prometheus'),
        ('dubbo','dubbo-metrics/dubbo-metrics-config-center'),
        # ('dubbo','dubbo-metrics/dubbo-metrics-metadata'),
        # ('dubbo','dubbo-metrics/dubbo-metrics-default'),
        ('dubbo','dubbo-metrics/dubbo-metrics-netty'),
        # ('dubbo','dubbo-metrics/dubbo-tracing'),
        ('dubbo','dubbo-plugin/dubbo-auth'),
        # ('dubbo','dubbo-plugin/dubbo-filter-validation'),
        # ('dubbo','dubbo-plugin/dubbo-spring-security'),
        ('dubbo','dubbo-plugin/dubbo-compiler'),
        # ('dubbo','dubbo-plugin/dubbo-qos-api'),
        ('dubbo','dubbo-plugin/dubbo-filter-cache'),
        ('dubbo','dubbo-remoting/dubbo-remoting-api'),
        # ('dubbo','dubbo-remoting/dubbo-remoting-netty4'),
        # ('dubbo','dubbo-remoting/dubbo-remoting-netty'),
        # ('dubbo','dubbo-remoting/dubbo-remoting-zookeeper-curator5'),
        ('dubbo','dubbo-cluster'),
        ('dubbo','dubbo-rpc/dubbo-rpc-api'),
        # ('dubbo','dubbo-rpc/dubbo-rpc-dubbo'),
        ('dubbo','dubbo-rpc/dubbo-rpc-injvm'),
        ('dubbo','dubbo-demo/dubbo-demo-interface'),
        ('dubbo','dubbo-demo/dubbo-demo-spring-boot/dubbo-demo-spring-boot-interface'),
        # ('netty','buffer'),
        # ('netty','handler-proxy'),
        ('netty','testsuite-autobahn'),
        # ('netty','handler-ssl-ocsp'),
        ('netty','testsuite-http2'),
        # ('netty','codec'),
        ('netty','codec-dns'),
        ('netty','codec-haproxy'),
        ('netty','codec-memcache'),
        ('netty','codec-mqtt'),
        ('netty','codec-redis'),
        ('netty','codec-smtp'),
        ('netty','codec-stomp'),
        ('netty','codec-socks'),
        ('netty','codec-xml'),
        # ('netty','common'),
        # ('netty','transport'),
        ('netty','transport-rxtx'),
        # ('netty','transport-sctp'),
        ('netty','transport-udt'),
        ('netty','example'),
        # ('netty','dev-tools'),
        ('java-design-patterns', 'monad'),
        ('java-design-patterns', 'value-object'),
        ('java-design-patterns', 'ambassador'),
        ('java-design-patterns', 'model-view-controller'),
        ('java-design-patterns', 'bridge'),
        ('java-design-patterns', 'facade'),
        ('java-design-patterns', 'event-driven-architecture'),
        ('java-design-patterns', 'lockable-object'),
        ('java-design-patterns', 'collection-pipeline'),
        ('java-design-patterns', 'interpreter'),
        ('java-design-patterns', 'resource-acquisition-is-initialization'),
        ('java-design-patterns', 'page-controller'),
        ('java-design-patterns', 'version-number'),
        # ('java-design-patterns', 'command-query-responsibility-segregation'),
        ('java-design-patterns', 'data-locality'),
        ('java-design-patterns', 'double-checked-locking'),
        ('java-design-patterns', 'repository'),
        ('java-design-patterns', 'composite-entity'),
        ('java-design-patterns', 'gateway'),
        ('java-design-patterns', 'master-worker'),
        ('java-design-patterns', 'multiton'),
        ('java-design-patterns', 'monostate'),
        ('java-design-patterns', 'trampoline'),
        ('java-design-patterns', 'notification'),
        ('java-design-patterns', 'singleton'),
        ('java-design-patterns', 'throttling'),
        ('java-design-patterns', 'producer-consumer'),
        ('java-design-patterns', 'component'),
        ('java-design-patterns', 'object-pool'),
        ('java-design-patterns', 'table-module'),
        ('java-design-patterns', 'optimistic-offline-lock'),
        ('java-design-patterns', 'flux'),
        ('java-design-patterns', 'delegation'),
        ('java-design-patterns', 'extension-objects'),
        ('java-design-patterns', 'anti-corruption-layer'),
        ('java-design-patterns', 'dynamic-proxy'),
        ('java-design-patterns', 'caching'),
        ('java-design-patterns', 'bytecode'),
        # ('java-design-patterns', 'microservices-aggregrator'),
        ('java-design-patterns', 'servant'),
        ('java-design-patterns', 'visitor'),
        ('java-design-patterns', 'null-object'),
        # ('java-design-patterns', 'page-object'),
        ('java-design-patterns', 'fluent-interface'),
        ('java-design-patterns', 'event-sourcing'),
        ('java-design-patterns', 'reactor'),
        ('java-design-patterns', 'fanout-fanin'),
        ('java-design-patterns', 'client-session'),
        ('java-design-patterns', 'half-sync-half-async'),
        ('java-design-patterns', 'marker-interface'),
        ('java-design-patterns', 'function-composition'),
        ('java-design-patterns', 'promise'),
        # ('java-design-patterns', 'naked-objects'),
        ('java-design-patterns', 'saga'),
        # ('java-design-patterns', 'localization'),
        ('java-design-patterns', 'microservices-log-aggregation'),
        ('java-design-patterns', 'transaction-script'),
        ('java-design-patterns', 'poison-pill'),
        # ('java-design-patterns', 'service-layer'),
        ('java-design-patterns', 'data-transfer-object'),
        ('java-design-patterns', 'data-mapper'),
        ('java-design-patterns', 'builder'),
        ('java-design-patterns', 'health-check'),
        ('java-design-patterns', 'specification'),
        ('java-design-patterns', 'strangler'),
        ('java-design-patterns', 'queue-based-load-leveling'),
        ('java-design-patterns', 'converter'),
        ('java-design-patterns', 'collecting-parameter'),
        # ('java-design-patterns', 'model-view-presenter'),
        ('java-design-patterns', 'proxy'),
        ('java-design-patterns', 'serialized-entity'),
        ('java-design-patterns', 'business-delegate'),
        ('java-design-patterns', 'combinator'),
        # ('java-design-patterns', 'etc'),
        ('java-design-patterns', 'layered-architecture'),
        # ('java-design-patterns', 'intercepting-filter'),
        ('java-design-patterns', 'data-access-object'),
        ('java-design-patterns', 'abstract-document'),
        ('java-design-patterns', 'virtual-proxy'),
        ('java-design-patterns', 'async-method-invocation'),
        ('java-design-patterns', 'observer'),
        ('java-design-patterns', 'filterer'),
        ('java-design-patterns', 'identity-map'),
        ('java-design-patterns', 'object-mother'),
        ('java-design-patterns', 'factory-method'),
        ('java-design-patterns', 'special-case'),
        ('java-design-patterns', 'chain-of-responsibility'),
        ('java-design-patterns', 'memento'),
        ('java-design-patterns', 'mediator'),
        ('java-design-patterns', 'abstract-factory'),
        ('java-design-patterns', 'callback'),
        ('java-design-patterns', 'domain-model'),
        ('java-design-patterns', 'data-bus'),
        ('java-design-patterns', 'leader-election'),
        ('java-design-patterns', 'service-to-worker'),
        ('java-design-patterns', 'acyclic-visitor'),
        ('java-design-patterns', 'registry'),
        # ('java-design-patterns', 'hexagonal-architecture'),
        ('java-design-patterns', 'front-controller'),
        ('java-design-patterns', 'model-view-intent'),
        ('java-design-patterns', 'type-object'),
        ('java-design-patterns', 'decorator'),
        ('java-design-patterns', 'service-locator'),
        ('java-design-patterns', 'composite'),
        ('java-design-patterns', 'strategy'),
        ('java-design-patterns', 'flyweight'),
        ('java-design-patterns', 'server-session'),
        ('java-design-patterns', 'subclass-sandbox'),
        ('java-design-patterns', 'dirty-flag'),
        ('java-design-patterns', 'twin'),
        ('java-design-patterns', 'active-object'),
        ('java-design-patterns', 'double-buffer'),
        ('java-design-patterns', 'game-loop'),
        ('java-design-patterns', 'context-object'),
        ('java-design-patterns', 'template-method'),
        ('java-design-patterns', 'separated-interface'),
        ('java-design-patterns', 'commander'),
        ('java-design-patterns', 'step-builder'),
        ('java-design-patterns', 'state'),
        ('java-design-patterns', 'tolerant-reader'),
        ('java-design-patterns', 'guarded-suspension'),
        ('java-design-patterns', 'sharding'),
        ('java-design-patterns', 'property'),
        ('java-design-patterns', 'balking'),
        ('java-design-patterns', 'currying'),
        # ('java-design-patterns', 'microservices-distributed-tracing'),
        ('java-design-patterns', 'event-aggregator'),
        ('java-design-patterns', 'leader-followers'),
        ('java-design-patterns', 'partial-response'),
        ('java-design-patterns', 'update-method'),
        ('java-design-patterns', 'private-class-data'),
        ('java-design-patterns', 'metadata-mapping'),
        ('java-design-patterns', 'prototype'),
        ('java-design-patterns', 'serialized-lob'),
        ('java-design-patterns', 'retry'),
        ('java-design-patterns', 'mute-idiom'),
        ('java-design-patterns', 'role-object'),
        # ('java-design-patterns', 'model-view-viewmodel'),
        ('java-design-patterns', 'event-based-asynchronous'),
        ('java-design-patterns', 'curiously-recurring-template-pattern'),
        ('java-design-patterns', 'adapter'),
        ('java-design-patterns', 'pipeline'),
        # ('java-design-patterns', 'presentation-model'),
        ('java-design-patterns', 'circuit-breaker'),
        ('java-design-patterns', 'factory-kit'),
        ('java-design-patterns', 'monitor'),
        ('java-design-patterns', 'double-dispatch'),
        ('java-design-patterns', 'single-table-inheritance'),
        ('java-design-patterns', 'unit-of-work'),
        ('java-design-patterns', 'event-queue'),
        ('java-design-patterns', 'factory'),
        # ('java-design-patterns', 'dependency-injection'),
        ('java-design-patterns', 'execute-around'),
        ('java-design-patterns', 'command'),
        ('java-design-patterns', 'spatial-partition'),
        # ('java-design-patterns', 'microservices-api-gateway'),
        ('java-design-patterns', 'feature-toggle'),
        ('java-design-patterns', 'composite-view'),
        ('java-design-patterns', 'parameter-object'),
        ('java-design-patterns', 'arrange-act-assert'),
        ('java-design-patterns', 'iterator'),
        ('java-design-patterns', 'lazy-loading'),
        ('easyexcel', 'easyexcel'),
        ('easyexcel', 'easyexcel-test'),
        ('easyexcel', 'easyexcel-support'),
        ('easyexcel', 'easyexcel-core'),
        # ('nacos', 'plugin'),
        ('nacos', 'plugin/environment'),
        ('nacos', 'plugin/trace'),
        ('nacos', 'plugin/datasource'),
        ('nacos', 'plugin/encryption'),
        ('nacos', 'plugin/config'),
        ('nacos', 'plugin/control'),
        ('nacos', 'plugin/auth'),
        ('nacos', 'common'),
        ('nacos', 'client'),
        # ('nacos', 'api'),
        # ('nacos', 'logger-adapter-impl'),
        ('nacos', 'logger-adapter-impl/log4j2-adapter'),
        ('nacos', 'logger-adapter-impl/logback-adapter-12'),
        ('nacos', 'consistency'),
        # ('nacos', 'plugin-default-impl'),
        ('nacos', 'plugin-default-impl/nacos-default-control-plugin'),
        # ('spring-boot-demo', 'demo-oauth'),
        # ('spring-boot-demo', 'demo-dubbo'),
        # ('spring-boot-demo', 'demo-dubbo/dubbo-common'),
        # ('spring-boot-demo', 'demo-admin'),
        ('WxJava', 'weixin-java-cp'),
        ('WxJava', 'weixin-graal'),
        # ('WxJava', 'spring-boot-starters'),
        ('WxJava', 'spring-boot-starters/wx-java-qidian-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-miniapp-multi-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-miniapp-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-channel-multi-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-cp-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-open-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-channel-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-mp-multi-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-mp-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-pay-spring-boot-starter'),
        ('WxJava', 'spring-boot-starters/wx-java-cp-multi-spring-boot-starter'),
        ('WxJava', 'weixin-java-miniapp'),
        ('WxJava', 'weixin-java-mp'),
        ('WxJava', 'weixin-java-pay'),
        ('WxJava', 'weixin-java-qidian'),
        ('WxJava', 'weixin-java-channel'),
        ('WxJava', 'weixin-java-open'),
        ('WxJava', 'weixin-java-common'),
        # ('WxJava', 'others/weixin-java-osgi'),
        # ('WxJava', 'solon-plugins'),
        ('WxJava', 'solon-plugins/wx-java-pay-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-open-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-cp-multi-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-miniapp-multi-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-channel-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-miniapp-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-cp-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-mp-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-channel-multi-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-qidian-solon-plugin'),
        ('WxJava', 'solon-plugins/wx-java-mp-multi-solon-plugin'),
        # ('zxing', 'core'),
        # ('zxing', 'zxing.appspot.com'),
        # ('zxing', 'javase')
    ]
    return modules

if __name__ == '__main__':
    main()