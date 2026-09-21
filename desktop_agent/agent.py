from .interpreter import arguments, split_steps
from .tools.registry import CRITERIA


class Agent:
    def __init__(self, config, client, tools, log, confirm, cancelled):
        self.config, self.client, self.tools = config, client, tools
        self.log, self.confirm, self.cancelled = log, confirm, cancelled

    def run(self, text, dry_run=False):
        history = []
        steps = split_steps(text)
        for index, instruction in enumerate(steps, 1):
            if self.cancelled.is_set():
                self.log("任务已停止。")
                return
            self.log(f"第 {index}/{len(steps)} 步：{instruction}")
            decision = self.client.choose(
                {
                    "current_instruction": instruction,
                    "history": history,
                    "local_state": self.tools.observe(),
                },
                CRITERIA,
            )
            self.log(f"Jev → {decision.choice} | confidence={decision.confidence:.3f}")
            if decision.choice == "unsupported":
                raise ValueError("Jev 判断此指令不在支持范围内，请参照示例重新表述。")
            args = arguments(decision.choice, instruction)
            self.log(f"参数：{args}")
            if decision.confidence < self.config.min_confidence and not dry_run:
                if not self.confirm(f"Jev 对动作选择不确定。是否执行？\n{decision.choice}\n{args}"):
                    raise RuntimeError("已取消低置信度动作。")
            if self.cancelled.is_set():
                self.log("任务已停止，未执行该动作。")
                return
            result = "仅预览，未执行。" if dry_run else self.tools.execute(decision.choice, args)
            self.log(result)
            # No document contents are sent back to Jev; only action status.
            history.append(
                {
                    "instruction": instruction,
                    "action": decision.choice,
                    "status": "previewed" if dry_run else "completed",
                }
            )
        self.log("预览完成。" if dry_run else "任务完成。")
