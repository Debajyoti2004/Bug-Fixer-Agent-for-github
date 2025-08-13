import cohere
import json
import subprocess
from langgraph.graph import StateGraph, END
from rich.panel import Panel
from rich import print as rprint

from agent_state import AgentState
from graph_tools import Neo4jGraphTools
from file_system_tools import read_file, write_file, list_files
from code_base_kg import CodebaseKnowledgeGraph
import config
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


class BugFixerWorkflow:
    def init(self):
        self.cohere_client = cohere.Client(api_key=config.COHERE_API_KEY)
        self.gemini_llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0)
        self.graph_tools = Neo4jGraphTools()
        self.kg_builder = CodebaseKnowledgeGraph(
            uri=config.NEO4J_URI,
            user=config.NEO4J_USERNAME,
            password=config.NEO4J_PASSWORD
        )

        self._initialize_tool_map()
        self._initialize_prompts()
        self._initialize_cohere_tools()
        self.graph = self._build_graph()

    def _initialize_tool_map(self):
        self.tool_map = {
            "query_code_graph": self.graph_tools.query_code_graph,
            "read_file": read_file,
            "write_file": write_file,
            "list_files": list_files,
        }

    def _initialize_cohere_tools(self):
        self.cohere_tools = [
            {
                "name": "query_code_graph",
                "description": "Executes a Cypher query against the Neo4j codebase graph to understand code structure.",
                "parameter_definitions": {
                    "query": {
                        "description": "The Cypher query to execute.",
                        "type": "string",
                        "required": True,
                    }
                },
            },
            {
                "name": "read_file",
                "description": "Reads the content of a specified file from the local project.",
                "parameter_definitions": {
                    "file_path": {
                        "description": "The path to the file.",
                        "type": "string",
                        "required": True,
                    }
                },
            },
            {
                "name": "write_file",
                "description": "Writes or overwrites content to a specified file in the local project.",
                "parameter_definitions": {
                    "file_path": {
                        "description": "The path to the file to write.",
                        "type": "string",
                        "required": True,
                    },
                    "content": {
                        "description": "The new content for the file.",
                        "type": "string",
                        "required": True,
                    },
                },
            },
            {
                "name": "list_files",
                "description": "Lists all files and directories in a given project directory.",
                "parameter_definitions": {
                    "directory": {
                        "description": "The directory to list. Defaults to the root.",
                        "type": "string",
                        "required": False,
                    }
                },
            },
        ]

    def _initialize_prompts(self):
        self.planner_preamble = """
🧠⚡ [PLANNER MODE] Autonomous Senior AI Engineering Lead ⚡🧠
🎯 MISSION:  
Design a precise, executable, and failure-proof plan to fix the reported bug, add a feature, or handle any kind of code, data, or environment issue — even if context is incomplete, requirements are vague, or dependencies are missing.
---
🛠 CORE SUPERPOWERS:
- 🐞 Bug Forensics → Trace, isolate, and diagnose root causes from logs, stack traces, or indirect behavior changes.  
- 🗺 Codebase Navigation → Explore architecture via query_code_graph to map dependencies, relationships, and usage patterns.  
- 🔄 Cross-File Refactoring → Safely modify multiple interconnected files while preserving existing behavior.  
- 🧩 Dependency Recovery → Detect & restore missing imports, libraries, configs, or environment mismatches.  
- 🛡 Risk-Aware Execution → Prevent regression, anticipate side effects, and maintain backward compatibility.  
- 📈 Performance Awareness → Optimize only if it doesn’t break functional correctness.
---
📜 EXECUTION METHODOLOGY:  
1️⃣ 🧐 Problem Understanding  
   - Parse the issue/request.  
   - Infer missing details from code graph and file inspection.  
   - Pinpoint probable root cause(s).  
2️⃣ 🔍 Code Graph Analysis  
   - Use query_code_graph to locate definitions, usages, and call relationships.  
   - Identify all affected files, modules, and integration points.  
3️⃣ 📂 File Content Inspection  
   - Use read_file to review exact code segments.  
   - Verify assumptions before making edits.  
4️⃣ 🛠 Strategic Fix Plan  
   - Sequence tool calls logically from diagnosis → implementation → verification.  
   - Ensure every write_file contains complete, correct, and ready-to-run code.  
   - Use list_files or additional graph queries for hidden dependencies.  
5️⃣ 🛡 Risk Mitigation  
   - Avoid unrelated changes.  
   - Account for integration points and existing features.  
6️⃣ 🔁 Verification Readiness  
   - Ensure changes are testable immediately.  
   - Include any post-change validation if needed.  
---
⚠ FINAL OUTPUT RULES:  
- Respond ONLY with a JSON array of tool calls — no explanations, no prose.  
- Every tool call must have exact parameters.  
- Steps must be in execution order.  
- Cover all steps from exploration to final fix readiness.
💡 REMEMBER:  
- If input is ambiguous → Explore before editing.  
- If multiple approaches exist → Choose safest & most complete.  
- If environment/system issue → Include inspection & repair steps.  
"""

        self.reviser_prompt_template = """
🔄🛠 [REVISION MODE] Adaptive Senior AI Engineer 🛠🔄
📌 Incoming Change Request / Reviewer Feedback:  
"{user_command}"
📜 Previous Plan for Similar Issue (‘{old_issue}’):  
{cached_plan}
---
🎯 MISSION:  
Refine or rebuild the fix plan to handle:  
- 🆕 New constraints, requirements, or environment conditions.  
- ❌ Failures from prior execution.  
- 🛠 Missing files, altered dependencies, or broken steps.  
- ⚠ Partial relevance of old plan — adapt accordingly.  
- ⛔ If old plan is irrelevant → Create a completely new plan from scratch using the full methodology.
---
📜 REVISION PROTOCOL:  
1️⃣ Analyze Feedback → Understand exactly what needs fixing or changing.  
2️⃣ Re-Validate → Use code graph & file inspection if needed.  
3️⃣ Repair & Reorder → Modify existing steps or insert new ones.  
4️⃣ Remove Failures → Drop steps that are invalid, redundant, or incorrect.  
5️⃣ Ensure Completeness → Plan must still cover diagnosis → fix → validation.  
---
⚠ FINAL OUTPUT RULES:  
- Respond ONLY with a JSON array of tool calls — no explanations.  
- Include all required file reads, queries, and writes in proper order.  
- Plan must be immediately executable without missing context.  
- Ensure every tool call has the exact parameters it needs.  
"""
    
        self.failure_reviser_prompt_template = """
# 🚨🛠 [RECOVERY MODE] Autonomous Senior AI Engineering Lead 🛠🚨

**CRITICAL ALERT:** The previous attempt to fix the issue has FAILED review.  
You must perform **deep failure forensics** and produce a **new, flawless execution plan**.

## 🔍 FAILURE ANALYSIS DOSSIER

### 1️⃣ Original Mission:
"{issue_summary}"

### 2️⃣ Failed Plan (JSON Format):
{failed_plan}

### 3️⃣ Execution Logs & Results:
{execution_results}

### 4️⃣ QA Reviewer's Verdict (Reason for Failure):
"{review\_feedback}"

## 🎯 NEW MISSION DIRECTIVES:

1. **Root Cause Diagnosis (🧬)**

   * Conduct a full **post-mortem** of the failure.
   * Identify *exactly* why the plan failed:

     * ❌ Logical flaw in approach
     * ❌ Wrong file paths or filenames
     * ❌ Incorrect code syntax or logic
     * ❌ Missing dependencies or imports
     * ❌ Partial fix that didn’t address all affected areas
     * ❌ Introduced regressions or new errors
   * Include all contextual clues from the logs & reviewer feedback.

2. **Strategic Overhaul (⚙️)**

   * **Do NOT** simply patch the old plan.
   * Engineer a **completely new, robust, and logically airtight plan**.
   * Ensure your plan covers **diagnosis → fix → validation** in one continuous flow.
   * Anticipate *all* related edge cases and avoid repetition of failed steps.

3. **Context Integration (🧠)**

   * Leverage insights from the failed attempt to avoid prior mistakes.
   * Map out any missing intermediate steps.
   * If applicable, expand the scope to cover upstream/downstream dependencies.

4. **Tool Mastery (🔧)**

   * Use all available tools effectively:

     * `query_code_graph` → Investigate architecture & dependencies
     * `read_file` → Inspect relevant files
     * `write_file` → Apply complete, tested code changes
     * `list_files` → Identify file locations & structures
   * Maintain logical sequence in tool calls.

5. **Risk Mitigation (🛡)**

   * Prevent regressions.
   * Consider compatibility with other modules.
   * Ensure every change is self-contained and reversible if needed.

## ⚠ FINAL OUTPUT RULES (Non-Negotiable):

* Respond **ONLY** with a valid JSON array of new tool calls.
* **No** explanations, markdown, or extra commentary—just the raw executable plan.
* The plan must:

  * Contain **all required parameters** for each tool call.
  * Be **logically ordered** for flawless execution.
  * Avoid any step that directly replicates failed logic from the previous plan.
  * Contain **only complete, functional, and ready-to-run** changes.

"""

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("planner", self.plan_step)
        workflow.add_node("executor", self.execute_step)
        workflow.add_node("reviewer", self.review_step)
        workflow.add_node("save_plan", self.save_plan_step)

        workflow.set_entry_point("planner")

        workflow.add_edge("planner", "executor")
        workflow.add_edge("executor", "reviewer")
        workflow.add_conditional_edges(
            "reviewer",
            self.should_continue,
            {"continue": "planner", "end": "save_plan"},
        )
        workflow.add_edge("save_plan", END)

        return workflow.compile()

    def _run(self, args, check=True, capture_output=False, text=True):
        return subprocess.run(args, check=check, capture_output=capture_output, text=text)

    def _commit_and_push(self, commit_message):
        try:
            status = self._run(["git", "status", "--porcelain"], capture_output=True).stdout.strip()
            if not status:
                rprint("[yellow]No changes to commit.[/yellow]")
                return

            self._run(["git", "add", "."])
            self._run(["git", "commit", "-m", commit_message])
            branch = self._run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True
            ).stdout.strip()
            self._run(["git", "push", "origin", branch])

            rprint("[bold green]✅ Changes committed and pushed.[/bold green]")
        except subprocess.CalledProcessError as e:
            rprint(f"[bold red]❌ Git error: {e}[/bold red]")

    def plan_step(self, state: AgentState):
        rprint("[bold blue]--- 📝 Planning Step (Cohere) ---[/bold blue]")

        issue = state["issue_summary"]
        review_feedback = state.get("review_feedback")
        preamble = self.planner_preamble
        
        if review_feedback and "❌ REVISE" in review_feedback:
            rprint(Panel(
                f"[bold red]RECOVERY MODE ACTIVATED[/bold red]\n"
                f"Analyzing failure based on reviewer feedback:\n"
                f"{review_feedback}",
                title="Plan Revision",
                border_style="red"
            ))
            message = self.failure_reviser_prompt_template.format(
                issue_summary=issue,
                failed_plan=json.dumps(state.get("plan", []), indent=2),
                execution_results="\n".join(state.get("execution_results", [])),
                review_feedback=review_feedback
            )
        else:
            message = issue
            cached_plan_data = self.kg_builder.find_successful_plan(issue)
            if cached_plan_data:
                rprint(
                    Panel(
                        f"[bold green]🧠 Found a similar plan for issue:[/bold green] '{cached_plan_data['issue']}'\n"
                        "[bold green]Revising it for the current needs...[/bold green]",
                        title="Knowledge Graph Hit",
                        border_style="green",
                    )
                )
                message = self.reviser_prompt_template.format(
                    user_command=issue,
                    old_issue=cached_plan_data["issue"],
                    cached_plan=json.dumps(cached_plan_data["plan"], indent=2),
                )
        try:
            response = self.cohere_client.chat(
                message=message,
                tools=self.cohere_tools,
                model="command-r",
                preamble=preamble,
            )
            plan = []
            if getattr(response, "tool_calls", None):
                plan = [{"tool_name": call.name, "parameters": call.parameters} for call in response.tool_calls]
            rprint(Panel(json.dumps(plan, indent=2), title="[bold]Generated Plan[/bold]", border_style="cyan"))
            return {"plan": plan, "execution_results": [], "review_feedback": None}

        except Exception as e:
            rprint(f"[bold red]Error during planning: {e}[/bold red]")
            return {"plan": [], "review_feedback": None}
        
    def execute_step(self, state: AgentState):
        rprint("[bold blue]--- 👨‍💻 Execution Step ---[/bold blue]")

        plan = state.get("plan", [])
        results = []

        for i, step in enumerate(plan):
            tool_name = step.get("tool_name")
            params = step.get("parameters", {})
            rprint(f"Executing step {i+1}/{len(plan)}: [bold yellow]{tool_name}[/bold yellow] with params {params}")

            tool_function = self.tool_map.get(tool_name)
            if not tool_function:
                result = f"Error: Tool '{tool_name}' not found."
            else:
                try:
                    result = tool_function(**params)
                except Exception as e:
                    result = f"Error executing tool '{tool_name}': {e}"

            results.append(str(result))
            rprint(f"Result: {str(result)[:500]}")

        return {"execution_results": results}

    def review_step(self, state: AgentState):
        rprint("[bold blue]--- 🕵️‍♀️ Review Step (Gemini) ---[/bold blue]")

        plan_str = json.dumps(state.get("plan", []), indent=2)
        programmer_summary = (
            "Executed the following plan:\n"
            + plan_str
            + "\n\nExecution Results:\n"
            + "\n".join(state.get("execution_results", []))
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
As an automated AI Quality Assurance system (QA-Gemini), you must perform a strict, logical review of the work done.
INPUT:
1. The Original Plan (📝): The set of tool calls the programmer was supposed to execute.
2. The Programmer's Work & Results (💻): A summary of the execution and the output from each tool call.
ANALYSIS PROTOCOL:
1. Plan vs. Implementation: Review the execution results. Did the steps run successfully or produce errors?
2. Logical Soundness: Based on the plan and the results, is the original bug likely resolved?
3. Integrity Check: Do the execution logs indicate any new, obvious errors?
OUTPUT FORMAT:
- If the implementation appears successful, your response MUST be the single token: ✅ COMPLETE
- If there is any deviation, flaw, or error, your response MUST start with ❌ REVISE, followed by a brief, technical reason for the failure.
""",
                ),
                (
                    "human",
                    "THE ORIGINAL PLAN:\n{plan}\n\nTHE PROGRAMMER'S WORK & RESULTS:\n{code_changes}\n\nReview the work now.",
                ),
            ]
        )
        chain = prompt | self.gemini_llm | StrOutputParser()
        review_content = chain.invoke({"plan": plan_str, "code_changes": programmer_summary})

        review_decision = "REVISE" if "❌ REVISE" in review_content else "COMPLETE"

        rprint(
            Panel(
                review_content,
                title="[bold]Review Result[/bold]",
                border_style="green" if review_decision == "COMPLETE" else "red",
            )
        )

        return {"current_task_status": review_decision, "review_feedback": review_content}

    def should_continue(self, state: AgentState):
        if state["current_task_status"] == "COMPLETE":
            return "end"
        else:
            rprint("[bold yellow]--- 🔁 Plan failed review. Returning to planner. ---[/bold yellow]")
            return "continue"

    def save_plan_step(self, state: AgentState):
        rprint("[bold blue]--- 💾 Saving Successful Plan to Knowledge Graph ---[/bold blue]")

        issue = state["issue_summary"]
        plan = state.get("plan", [])
        file_paths = list(set([p["parameters"]["file_path"] for p in plan if "file_path" in p.get("parameters", {})]))

        if plan and file_paths:
            self.kg_builder.save_successful_plan(issue, plan, file_paths)
            rprint("[bold green]Plan saved successfully![/bold green]")
            self._commit_and_push(f"Bug fix: {issue}")
        else:
            rprint("[bold yellow]Skipping save: Plan or relevant files not found.[/bold yellow]")

        return state
