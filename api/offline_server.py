"""Local mock gateway. Does not import or start any legacy platform clients."""
import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from agent_core.offline_runtime import build_offline_agent
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget
from agent_core.action_store import ActionError
from agent_core.workflow_contracts import Ref


class ExecuteRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=10000)
    business_code: str = "testops"
    context: dict = Field(default_factory=dict)


class WorkflowRequest(ExecuteRequest):
    budget: Budget = Field(default_factory=Budget)


class ResumeRequest(BaseModel):
    context: dict = Field(default_factory=dict)
    action_id: str | None = None
    decision: str | None = None
    reply: str | None = Field(None, max_length=2000)


class ReferenceRequest(Ref):
    context: dict = Field(default_factory=dict)


def create_app(agent=None, workflow=None):
    app = FastAPI(title="TestOps Agent — local mock", version="2.0")
    app.state.agent = agent
    app.state.workflow = workflow

    def get_workflow():
        if app.state.workflow is None:
            app.state.workflow = WorkflowRuntime(os.getenv("MOCK_DB_PATH", ".mock_state/platforms.sqlite"))
        return app.state.workflow

    @app.exception_handler(ActionError)
    async def action_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409 if exc.code=="RESOURCE_BUSY" else 400, content={"code":exc.code,"message":str(exc)})

    @app.post("/workflows")
    async def start_workflow(request: WorkflowRequest):
        if request.business_code != "testops":
            raise HTTPException(400,"Only testops is supported")
        context={"env":"uat","operator":"local",**request.context}
        context.setdefault("session_id",str(uuid.uuid4()))
        result=await get_workflow().start(request.user_input,context,request.budget)
        return {**result,"session_id":context["session_id"]}

    @app.post("/workflows/{task_id}/resume")
    async def resume_workflow(task_id: str, request: ResumeRequest):
        if request.decision not in {None,"approve","deny"}:
            raise HTTPException(422,"decision must be approve or deny")
        return await get_workflow().resume(task_id,request.context,request.action_id,request.decision,request.reply)

    @app.post("/workflows/{task_id}/status")
    async def workflow_status(task_id: str, request: ResumeRequest):
        return get_workflow().store.get(task_id,request.context)

    @app.post("/workflows/{task_id}/refs")
    async def read_reference(task_id: str, request: ReferenceRequest):
        return get_workflow().store.read_ref(task_id,request.model_dump(exclude={"context"}),request.context)

    def get_agent():
        if app.state.agent is None:
            app.state.agent = build_offline_agent(os.getenv("MOCK_DB_PATH", ".mock_state/platforms.sqlite"))
        return app.state.agent

    @app.get("/")
    @app.get("/health")
    async def health():
        runtime = get_agent()
        return {"status": "ok", "runtime_mode": "mock", "llm_mode": runtime.llm.mode,
                "orchestrator": "langgraph" if runtime._graph is not None else "manual_fallback"}

    @app.post("/agent/execute")
    @app.post("/agent/langgraph/execute")
    async def execute(request: ExecuteRequest):
        if request.business_code != "testops":
            raise HTTPException(400, "Only testops is supported")
        context = {"env": "uat", "operator": "local", **request.context}
        context.setdefault("session_id", str(uuid.uuid4()))
        result = await get_agent().ainvoke(request.user_input, context)
        result["data"]["session_id"] = context["session_id"]
        return result

    return app


app = create_app()
