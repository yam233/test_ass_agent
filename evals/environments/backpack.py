from evals.environments.workflow import WorkflowEnvironment


class BackpackEnvironment(WorkflowEnvironment):
    def reset(self, seed):
        from scripts.evaluate_backpack import offline_agent

        self.seed = seed
        self.agent = offline_agent(self.path)
        self.agent.mock_platforms.reset()

    async def apply(self, action):
        return await self.agent.ainvoke(action["text"], action["context"])

    def snapshot(self):
        return {"gifts": self.agent.mock_platforms.snapshot("gifts")}

    def invariants(self):
        rows = self.snapshot()["gifts"]
        return [
            {
                "name": "nonnegative_quantity",
                "passed": all(r["quantity"] >= 0 for r in rows),
            }
        ]
