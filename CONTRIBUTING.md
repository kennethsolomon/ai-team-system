# Contributing to AI Team System

We welcome contributions -- whether it's a new agent, a bug fix, or a documentation improvement.

## Ways to contribute

- **Add a new agent** -- build a specialist for a domain not yet covered
- **Improve an existing agent** -- sharpen prompts, add skills, handle edge cases better
- **Fix bugs** -- in the database layer, ingestion pipeline, or agent definitions
- **Improve documentation** -- clearer setup instructions, better examples, typo fixes
- **Share your setup** -- open a Discussion showing how you've customized the system

## How to add a new agent

1. Fork the repo and create a branch from `main`
2. Create the agent definition at `.claude/agents/<name>.md` -- follow the format of any existing agent (e.g., `vault.md`, `sage.md`)
3. Create the identity profile at `Team/<name>.md` -- same structure as existing profiles
4. Add the agent to `Team/roster.md`
5. Add a routing rule in `CLAUDE.md` under "Routing Rules" so John knows when to delegate to them
6. Submit a PR

## Agent definition format

Each agent file in `.claude/agents/` uses this structure:

- **Identity** -- name, role, one-line description
- **Personality** -- how the agent thinks and communicates
- **Technical expertise** -- tools, frameworks, domain knowledge
- **Mental models** -- guiding principles for decision-making
- **What they do NOT do** -- explicit boundaries to prevent scope creep
- **Quality bar** -- definition of done for their work

Look at any existing agent in `.claude/agents/` for a working example.

## PR guidelines

- **One concern per PR** -- don't mix a new agent with unrelated doc changes
- **Clear description** -- explain what changed and why
- **Test your agent** -- have a conversation with it before submitting; verify it stays in its lane and produces useful output
- **Follow existing patterns** -- naming conventions, file locations, and formatting should match the rest of the project

## Code of conduct

Be respectful. That's it.

## Questions?

Open a thread in [GitHub Discussions](https://github.com/kennethsolomon/ai-team-system/discussions).
