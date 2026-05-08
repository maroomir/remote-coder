# Clean Code Rules

The goal is not pretty code for its own sake. The goal is code that another person can understand quickly and modify safely.

## Core Quality Bar

Write code that is:

- **Readable**: intent and flow are easy to follow.
- **Maintainable**: change locations are easy to find and impact is contained.
- **Extensible**: new behavior can be added without destabilizing unrelated code.
- **Robust**: invalid input, edge cases, and failures are handled deliberately.
- **Testable**: logic is split into units that can be verified independently.
- **Self-documenting**: names and structure communicate domain intent.
- **Consistent**: similar problems are solved in similar ways across the project.

## Start with Readability

Optimize for reducing cognitive load. Prefer code whose shape, structure, and names match the reader's expectations.

Use three lenses:

1. **Good shape**: meaningful blocks are visually separated.
2. **Good structure**: related data and logic are placed where readers expect them.
3. **Good names**: names are concise but descriptive enough to reveal intent.

## Good Shape

- Let the project formatter handle mechanical formatting.
- Keep strongly related code close together.
- Use blank lines to separate distinct semantic steps.
- Use comments only for intent, constraints, tradeoffs, security, or non-obvious context.
- Remove comments that merely repeat what the code says.
- Avoid large uninterrupted blocks; split when a reader cannot see the meaningful unit at once.

## Good Structure

- Keep related state, derived values, and functions near each other.
- Arrange similar handlers/functions in a consistent order.
- Preserve data-flow readability: values should be created, transformed, and used in an order that is easy to trace.
- Split long functions/classes when one screen no longer shows the meaningful unit.
- Choose organization by role or by flow based on what makes the current code easiest to read.
- Keep FastAPI routing, domain services, adapters, persistence, and Telegram presentation concerns separated.

Before finalizing structure, ask:

- Can a reader easily trace where this value is created and used?
- Are related behaviors grouped together?
- Do similar functions/handlers have similar shapes and ordering?
- Is the likely change location obvious for a future requirement?
- Is the testable unit visible in the code structure?

## Good Names

Names are the fastest documentation. Make them specific enough to reveal role and intent without becoming noisy.

### Variables

- Reveal the value's role.
- Make the type or shape reasonably inferable.
- Avoid unclear abbreviations.
- Use more specific names for wider scopes.
- Boolean names should usually begin with `is`, `has`, `can`, or `should`.

Examples:

```python
selected_project_name = "remote-coder"
is_authorized = True
workspace_paths = settings.project_paths
```

### Functions

Function names should communicate action, target, condition, and context when useful.

Prefer names like:

```python
def get_project_by_name(project_name: str) -> ProjectConfig: ...
def create_worktree_for_job(job: Job) -> Path: ...
def validate_chat_id(chat_id: int) -> bool: ...
```

Avoid vague names without context, such as `process`, `do_stuff`, `handle_it`, `data`, `flag`, and `temp`, unless the scope is tiny and meaning is obvious.

### Naming Nuance

- `create`: make a new object or resource.
- `add`: add an item to an existing collection.
- `insert`: place an item at a specific position.
- `fetch`: retrieve remote data.
- `load`: read from file, resource, or persisted state.
- `get`: access an already available value.
- `update`: modify an existing value.
- `validate`: check whether input satisfies rules.
- `current`: currently active value.
- `selected`: user-selected value.

## Review Checklist

When writing or reviewing code, verify:

- Can the role of each value/function be inferred from its name?
- Does each function/class have a focused responsibility?
- Are related pieces close together and unrelated pieces separated?
- Do blank lines separate meaningful phases?
- Do comments explain intent/context rather than repeat implementation?
- Are patterns consistent with the surrounding project?
- Is the code split into units that are easy to test?
- Would a future maintainer know where to change behavior for a new requirement?

## Adoption Principles

- Automate what can be automated with formatter and linter rules.
- In reviews, discuss readability, change safety, and testability rather than personal taste.
- Refactor only as part of feature work or when it directly reduces risk for the requested change.
- Add tests first around high-risk or frequently changed logic.
- Write code for future maintainers, including future you.
