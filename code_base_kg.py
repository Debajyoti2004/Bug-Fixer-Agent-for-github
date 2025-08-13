import os
import ast
import json
from neo4j import GraphDatabase
import git

class CodebaseKnowledgeGraph:
    def __init__(self, uri, user, password):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    def _execute_query(self, query, parameters=None):
        with self._driver.session() as session:
            result = session.run(query, parameters)
            return [record for record in result]

    def clear_database(self):
        self._execute_query("MATCH (n) DETACH DELETE n")

    def build_graph_from_repo(self, repo_url, local_path):
        if not os.path.exists(local_path):
            git.Repo.clone_from(repo_url, local_path)

        for root, _, files in os.walk(local_path):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    self._parse_and_ingest_file(file_path, local_path)

    def _parse_and_ingest_file(self, file_path, base_path):
        relative_path = os.path.relpath(file_path, base_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            try:
                tree = ast.parse(content)
            except SyntaxError:
                return

        self._execute_query("MERGE (f:File {path: $path})", parameters={'path': relative_path})

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._ingest_class(node, relative_path)
            elif isinstance(node, ast.FunctionDef):
                self._ingest_function(node, relative_path)
            elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                self._ingest_import(node, relative_path)

    def _ingest_class(self, node, file_path):
        class_name = node.name
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (c:Class {name: $class_name, file_path: $file_path})
        MERGE (f)-[:CONTAINS]->(c)
        """
        self._execute_query(query, {'file_path': file_path, 'class_name': class_name})

    def _ingest_function(self, node, file_path):
        function_name = node.name
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (func:Function {name: $function_name, file_path: $file_path})
        MERGE (f)-[:CONTAINS]->(func)
        """
        self._execute_query(query, {'file_path': file_path, 'function_name': function_name})

    def _ingest_import(self, node, file_path):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                query = """
                MATCH (f:File {path: $file_path})
                MERGE (m:Module {name: $module_name})
                MERGE (f)-[:IMPORTS]->(m)
                """
                self._execute_query(query, {'file_path': file_path, 'module_name': module_name})
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module
            query = """
            MATCH (f:File {path: $file_path})
            MERGE (m:Module {name: $module_name})
            MERGE (f)-[:IMPORTS]->(m)
            """
            self._execute_query(query, {'file_path': file_path, 'module_name': module_name})

    def save_successful_plan(self, issue_summary: str, plan: list, file_paths: list):
        plan_json = json.dumps(plan)
        query = """
        CREATE (p:Plan {issue_summary: $issue_summary, steps: $plan_json})
        WITH p
        UNWIND $file_paths AS file_path
        MATCH (f:File {path: file_path})
        MERGE (p)-[:APPLIES_TO_FILE]->(f)
        RETURN p
        """
        self._execute_query(query, {
            'issue_summary': issue_summary,
            'plan_json': plan_json,
            'file_paths': file_paths
        })

    def find_successful_plan(self, issue_summary: str):
        query = """
        MATCH (p:Plan)
        RETURN p.issue_summary AS issue, p.steps AS plan
        ORDER BY rand()
        LIMIT 1
        """
        result = self._execute_query(query)

        if not result:
            return None
        
        record = result[0]
        try:
            plan_steps = json.loads(record['plan'])
            return {"issue": record['issue'], "plan": plan_steps}
        except (json.JSONDecodeError, TypeError):
            return None