# Groundhog — notes and suggested issues

Notes from working through issues #5 and #6. Five things I'd raise as issues,
then a sketch of how I'd change the architecture to let this scale.

Everything below was reproduced against `6f6e8bc`.

---

## 1. The experiment agent modified the application's own dependency manifest

This one I hit by accident while testing, which makes it the clearest example of
the problem underneath most of the others.

I ran a real experiment loop against a demo project. The agent needed
scikit-learn, which isn't a declared dependency and isn't installed. Rather than
fail, it went up out of the project directory, added `scikit-learn>=1.9.0` to
Groundhog's own `pyproject.toml`, and re-locked `uv.lock` (+292 lines). The
experiment itself worked fine — AUC 0.6768, result appended correctly. But a
project-level experiment silently changed the application's dependencies.

`AGENTS.md` does say "Work entirely within the current directory" and lists
things not to modify. The list covers `data/`, `metadata.json` and other
projects. It doesn't mention the parent repository, and `cwd` isn't a boundary —
the agent runs with `--dangerously-skip-permissions` and can walk anywhere.

Two separate things to fix:

- Experiments need their own environment. Every experiment will want packages
  the app doesn't have. Issue #4 asks for `sklearn.metrics.roc_curve`, so this
  will come up immediately. A per-project venv, or a declared experiment
  dependency set, or a container.
- The agent shouldn't be *able* to reach the parent repo. See the sandboxing
  point in the sketch below.

## 2. Project name from the URL isn't validated, so the agent can be pointed anywhere

`ProjectState.name` comes from the `/project/[name]` route. It's never declared
in the state class — Reflex injects it from the URL — so it's raw user input.
`create_project()` slugifies the name, but the read path doesn't:

```
name='../..'  ->  projects/../..  ->  /Users/me/Documents/projects
project_exists('../..').is_dir()  ->  True    # the only check that runs
```

`run_experiment` then uses that as the subprocess `cwd` and launches the agent
with `--dangerously-skip-permissions`. So visiting `/project/../..` and clicking
Start Experiment runs a full-permissions coding agent in a directory of the
caller's choosing. There's no auth on the app, so this is reachable by anyone
who can reach the port.

Fix is small: check `slugify(name) == name` on every read path, and assert the
resolved path is inside `PROJECTS_DIR`.

## 3. "Top Result" compares numbers from different metrics

`fs.top_result()` collects each row's metric, then throws it away. Direction and
label come from `eval_metric` only, and min/max runs over every value:

```python
rows = AUC 0.91, RMSE 12.5   eval_metric = "AUC"
top_result() -> "12.5 (AUC)"        # should be 0.91 (AUC)
```

The metric lookup is also case-sensitive, so an agent that writes `rmse` instead
of `RMSE` misses `LOWER_IS_BETTER` and the comparison inverts — `rmse 99` gets
reported as better than `rmse 5`.

This is the headline number on the projects table, and it's wrong as soon as
more than one metric appears. Worth fixing before #1 and #2, since both of those
deliberately introduce multiple metrics.

## 4. RESULTS.md is the database

`parse_results()` splits a markdown table on `|`, and the file is written by a
free-form LLM. Two failure modes, both silent:

```
| tuned | 2026-01-02 | AUC | 0.88 | grid search over C | penalty |
   -> notes truncated at the pipe

| broken | 2026-01-03 | AUC | 0.99 |
   -> row dropped entirely, no error, no log
```

There's also no id linking a row back to `experiments/<name>/`, and "don't
rewrite history" is enforced only by asking the agent nicely in the prompt.

I'd keep RESULTS.md as a generated view and write results to something
structured (SQLite or JSONL). That also turns multi-metric support into a schema
change instead of a parsing problem.

## 5. Two browser tabs run two agents in the same directory

`is_running` lives on `ProjectState`, which is per-session. Two tabs are two
sessions, so the guard doesn't hold. Both runs get the same project directory,
both append to RESULTS.md, both write into `experiments/`. No lock file, no
shared registry of what's running.

Needs a run record outside session state — even a lock file in the project
directory would do for now.

---

## Re-architecture sketch

The current shape — one process, filesystem state, run tracking in session
state, agent trusted by prompt — works as a single-user local tool. Four changes
would let it go further, roughly in dependency order.

**1. Sandbox the agent.** Right now `AGENTS.md` asks the agent not to touch
`data/`, `metadata.json`, or other projects, and nothing enforces it — issue #1
above is that gap being crossed in practice, not in theory. The agent
runs with `--dangerously-skip-permissions`, `cwd` is a suggestion it can `cd`
out of, and `_subprocess_env()` strips two variables and passes the rest of the
parent environment through. Running each experiment in a container or VM with
only that project's directory mounted and an explicit allowlisted environment
turns those rules into actual boundaries. This is also what makes issue #1 above
merely a bug rather than remote code execution.

**2. Pull run state out of the UI.** A durable run record — id, project,
provider, run type, status, timestamps, exit code, log location — owned by
something other than `rx.State`. That single change covers the concurrency
problem in #4, gives somewhere to hang cancel and timeout, and stops logs
accumulating in state (they currently grow unbounded, one `rx.text` node per
line, and every append is serialised to the browser). It also means closing the
tab doesn't orphan the run.

**3. Structured results.** Per #3 above. Write to SQLite, render RESULTS.md from
it. Removes the class of bug where the model is also the database writer.

**4. Provider and prompt abstraction.** This is what issues #5 and #6 needed, so
it's done in the two PRs: providers declare their own executable, argument shape,
required config and credential environment, and prompts are versioned files in
`prompts/` rather than a section of a tool-managed `AGENTS.md`. Settings persist
to disk instead of living in session state, where they were previously never
read by the runner at all.

With 1–3 in place the UI becomes a client of a run orchestrator rather than the
thing holding the subprocess open, which is the point at which multiple users,
remote execution, and parallel experiments all become possible.

---

## Smaller things, not worth their own issue

- An interrupted run leaves inconsistent state. There's no way to stop a run
  from the UI, and if one dies partway it leaves `experiments/<name>/` behind
  with no row in `RESULTS.md`. The projects table counts experiment directories
  but takes results from the markdown table, so it reports 2 experiments and 1
  result. Observed — I killed a run mid-flight while testing. Fixing this
  properly needs the run record from point 2 of the sketch.
- One corrupt `metadata.json` takes down the whole projects page.
  `read_metadata()` calls `json.loads` unguarded and `write_metadata()` uses
  `write_text`, which isn't atomic. `load_projects()` loops every project
  calling it, so one truncated file breaks the index for all of them. Fix is a
  temp-file + `os.replace` write and a per-project try/except on read.
- `dataset_preview()` does `pd.read_csv()` on the whole file plus `nunique()` on
  every column, synchronously, inside an event handler. A large CSV blocks every
  session. Uploads have no size limit either.
- Only `files[0]` is ever previewed, so a multi-file dataset is half ignored.
- `split.value` is stored unvalidated. `percentage` accepts `"abc"`, `cv_folds`
  accepts `"0.8"`, and `column` is never checked against the real columns.
- `projects/` isn't gitignored, so uploaded datasets get committed.
- There were no tests or CI. The two PRs add pytest and 53 tests; CI config would
  be a sensible follow-up.
