# 🦦 Groundhog

Data science meta-harness application for agentic experimentation loops.

**The problem**: Solving data science problems often requires many iterations
 of experimentation. Each loop learning from the results of previous iterations.
 These problems are not solved by simply describing a problem and designing
 an appropriate solution.

This project implements a meta-harness for using AI coding agents to perform
those experiments. You define the problem through a dataset, required metric
to optimise and an appropriate testing strategy. Then the groundhog meta-harness
allows you to point one (or more) coding agents at the problem. Each new iteration
can access the previous experimental notes and results to devise an improved approach.




## Implementation

Created as a Reflex python web application and managed using the uv package manager.

Refer to the [Design](DESIGN.md) document for outline of the initial idea.

## Usage

Groundhog can drive Claude Code, OpenCode or Codex. Pick one in the settings
dialog (the gear icon) and fill in what it needs:

| Agent | Requires | Notes |
| --- | --- | --- |
| Claude Code | a claude.ai subscription login | Run `claude /login` once. Any `ANTHROPIC_API_KEY` in your shell is removed before each run so it stays on the subscription. |
| OpenCode | model + API key | Model is fully qualified, e.g. `anthropic/claude-sonnet-5`. |
| Codex | API key (model optional) | |

Each agent also takes an optional executable path (if it isn't on `PATH`) and
extra arguments appended to every run. Settings are saved to `settings.json`
in the repo root, which is gitignored because it can hold API keys.

1. Install dependencies:
   ```
   uv sync
   ```
2. Start the app:
   ```
   uv run reflex run
   ```
3. Open http://localhost:3000 in your browser.

* Create a project
* Load a dataset
* Specify your target variable
* Choose a train/test strategy.
* Then start you experiment
 
The AI coding agent runs independent loops of experimentation.
Each loop reflects on previous experiments and results before devising the
next approach.


