"""Local mock gateway. Does not import or start any legacy platform clients."""
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Literal
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from agent_core.workflow_runner import WorkflowRunner
from pydantic import BaseModel, Field
from agent_core.workflow import WorkflowRuntime
from agent_core.workflow_store import Budget
from agent_core.action_store import ActionError
from agent_core.workflow_contracts import Ref


class ExecuteRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=10000)
    business_code: str = "testops"
    context: dict = Field(default_factory=dict)


class WorkflowRequest(ExecuteRequest):
    dispatch: Literal["inline", "queued"] = "inline"
    budget: Budget = Field(default_factory=Budget)


class ResumeRequest(BaseModel):
    dispatch: Literal["inline", "queued"] = "inline"
    context: dict = Field(default_factory=dict)
    action_id: str | None = None
    decision: str | None = None
    confirm_effect: str | None = None
    snapshot_hash: str | None = None
    reply: str | None = Field(None, max_length=2000)


class ReferenceRequest(Ref):
    context: dict = Field(default_factory=dict)


def create_app(agent=None, workflow=None, runner=None):
    @asynccontextmanager
    async def lifespan(app):
        await get_runner()
        try:
            yield
        finally:
            if app.state.runner is not None:
                await app.state.runner.stop()

    app = FastAPI(title="TestOps Agent — local mock", version="3.0", lifespan=lifespan)
    app.state.agent = agent
    app.state.workflow = workflow
    app.state.runner = runner
    runner_lock = asyncio.Lock()

    def get_workflow():
        if app.state.workflow is None:
            app.state.workflow = WorkflowRuntime(
                os.getenv("MOCK_DB_PATH", ".mock_state/platforms.sqlite")
            )
        return app.state.workflow

    async def get_runner():
        async with runner_lock:
            if app.state.runner is None:
                app.state.runner = WorkflowRunner(get_workflow().store.db.path)
            if not app.state.runner.accepting:
                raise HTTPException(503, "服务正在停止接单")
            await app.state.runner.start()
            return app.state.runner

    @app.exception_handler(ActionError)
    async def action_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409
            if exc.code in {"RESOURCE_BUSY", "STATE_CONFLICT"}
            else 429
            if exc.code == "QUEUE_FULL"
            else 400,
            content={"code": exc.code, "message": str(exc)},
            headers={"Retry-After": "1"}
            if exc.code in {"RESOURCE_BUSY", "STATE_CONFLICT"}
            else None,
        )

    @app.post("/workflows")
    async def start_workflow(request: WorkflowRequest):
        if request.business_code != "testops":
            raise HTTPException(400, "Only testops is supported")
        context = dict(request.context)
        context.setdefault("session_id", str(uuid.uuid4()))
        runner = await get_runner()
        result = await asyncio.to_thread(
            runner.jobs.submit, request.user_input, context, request.budget
        )
        if request.dispatch == "queued":
            return JSONResponse(
                status_code=202, content={**result, "session_id": context["session_id"]}
            )
        result = await runner.wait(result["task_id"], context)
        return {**result, "session_id": context["session_id"]}

    @app.post("/workflows/{task_id}/resume")
    async def resume_workflow(task_id: str, request: ResumeRequest):
        if request.decision not in {None, "approve", "deny"}:
            raise HTTPException(422, "decision must be approve or deny")
        runner = await get_runner()
        result = await asyncio.to_thread(
            runner.jobs.resume,
            task_id,
            request.context,
            request.action_id,
            request.decision,
            request.reply,
            request.confirm_effect,
            request.snapshot_hash,
        )
        if request.dispatch == "queued":
            return JSONResponse(status_code=202, content=result)
        return await runner.wait(task_id, request.context)

    @app.post("/workflows/{task_id}/status")
    async def workflow_status(task_id: str, request: ResumeRequest):
        return await asyncio.to_thread(
            get_workflow().store.get, task_id, request.context
        )

    @app.post("/workflows/{task_id}/refs")
    async def read_reference(task_id: str, request: ReferenceRequest):
        return await asyncio.to_thread(
            get_workflow().store.read_ref,
            task_id,
            request.model_dump(exclude={"context"}),
            request.context,
        )

    @app.post("/workflows/{task_id}/cancel")
    async def cancel_workflow(task_id: str, request: ResumeRequest):
        runner = await get_runner()
        result = await asyncio.to_thread(runner.jobs.cancel, task_id, request.context)
        return JSONResponse(
            status_code=200
            if result["status"]
            in {
                "cancelled",
                "completed",
                "failed",
                "denied",
                "planned",
                "partial",
                "expired",
            }
            else 202,
            content=result,
        )

    def get_agent():
        if app.state.agent is None:
            from agent_core.offline_runtime import build_offline_agent

            app.state.agent = build_offline_agent(
                os.getenv("MOCK_DB_PATH", ".mock_state/platforms.sqlite")
            )
        return app.state.agent

    @app.get("/")
    @app.get("/health")
    async def health():
        runtime = get_workflow()
        model = runtime.model
        llm = getattr(model, "llm", None)
        legacy = app.state.agent
        return {
            "status": "ok",
            "runtime_mode": "mock",
            "primary_endpoint": "/workflows",
            "orchestrator": "workflow_runtime",
            "llm_mode": getattr(llm, "mode", None)
            or (
                "offline"
                if getattr(model, "name", None) == "offline_rules"
                else "custom"
            ),
            "compatibility": {
                "endpoints": ["/agent/execute", "/agent/langgraph/execute"],
                "initialized": legacy is not None,
                "orchestrator": None
                if legacy is None
                else ("langgraph" if legacy._graph is not None else "manual_fallback"),
                "llm_mode": None if legacy is None else legacy.llm.mode,
            },
        }

    @app.post("/agent/execute")
    @app.post("/agent/langgraph/execute")
    async def execute(request: ExecuteRequest):
        if request.business_code != "testops":
            raise HTTPException(400, "Only testops is supported")
        context = dict(request.context)
        context.setdefault("session_id", str(uuid.uuid4()))
        result = await get_agent().ainvoke(request.user_input, context)
        result["data"]["session_id"] = context["session_id"]
        return result

    return app


app = create_app()
