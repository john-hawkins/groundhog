"""State for a single project's page: upload -> configure -> summary."""

from __future__ import annotations

import pydantic
import reflex as rx

from ..lib import agent, fs, providers


class ColumnInfo(pydantic.BaseModel):
    name: str
    dtype: str
    n_unique: int


class ExperimentRow(pydantic.BaseModel):
    experiment: str
    date: str
    metric: str
    value: str
    notes: str


class ProjectState(rx.State):
    # "loading" | "not_found" | "upload" | "configure" | "analysis" | "summary"
    stage: str = "loading"
    error: str = ""

    # populated once a dataset has been uploaded
    dataset_files: list[str] = []
    record_count: int = 0
    columns: list[ColumnInfo] = []

    # configure form (target/split/metric)
    target_variable: str = ""
    split_mode: str = "percentage"
    split_value: str = "0.8"
    eval_metric: str = "AUC"

    # populated once ANALYSIS.md exists
    analysis_text: str = ""
    # free-text analysis the user writes instead of running the agent
    analysis_draft: str = ""
    analysis_error: str = ""

    # populated once metadata.json exists (summary stage)
    target_dtype: str = ""
    target_n_unique: int = 0
    experiments: list[ExperimentRow] = []
    top_result: str = "—"

    # experiment run status
    is_running: bool = False
    log_lines: list[str] = []
    run_error: str = ""
    # set when a run exits cleanly but produces nothing, which otherwise looks
    # identical to never having pressed the button
    run_warning: str = ""

    @rx.var
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @rx.var
    def has_analysis(self) -> bool:
        return self.analysis_text.strip() != ""

    @rx.var
    def can_run_experiments(self) -> bool:
        """Experiments need an analysis, unless the project already has some —
        those predate the analysis stage and must not be locked out."""
        return self.has_analysis or len(self.experiments) > 0

    @rx.event
    def load_project(self):
        name = self.name
        self.error = ""
        # Stage is decided from what's on disk, so the agent writing ANALYSIS.md
        # is enough to advance the project.
        self.stage = fs.project_stage(name)
        if self.stage == "not_found":
            return

        self.dataset_files = fs.list_data_files(name)
        if self.stage == "upload":
            return

        if self.stage == "configure":
            preview = fs.dataset_preview(name)
            self.record_count = preview["record_count"]
            self.columns = [ColumnInfo(**c) for c in preview["columns"]]
            if not self.target_variable and self.columns:
                self.target_variable = self.columns[0].name
            return

        self._load_summary(name, fs.read_metadata(name) or {})

    def _load_summary(self, name: str, meta: dict):
        self.record_count = meta.get("record_count", 0)
        self.dataset_files = meta.get("dataset_files", self.dataset_files)
        target = meta.get("target_variable", {})
        self.target_variable = target.get("name", "")
        self.target_dtype = target.get("dtype", "")
        self.target_n_unique = target.get("n_unique", 0)
        split = meta.get("split", {})
        self.split_mode = split.get("mode", "percentage")
        self.split_value = str(split.get("value", ""))
        self.eval_metric = meta.get("eval_metric", "")
        self.analysis_text = fs.read_analysis(name)
        rows = fs.parse_results(name)
        self.experiments = [ExperimentRow(**r) for r in rows]
        self.top_result = fs.top_result(name, self.eval_metric, rows)

    async def handle_upload(self, files: list[rx.UploadFile]):
        for file in files:
            data = await file.read()
            fs.save_data_file(self.name, file.name or "dataset.csv", data)
        self.load_project()

    @rx.event
    def set_target_variable(self, value: str):
        self.target_variable = value

    @rx.event
    def set_split_mode(self, value: str):
        self.split_mode = value

    @rx.event
    def set_split_value(self, value: str):
        self.split_value = value

    @rx.event
    def set_eval_metric(self, value: str):
        self.eval_metric = value

    @rx.event
    def save_metadata(self):
        if not self.target_variable:
            self.error = "Choose a target variable."
            return
        if not self.split_value.strip():
            self.error = "Provide a train/test split value."
            return

        column = next(
            (c for c in self.columns if c.name == self.target_variable), None
        )
        metadata = {
            "dataset_files": self.dataset_files,
            "record_count": self.record_count,
            "target_variable": {
                "name": self.target_variable,
                "dtype": column.dtype if column else "",
                "n_unique": column.n_unique if column else 0,
            },
            "split": {"mode": self.split_mode, "value": self.split_value},
            "eval_metric": self.eval_metric,
        }
        fs.write_metadata(self.name, metadata)
        self.error = ""
        self.load_project()

    @rx.event
    def set_analysis_draft(self, value: str):
        self.analysis_draft = value

    @rx.event
    def save_analysis(self):
        """Write a user-supplied analysis, skipping the agent run."""
        try:
            fs.write_analysis(self.name, self.analysis_draft)
        except ValueError as exc:
            self.analysis_error = str(exc)
            return
        self.analysis_draft = ""
        self.analysis_error = ""
        self.load_project()

    @rx.event(background=True)
    async def run_analysis(self):
        await self._run(agent.run_analysis, "analysis")

    @rx.event(background=True)
    async def run_experiment(self):
        await self._run(agent.run_experiment, "experiment")

    async def _run(self, runner, kind: str):
        """Stream one agent run into the log panel, then reload the page state."""
        async with self:
            if self.is_running:
                return
            self.is_running = True
            self.log_lines = []
            self.run_error = ""
            self.run_warning = ""
            name = self.name

        results_before = len(fs.parse_results(name))

        settings = fs.read_settings()
        try:
            async for line in runner(name, settings):
                async with self:
                    self.log_lines.append(line)
        except (agent.AgentRunError, agent.AgentConfigError) as exc:
            async with self:
                self.run_error = str(exc)
        except FileNotFoundError:
            async with self:
                self.run_error = self._missing_cli_message(settings)
        finally:
            async with self:
                self.is_running = False
                # Reload rather than just refreshing the summary: an analysis
                # run moves the project from the analysis stage to summary.
                self.load_project()
                if not self.run_error:
                    self.run_warning = self._nothing_produced(
                        name, kind, results_before
                    )

    @staticmethod
    def _nothing_produced(name: str, kind: str, results_before: int) -> str:
        """An agent can exit cleanly having written no result — usually because
        its own script failed. Say so rather than showing an empty table."""
        if kind == "analysis" and not fs.has_analysis(name):
            return (
                "The agent finished without writing ANALYSIS.md. Check the "
                "output below."
            )
        if kind == "experiment" and len(fs.parse_results(name)) == results_before:
            return (
                "The agent finished without recording a result in RESULTS.md. "
                "Its experiment code most likely failed — check the output "
                "below and the experiments directory."
            )
        return ""

    @staticmethod
    def _missing_cli_message(settings: dict) -> str:
        provider = providers.get(
            settings.get("provider", providers.DEFAULT_PROVIDER_ID)
        )
        config = (settings.get("provider_config") or {}).get(provider.id, {})
        return (
            f"{provider.label} CLI ('{provider.command(config)}') was not "
            "found on PATH."
        )
