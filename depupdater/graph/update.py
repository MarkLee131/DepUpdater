"""update dependency graph after computing the newest compatible version of a dependency"""
from collections import deque, defaultdict
from depupdater.database.query import query_dependencies_from_mongo, insert_dependencies_into_mongo
from depupdater.database.populate import populate_dep
from depupdater.log import log_debug
class Update:

    def __init__(self, cur_node:dict, graph:list, queue:deque, old_deps:list):
        """
        Args:
            cur_node (dict): the node in graph that has been computed and validated
            graph (list): the dependency graph, a list of dict
            queue (deque): the queue that stores the dependencies can be computed(all dependents have been computed)
            old_deps (list): the old dependencies of cur_node
        """
        self.cur_node = cur_node
        self.graph = graph
        # queue is used to store the nodes that can be
        # computed(all dependents have been computed) and need to be computed(node itself is not computed)
        self.queue = queue
        # dict of old_deps; groupId:artifactId -> index
        self.old_dict = self.get_old_deps_dict(old_deps)
        # dict of graph; groupId:artifactId -> index
        self.graph_dict = self.get_graph_dict()
        # dict of new new_deps; groupId:artifactId -> [version, type]
        self.new_dict = self.query_dependencies(self.cur_node['GroupId'], self.cur_node['ArtifactId'], \
            self.cur_node['Best_Version'])
        # dict of queue; groupId:artifactId -> dep dict in queue
        self.queue_dict = self.get_queue_dict()

    def get_queue_dict(self):
        """transform queue from a deque of dicts to a dict of groupId:artifactId -> dep dict in queue
        Returns:
            queue (dict): the dependencies in the queue; groupId:artifactId -> dep dict in queue
        """
        queue_dict = {}
        if self.queue is None:
            self.queue = deque()
            return queue_dict
        for dep in self.queue:
            queue_dict[dep['GroupId']+':'+dep['ArtifactId']] = dep
        return queue_dict

    def get_old_deps_dict(self, old_deps:list):
        """transform old_deps from a list of dicts to a dict of groupId:artifactId -> index
        Args:
            old_deps (list): the old dependencies of cur_node
            consisting of dicts
            {
                'GroupId': str,
                'ArtifactId': str
            }
        Returns:
            old (dict): the old dependencies of cur_node; groupId:artifactId -> index
        """
        old = {}
        for old_dep in old_deps:
            for i, dep in enumerate(self.graph):
                if dep['GroupId'] == old_dep['GroupId'] and dep['ArtifactId'] == old_dep['ArtifactId']:
                    old[old_dep['GroupId']+':'+old_dep['ArtifactId']] = i
                    break
        return old

    def get_graph_dict(self):
        """transform graph from a list of dicts to a dict of groupId:artifactId -> index
        Returns:
            graph (dict): the dependency graph; groupId:artifactId -> index
        """
        graph = {}
        for i, dep in enumerate(self.graph):
            depth = dep['Depth']
            if depth > 0 and not dep['Dependents']:
                # the node is not client and has no dependents
                # means the node is not in graph actually
                continue
            graph[dep['GroupId']+':'+dep['ArtifactId']] = i
        return graph

    def query_dependencies(self, groupId:str, artifactId:str, version:str):
        """query the dependencies of the cur_node from the database
        1. get new_deps from mongodb;
        2. filter gav and type of the new_deps;
        3. transform new_deps from a list of dicts to a dict of groupId:artifactId -> [version, type]
        """
        # query the dependencies of the cur_node from the database
        dependencies = query_dependencies_from_mongo(groupId, artifactId, version)
        if dependencies is None:
            # the dependencies of the cur_node are not in the database
            # get the dependencies and store them in the database
            dependencies = populate_dep(groupId, artifactId, version)
            insert_dependencies_into_mongo(groupId, artifactId, version, dependencies)
        dependencies_dict = self.filter_dep(dependencies)
        return dependencies_dict

    def filter_dep(self, dependencies:list):
        """filter the new dependencies of the cur_node:
        1. remove the dependencies that are not compile or runtime
        2. remove the dependencies that are optional and not the direct dependency of the client
        Returns:
            dependencies_dict (dict): the dependencies of the cur_node; groupId:artifactId -> [version, type]
        """
        dependencies_dict = {}
        for dependency in dependencies:
            gav = dependency['dep']
            # g,a,v is splited by the first two ':' of gav
            g, a, v = gav.split(':', 2)
            if dependency['dScope'] != 'compile' and dependency['dScope'] != 'runtime':
                continue
            if dependency['isoptional'] == 'true':
                # check if the dependency is the direct dependency of the client
                # ignore it if not
                if f'{g}:{a}' in self.graph_dict:
                    index = self.graph_dict[f'{g}:{a}']
                    depth = self.graph[index]['Depth']
                    if depth == 1:
                        dependencies_dict[f'{g}:{a}'] = [f'{v}', dependency['dScope']]
                continue
            dependencies_dict[f'{g}:{a}'] = [f'{v}', dependency['dScope']]
        return dependencies_dict

    def update(self, old_best_version:str):
        """main method to update the dependency graph and the queue after computing the newest compatible version of a dependency"""
        new = set(self.new_dict.keys())
        old = set(self.old_dict.keys())
        if old_best_version == self.cur_node['Best_Version']:
            # the best version of the dependency is unchanged
            # no need to use the new dependencies
            self.update_nodes(old)
        else:
            # handle new & old, which means the unchanged edges
            self.update_nodes(new & old)
            # handle new - old, which means the new edges
            self.add_edges(new - old)
            # handle old - new, which means the removed edges
            self.remove_edges(old - new)

    def update_nodes(self, ga_set:set):
        """situation 1: the dependency is in both old_deps and new_deps
        the edges in dependency graph are unchanged
        """
        best_version = self.cur_node['Best_Version']
        ga_list = sorted(ga_set) # transform into list for reproducibility
        # for ga in ga_set:
        for ga in ga_list:
            idx = self.graph_dict[ga]
            dep_dict = self.graph[idx]
            # update graph
            for dependent in dep_dict['Dependents']:
                if self.cur_node['GroupId'] == dependent['GroupId'] and self.cur_node['ArtifactId'] == dependent['ArtifactId']:
                    # update the version of the dependent and the defined version(of this dep) by the dependent
                    if dependent['Version'] != best_version:
                        dependent['Version'] = best_version
                        # the best version of the dependent recorded by this dependency is outdated
                        # dep_dict['Best_Version'] = ""
                        self.clear_best_version(dep_dict, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])
                        dependent['Define_Version'] = self.new_dict[ga][0]
                    break

            # update queue
            # 1. compute the in-degree to judge if the dependency is ready to be computed
            flag = self.is_ready(ga)
            # 2. update queue by the in-degree(whether bigger than 0) and dep ga
            self.update_queue(flag, ga, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])

    def add_edges(self, ga_set:set):
        """situation 2: the dependency is in new_deps but not in old_deps
        add new edges to the dependency graph and add new nodes if necessary
        """
        ga_list = sorted(ga_set)
        # for ga in ga_set:
        for ga in ga_list:
            # update graph, add the new dependent to the dependency
            if ga in self.graph_dict:
                # ga in the graph, so no need to add new nodes
                idx = self.graph_dict[ga]
                dep_dict = self.graph[idx]

                # # add the edge if not introducing a cycle
                # if not self.node_reachability(ga, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId']):
                dep_dict['Dependents'].append(
                    {
                        "GroupId": self.cur_node['GroupId'],
                        "ArtifactId": self.cur_node['ArtifactId'],
                        "Version": self.cur_node['Best_Version'],
                        "Define_Version": self.new_dict[ga][0]
                    }
                )

                log_debug(f'{ga} is a new dep of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]} now')

                # clear the best version of this dependency as its context has changed
                # dep_dict['Best_Version'] = ""
                self.clear_best_version(dep_dict, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])
                flag = self.is_ready(ga)
                self.update_queue(flag, ga, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])
                # else:
                #     log_debug(f'Introducing a cycle by adding {ga} as a dep of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]}, so quit')
            else :
                ga_version = self.new_dict[ga][0]
                ga_type = self.new_dict[ga][1]
                # ga not in the graph, so need to add new nodes recursively
                self.add_node(ga, self.cur_node['GroupId'], self.cur_node['ArtifactId'], ga_version, ga_type)

    def add_node(self, ga:str, dependent_g:str, dependent_a:str, version:str, Dtype:str)->bool:
        """add the node and its outer-edges to the dependency graph recursively
        helper method for add_edges
        Args:
            ga (str): the groupId:artifactId of the new node
            dependent_g (str): the groupId of the dependent that induces the new node
            dependent_a (str): the artifactId of the dependent that induces the new node
            version (str): the version of the new node
            Dtype (str): the type of the new node
        Returns:
            flag (bool): if the new node need further process
            new_node (dict): the new node added to the graph
        """
        log_debug(f'{ga} added by {dependent_g}:{dependent_a}')

        groupId, artifactId = ga.split(':')
        # version = self.new_dict[ga][0]
        # Dtype = self.new_dict[ga][1]
        dependent_ga = dependent_g + ':' + dependent_a
        dependent_idx = self.graph_dict[dependent_ga]
        dependent_node = self.graph[dependent_idx]
        if not self.is_computed(dependent_ga):
            # the dependent is also a new node added before
            dependent_version = self.graph[dependent_idx]['Original_Version']
        else:
            # the dependent is the node computed before
            dependent_version = self.graph[dependent_idx]['Best_Version']
        # add node to the graph
        # traverse the graph
        existing_in_list = False
        for i, node in enumerate(self.graph):
            if node['GroupId'] == groupId and node['ArtifactId'] == artifactId:
                # the node is removed before and need to be added again
                existing_in_list = True
                node['Dependents'].append({
                    "GroupId": dependent_g,
                    "ArtifactId": dependent_a,
                    "Version": dependent_version,
                    "Define_Version": version
                })
                depth = min(dependent_node['Depth'] + 1, node['Depth'])
                node['Depth'] = depth
                # node['Best_Version'] 
                self.clear_best_version(node, dependent_ga)
                node['Type'] = Dtype
                # add the node to graph_dict
                self.graph_dict[ga] = i
                break
        if not existing_in_list:
            # the node is not removed before
            # add the node to the graph_list as well as the list
            new_node = {
                "GroupId": groupId,
                "ArtifactId": artifactId,
                "Original_Version": version,
                "Best_Version": "",
                "Type": Dtype,
                "Depth": dependent_node['Depth'] + 1,
                "Count": 0,
                "Dependents": [
                    {
                        "GroupId": dependent_g,
                        "ArtifactId": dependent_a,
                        "Version": dependent_version,
                        "Define_Version": version
                    }
                ]
            }
            self.graph.append(new_node)
            self.graph_dict[ga] = len(self.graph) - 1

        # add new outer-edges
        new_deps_dict = self.query_dependencies(groupId, artifactId, version)
        for new_dep_ga, new_dep_inform in new_deps_dict.items():
            if new_dep_ga in self.graph_dict:
                # the new dependency is in the graph
                # add the new dependent to the new
                idx = self.graph_dict[new_dep_ga]
                new_dep = self.graph[idx]
                
                # # add the edge if not introducing a cycle
                # if not self.node_reachability(new_dep_ga, ga):
                new_dep['Dependents'].append(
                    {
                        "GroupId": groupId,
                        "ArtifactId": artifactId,
                        "Version": version,
                        "Define_Version": new_dep_inform[0]
                    }
                )

                log_debug(f'{new_dep_ga} is a new dep of {groupId}:{artifactId} now')

                # clear the best version of this dependency as its context has changed
                # new_dep['Best_Version'] = ""
                self.clear_best_version(new_dep, f'{groupId}:{artifactId}')
                # update the queue
                flag = self.is_ready(new_dep_ga)
                self.update_queue(flag, new_dep_ga, f'{groupId}:{artifactId}')
                # else:
                #     log_debug(f'Introducing a cycle by adding {new_dep_ga} as a dep of {groupId}:{artifactId}, so quit')
            else:
                # the new dependency is not in the graph
                # add new nodes recursively
                self.add_node(new_dep_ga, groupId, artifactId, new_dep_inform[0], new_dep_inform[1])

        # judge if need to add the new node to the queue
        flag = self.is_ready(ga)
        self.update_queue(flag, ga, dependent_ga)

    def node_reachability(self, ga_start, ga_end):
        """check whether there exists a path from ga_start to ga_end in dependency graph
        if ga_end is reachable from ga_start, then an edge from ga_end to ga_start will introduce a cycle
        Returns:
            reachable (bool): if ga_end is reachable from ga_start
        """
        # dfs from ga_end to ga_start as node stores dependents rather than dependencies
        def dfs(v, visited, ga_start):
            visited[v] = True
            if v == ga_start:
                return True
            for dependent in self.graph[self.graph_dict[v]]['Dependents']:
                dependent_ga = dependent['GroupId'] + ':' + dependent['ArtifactId']
                if not visited[dependent_ga]:
                    if dfs(dependent_ga, visited, ga_start):
                        return True
            return False
        visited = {node:False for node in self.graph_dict}
        return dfs(ga_end, visited, ga_start)

    def remove_edges(self, ga_set:set):
        """situation 3: the dependency is in old_deps but not in new_deps
        remove some edges (and some nodes if necessary)in the dependency graph
        """
        ga_list = sorted(ga_set)
        # for ga in ga_set:
        for ga in ga_list:
            # update graph, remove the dependent from the dependency
            idx = self.graph_dict[ga]
            dep_dict = self.graph[idx]
            for dependent in dep_dict['Dependents']:
                if self.cur_node['GroupId'] == dependent['GroupId'] and self.cur_node['ArtifactId'] == dependent['ArtifactId']:
                    dep_dict['Dependents'].remove(dependent)

                    log_debug(f'{ga} is not a dep of {self.cur_node["GroupId"]}:{self.cur_node["ArtifactId"]} now')

                    break

            # the best version of the dependent recorded by this dependency is outdated
            # dep_dict['Best_Version'] = ""
            self.clear_best_version(dep_dict, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])

            # if the ga has no dependents now, remove the node from the graph
            if not dep_dict['Dependents']:
                self.remove_node(ga, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])
            
            # note : queue is always updated after updating the graph
            # update queue after deleting an edge
            flag = self.is_ready(ga)
            self.update_queue(flag, ga, self.cur_node['GroupId']+':'+self.cur_node['ArtifactId'])

    def remove_node(self, ga:str, dependent_ga:str):
        """remove the node and its outer-edges from the dependency graph recursively
        helper method for remove_edges; also updated the queue
        Args:
            ga (str): the groupId:artifactId of the dependency
            which should be removed from the graph
        """
        log_debug(f'{ga} is removed by {dependent_ga}')

        # handle the dependencies of ga first
        for node in self.graph:
            is_dependent = False
            dependent_idx = -1
            for idx, dependent in enumerate(node['Dependents']):
                if ga == dependent['GroupId']+':'+dependent['ArtifactId']:
                    # ga is a dependent of node
                    is_dependent = True
                    dependent_idx = idx
                    break
            if is_dependent:
                # remove ga from the dependents of node
                node['Dependents'].pop(dependent_idx)

                log_debug(f'{node["GroupId"]}:{node["ArtifactId"]} is not a dep of {ga} now')

                node_ga = node['GroupId']+':'+node['ArtifactId']

                if not node['Dependents']:
                    # if the node has no dependents now, remove the node from the graph
                    self.remove_node(node_ga, ga)
                else :
                    # just update queue and on need to remove node_ga from the graph
                    # also means, the graph has been updated, so the queue could be updated
                    flag = self.is_ready(node_ga)
                    self.update_queue(flag, node_ga, ga)

        # remove the node in graph_dict
        self.graph_dict.pop(ga)
        # remove the node from the queue if it is in the queue
        self.update_queue(False, ga, dependent_ga)

    def update_queue(self, is_ready:bool, ga:str, dependent_ga:str):
        """update the queue after updating the dependency graph
        Args:
            is_ready (bool): if the dependency is ready to be computed(all dependents have been computed)
            ga (str): the groupId:artifactId of the dependency
        """
        # first, check if the dep in the queue are all ready to be computed,
        # because may be some dependent of the dep in the queue are cleared, so the dep in the queue should be removed
        for dep in list(self.queue): # a copy of list is used to avoid the RuntimeError: deque mutated during iteration
            dep_ga = dep['GroupId'] + ':' + dep['ArtifactId']
            if not self.is_ready(dep_ga):
                # the dependency is not ready to be computed
                # remove the dependency from the queue
                self.queue.remove(dep)
                self.queue_dict.pop(dep_ga)

                log_debug(f"{dep_ga} dequeue because it shoud not be computed now")
        # whether the dependency is in the queue
        is_in = ga in self.queue_dict
        if is_ready and not is_in:
            # the dependency is ready to be computed and not in the queue
            # add the dependency to the queue
            # self.log_queue()

            self.queue.append(self.graph[self.graph_dict[ga]])
            self.queue_dict[ga] = self.graph[self.graph_dict[ga]]

            log_debug(f"{ga} enqueue because of {dependent_ga}.")
            # the remaining nodes may be the dependency of the new node, which should be removed from the queue
            # to guarantee all the nodes in the queue are ready to be computed
            
        elif not is_ready and is_in:
            # the dependency is not ready to be computed and in the queue
            # remove the dependency from the queue
            self.queue.remove(self.queue_dict[ga])
            self.queue_dict.pop(ga)

            log_debug(f"{ga} dequeue because of {dependent_ga}.")

    def is_ready(self, ga:str):
        """judge if ga should be stored in the queue
        if the in-degree is 0 and the dependency is not computed, return True; if in-degree is bigger than 0, return False
        note: 
        Args:
            ga (str): the groupId:artifactId of the dependency
        """
        # client is no need to be computed
        
        if ga not in self.graph_dict:
            return False
        if self.is_computed(ga):
            # if the dependency is computed, return False
            # as it is not necessary to compute it again
            return False
        dep = self.graph[self.graph_dict[ga]]
        dependents_list = dep['Dependents']
        if not dependents_list:
            # the dependency is not in the graph actually
            # something goes wrong as the dependency in graph should have dependents except the client
            print(f"Dependency {ga} is not in the graph actually, something goes wrong.")
            exit(1)
        for dependent in dependents_list:
            dependent_g = dependent['GroupId']
            dependent_a = dependent['ArtifactId']
            if not self.is_computed(f'{dependent_g}:{dependent_a}'):
                # a dependent is not computed
                return False
        return True

    def is_computed(self, ga):
        """check if the dependency is computed yet
        Args:
            ga (str): the groupId:artifactId of the dependency
        """
        dep_dict = self.graph[self.graph_dict[ga]]
        if dep_dict['Best_Version'] == "":
            return False
        return True

    def log_queue(self):
        """log the queue"""
        log_debug("Queue:")
        for ga in self.queue_dict.keys():
            log_debug(f" {ga}")

    @staticmethod
    def clear_best_version(dep_dict:dict, dependent_ga:str):
        """clear the best version of a dependency unless it is the client"""
        backtracking_flag = True # set False to disable backtracking in RQ2 - ablation experiments
        if backtracking_flag:
            if dep_dict['Depth'] != 0:
                log_debug(f"Clear the best version of {dep_dict['GroupId']}:{dep_dict['ArtifactId']} because of {dependent_ga}.")
                dep_dict['Best_Version'] = ""
        else:
            # disable backtracking_flag for RQ2 ---> don't clear the best version 
            # to let dep_dict back to queue for computing again even if it's dependents(context) have changed
            return