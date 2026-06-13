# Financial Planning Task Graph

## Purpose

This document defines a first version of a financial planning task graph for a digital AI assistant used by financial planners.

The graph must support three jobs:

- Help an AI assistant reason about what to ask, recommend, or complete next.
- Give planners a workflow structure for tracking client planning work.
- Provide a reusable taxonomy that other products or data models can map onto.

The model uses a familiar planning hierarchy as its visible spine:

```text
Need -> Subneed -> Task
```

Most tasks should sit under a subneed. A task may connect directly to a need when it is broad enough that forcing it into one subneed would make the model less clear.

## Core Model

### Node Types

`Need`

A broad financial planning domain. Needs are the top-level planning areas a planner or assistant can use for navigation and summary.

Examples:

- Cash Flow
- Savings
- Protection
- Investments
- Retirement
- Tax
- Estate
- Education

`Subneed`

A focused planning area within a need.

Examples:

- Emergency Reserve
- Retirement Savings
- College Funding
- Life Insurance
- Estate Planning
- Tax Planning

`Task`

An actionable planner work item. Tasks should be named with planner action verbs and should describe work that can be completed, reviewed, or marked not applicable.

Examples:

- Assess emergency reserve adequacy
- Estimate retirement income gap
- Review beneficiary designations
- Evaluate life insurance coverage gap
- Estimate college funding gap

## Relationship Types

`need_to_subneed`

Connects a broad planning need to a focused subneed.

Example:

```text
Savings -> Retirement Savings
```

`subneed_to_task`

Connects a subneed to an actionable planner task.

Example:

```text
Retirement Savings -> Estimate retirement income gap
```

`need_to_task`

Connects a need directly to a task when the task is broad and does not belong cleanly under one subneed.

Example:

```text
Tax -> Review current tax profile
```

## Modeling Rules

- Every subneed belongs to one need.
- Most tasks belong to one subneed.
- A task can belong directly to a need when no single subneed is the obvious home.
- Avoid duplicating the same task under multiple subneeds.
- Task names use planner action verbs.
- Tasks describe planner work, not vague client outcomes.
- V1 does not define client applicability rules, household fact schemas, thresholds, or recommendation logic.
- Future applicability rules can be added without changing the basic graph shape.

## Initial Taxonomy

### Cash Flow

#### Budget And Spending

- Analyze income and expense patterns
- Identify discretionary spending capacity
- Assess debt payment obligations
- Review recurring financial commitments

#### Emergency Reserve

- Assess emergency reserve adequacy
- Determine target reserve range
- Recommend reserve funding strategy

#### Debt Management

- Inventory outstanding debts
- Prioritize debt repayment strategy
- Evaluate refinancing opportunities

### Savings

#### Retirement Savings

- Estimate retirement income gap
- Review current retirement contribution rates
- Evaluate account type mix
- Recommend retirement savings strategy

#### Education Savings

- Estimate college funding gap
- Review education savings account options
- Recommend education funding strategy

#### Major Purchase Savings

- Define major purchase funding target
- Assess savings timeline feasibility
- Recommend major purchase savings strategy

### Protection

#### Life Insurance

- Inventory existing life insurance coverage
- Evaluate life insurance coverage gap
- Review policy ownership and beneficiaries
- Recommend life insurance strategy

#### Disability Insurance

- Inventory existing disability coverage
- Evaluate disability income protection gap
- Review employer disability benefits
- Recommend disability insurance strategy

#### Property And Casualty Insurance

- Inventory property and casualty policies
- Identify liability coverage gaps
- Review umbrella liability coverage need

### Investments

#### Asset Allocation

- Review current asset allocation
- Assess risk tolerance and capacity
- Identify concentration risk
- Recommend target allocation

#### Account Location

- Review taxable and tax-advantaged account placement
- Identify tax-inefficient holdings
- Recommend account location adjustments

#### Investment Policy

- Document investment objectives
- Review rebalancing approach
- Confirm liquidity needs

### Retirement

#### Retirement Readiness

- Assess retirement readiness
- Estimate retirement spending need
- Model retirement income sources
- Identify retirement plan shortfall

#### Social Security And Pensions

- Review Social Security claiming options
- Inventory pension benefits
- Evaluate guaranteed income strategy

#### Retirement Distribution

- Estimate sustainable withdrawal range
- Review retirement account distribution order
- Evaluate required minimum distribution impact

### Tax

#### Income Tax Planning

- Review current tax profile
- Identify marginal tax bracket issues
- Evaluate tax-loss harvesting opportunities
- Recommend income tax planning actions

#### Retirement Tax Strategy

- Evaluate Roth conversion opportunity
- Review pre-tax and Roth contribution mix
- Model retirement tax diversification

#### Charitable Giving

- Review charitable giving goals
- Evaluate donor-advised fund fit
- Recommend charitable giving strategy

### Estate

#### Estate Planning

- Review estate planning documents
- Identify missing estate documents
- Review beneficiary designations
- Confirm fiduciary appointments

#### Wealth Transfer

- Identify wealth transfer goals
- Review gifting strategy
- Evaluate trust planning needs

#### Incapacity Planning

- Review powers of attorney
- Review health care directives
- Confirm access to key financial information

### Education

#### College Funding

- Estimate expected education costs
- Review available education savings
- Evaluate financial aid assumptions
- Recommend college funding strategy

#### Student Loan Planning

- Inventory student loans
- Review repayment plan options
- Evaluate refinancing fit

## AI Assistant Use

The assistant can use the graph to:

- Summarize planning progress by need and subneed.
- List tasks associated with a subneed.
- List broad tasks associated directly with a need.
- Explain why a task matters by tracing it to its parent subneed and need, or directly to its parent need.

Example:

```text
If the planner is working on Education -> College Funding, show the tasks under College Funding: estimate expected education costs, review available education savings, evaluate financial aid assumptions, and recommend college funding strategy.
```

## Review Criteria

The model is acceptable when:

- A planner can browse the structure by need and subneed.
- An AI assistant can list the tasks under a need or subneed.
- Tasks are actionable planner work items.
- The only relationships are need to subneed, subneed to task, and optional need to task.
- No client applicability rules are required to understand v1.
