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
    # "loading" | "not_found" | "upload" | "configure" | "summary"
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

    # populated once metadata.json exists (summary stage)
    target_dtype: str = ""
    target_n_unique: int = 0
    experiments: list[ExperimentRow] = []
    top_result: str = "—"

    # experiment run status
    is_running: bool = False
    log_lines: list[str] = []
    run_error: str = ""

    @rx.var
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @rx.event
    def load_project(self):
        name = self.name
        self.error = ""
        if not fs.project_exists(name):
            self.stage = "not_found"
            return

        self.dataset_files = fs.list_data_files(name)
        if not self.dataset_files:
            self.stage = "upload"
            return

        meta = fs.read_metadata(name)
        if meta is None:
            preview = fs.dataset_preview(name)
            self.record_count = preview["record_count"]
            self.columns = [ColumnInfo(**c) for c in preview["columns"]]
            if not self.target_variable and self.columns:
                self.target_variable = self.columns[0].name
            self.stage = "configure"
            return

        self._load_summary(name, meta)
        self.stage = "summary"

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

    @rx.event(background=True)
    async def run_experiment(self):
        async with self:
            if self.is_running:
                return
            self.is_running = True
            self.log_lines = []
            self.run_error = ""
            name = self.name

        settings = fs.read_settings()
        try:
            async for line in agent.run_experiment(name, settings):
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
                self._load_summary(name, fs.read_metadata(name) or {})

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
