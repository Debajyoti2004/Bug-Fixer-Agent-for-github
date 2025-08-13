from langchain.tools import tool
from neo4j import GraphDatabase
import config

class Neo4jGraphTools:
    def __init__(self):
        self._driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD))

    def _execute_query(self, query):
        with self._driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

    def query_code_graph(self, query: str) -> str:
        try:
            result = self._execute_query(query)
            return str(result)
        except Exception as e:
            return f"Error executing query: {e}"