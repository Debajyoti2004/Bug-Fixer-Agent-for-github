import argparse
import shutil
import json
import os
from rich import print as rprint
from rich.panel import Panel

from code_base_kg import CodebaseKnowledgeGraph
from bug_fix_workflow import BugFixerWorkflow
import config

class BugFixingAgent:
    def __init__(self, repo_url: str, issue: str, clean_db: bool = False):
        self.repo_url = repo_url
        self.issue = issue
        self.local_path = "./temp_repo"
        
        rprint(Panel(f"[bold green]🚀 Initializing Bug Fixer Agent for {self.repo_url} 🚀[/bold green]"))

        self._prepare_local_environment(clean_db)
        
        self.kg_builder = CodebaseKnowledgeGraph(
            uri=config.NEO4J_URI,
            user=config.NEO4J_USERNAME,
            password=config.NEO4J_PASSWORD
        )

        self._prepare_knowledge_graph(clean_db)

    def _prepare_local_environment(self, clean_db: bool):
        if clean_db and os.path.exists(self.local_path):
            rprint(f"[bold yellow]--- 🗑️ Clearing local repository: {self.local_path} ---[/bold yellow]")
            shutil.rmtree(self.local_path)

    def _prepare_knowledge_graph(self, clean_db: bool):
        rprint("[bold blue]--- 🧠 Configuring Knowledge Graph ---[/bold blue]")
        if clean_db:
            rprint("[bold yellow]--- 🧹 Clearing existing database ---[/bold yellow]")
            self.kg_builder.clear_database()

        if not os.path.exists(self.local_path):
            rprint(f"[bold blue]--- 📊 Cloning repo and building knowledge graph... ---[/bold blue]")
            self.kg_builder.build_graph_from_repo(self.repo_url, self.local_path)
        else:
            rprint("[bold yellow]--- 📊 Knowledge graph build skipped. Use --clean to force a rebuild. ---[/bold yellow]")

    def run(self):
        try:
            self._execute_workflow()
        finally:
            self._cleanup()

    def _execute_workflow(self):
        rprint("\n[bold blue]--- 🤖 Initializing Bug Fixer Workflow ---[/bold blue]")
        workflow_runner = BugFixerWorkflow()
        
        initial_state = {
            "issue_summary": self.issue,
            "repo_url": self.repo_url,
            "local_path": self.local_path,
            "plan": [],
            "execution_results": [],
            "review_feedback": None,
            "current_task_status": ""
        }

        rprint("\n[bold magenta]>>> Starting Bug Fix Process <<<[/bold magenta]")
        final_state = workflow_runner.graph.invoke(initial_state)

        rprint(Panel("[bold green]🎉 Bug Fix Process Complete! 🎉[/bold green]"))
        
        final_plan_str = json.dumps(final_state.get('plan', 'N/A'), indent=2)
        rprint(Panel(final_plan_str, title="[bold]Final Plan[/bold]", border_style="green", expand=False))

        final_results_str = "\n".join(final_state.get('execution_results', ['N/A']))
        rprint(Panel(final_results_str, title="[bold]Final Execution Results[/bold]", border_style="cyan", expand=False))

    def _cleanup(self):
        rprint("\n[bold blue]--- 🧹 Commencing Cleanup ---[/bold blue]")
        if os.path.exists(self.local_path):
            shutil.rmtree(self.local_path)
            rprint(f"[bold yellow]🗑️  Removed local repository: {self.local_path}[/bold yellow]")
        
        self.kg_builder.close()
        rprint("[bold blue]🔌 Knowledge Graph connection closed.[/bold blue]")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Bug Fixer Agent using a Knowledge Graph-driven workflow.")
    parser.add_argument("--repo_url", type=str, required=True, help="URL of the target GitHub repository.")
    parser.add_argument("--issue", type=str, required=True, help="A detailed summary of the bug to be fixed.")
    parser.add_argument("--clean", action='store_true', help="Perform a clean run by deleting the local repo and Neo4j database.")
    
    args = parser.parse_args()
    
    agent = BugFixingAgent(repo_url=args.repo_url, issue=args.issue, clean_db=args.clean)
    agent.run()