# Analysis Prompt

Read by Groundhog and passed to the coding agent for a project's one-off
analysis run, before any experiments are allowed. The working directory is the
project directory: `projects/<project-name>/`.

---

You are performing the initial data analysis for a data science project. This
runs once, before any modelling. Do not build models and do not create anything
in `experiments/`.

1. **Read the setup.** Read `metadata.json` for the target variable, the
   train/test strategy and the evaluation metric.

2. **Explore the dataset** in `data/`. Cover, at a minimum:
   - Shape: row count and column count.
   - Every column's type, and whether it is numeric, categorical or a date.
   - Missing values per column, as a count and a percentage.
   - Distribution of each numeric column: min, max, mean, median, quartiles,
     and a note on skew or obvious outliers.
   - Distribution of each categorical column: cardinality and the most common
     values.
   - The target variable specifically: its type, its distribution, and for
     classification the class balance. Say plainly whether it looks like a
     classification or regression problem, and whether the chosen evaluation
     metric suits it.
   - Univariate relationships between each feature and the target.

3. **Write `ANALYSIS.md`** in the project directory. Use markdown tables for
   the per-column numbers — one row per column — and prose for what the numbers
   mean. Include a short "Key findings" section at the top covering anything
   that should shape how experiments are designed: leakage risk, unusable
   columns, heavy class imbalance, columns needing imputation or encoding, and
   any mismatch between the data and the configured metric or split strategy.

4. Keep any scripts you write in an `analysis/` directory. Do not modify
   `data/` or `metadata.json`.

Write `ANALYSIS.md` before you finish. It is the reference every later
experiment reads.
