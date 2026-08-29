# Experiment Prompt

Read by Groundhog and passed to the coding agent for each experiment loop. The
working directory is the project directory: `projects/<project-name>/`.

---

You are running one iteration of an experimentation loop for a data science
project. Work entirely within the current directory. Do the following, in
order:

1. **Review prior work.** Read `metadata.json` (target variable, train/test
   strategy, evaluation metric). Read `ANALYSIS.md` — the initial analysis of
   this dataset — and treat its findings on distributions, missing values,
   class balance and leakage risk as established context you do not need to
   rediscover. Older projects may not have one; if it is absent, carry on and
   work from the previous experiments instead. Read `RESULTS.md` for every result achieved so far. Read every
   `experiments/*/README.md` to see what approaches have already been tried
   and what was learned from each.

2. **Plan the next experiment.** Based on `ANALYSIS.md` and on what has and
   hasn't worked so far, decide on one concrete, incremental experimental
   approach to try next (a model choice, feature engineering step,
   hyperparameter change, validation strategy, etc). Give it a short,
   descriptive, filesystem-safe name (lowercase, hyphen-separated, e.g.
   `gradient-boosting-baseline`).

3. **Set up the experiment directory.** Create `experiments/<name>/`.
   Before writing any code, write `experiments/<name>/README.md` documenting:
   - The approach and the reasoning behind trying it now.
   - Which finding in `ANALYSIS.md` motivates it, if any.
   - What prior result (if any) it is trying to improve on.
   - How it will be evaluated (using the metric and split strategy from
     `metadata.json`).

4. **Implement and run the experiment.** Write the experiment code inside
   `experiments/<name>/`, using the dataset in `data/` and respecting the
   target variable, train/test split, and evaluation metric defined in
   `metadata.json`. Execute it.

5. **Record the result.** Append one row to the table in `RESULTS.md`
   (create the row in the same `| Experiment | Date | Metric | Value | Notes |`
   format as the existing rows) with the experiment name, today's date, the
   metric name, the achieved value, and a one-line note. Do this before you
   finish, even if the experiment's result is worse than prior experiments —
   a negative result is still a result. Do not use the `|` character inside a
   cell.

Do not modify `data/`, `metadata.json`, `ANALYSIS.md`, or any other project's
directory. Do not rewrite history in `RESULTS.md` — only append.
