from typing import TypedDict, List, Optional, Dict, Any

class AgentState(TypedDict):
    issue_summary: str
    repo_url: str
    local_path: str
    plan: List[Dict[str, Any]]
    execution_results: List[str]
    review_feedback: Optional[str]
    current_task_status: str