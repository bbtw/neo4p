// =============================================
// ATOMIC NODES: SAVINGS (EMERGENCY, COLLEGE, PURCHASE)
// =============================================

// Savings Goals
MERGE (emerg:EmergencyFundGoal {name: "Emergency Fund Goal", category: "Savings", target_amount: "$10,000", timeline: "12 months"});
MERGE (college:CollegeSavingsGoal {name: "College Savings Goal", category: "Savings", target_amount: "$50,000", timeline: "10 years"});
MERGE (purchase:PurchaseGoal {name: "Purchase Goal", category: "Savings", example: "Boat, Home Down Payment", target_amount: "$20,000"});

// Savings Accounts
MERGE (hy_savings:HighYieldSavingsAccount {name: "High-Yield Savings Account", liquidity: "High", interest_rate: "4.5% APY"});
MERGE (plan529:529PlanAccount {name: "529 Plan", purpose: "Education", tax_advantaged: true});
MERGE (cd:CertificateOfDeposit {name: "CD", term: "12-60 months", penalty: "Early Withdrawal"});

// Contribution Methods
MERGE (auto_deposit:AutoDeposit {name: "Automated Deposit", frequency: "Monthly"});
MERGE (manual_transfer:ManualTransfer {name: "Manual Transfer", flexibility: "Ad hoc"});

// Monitoring Actions
MERGE (progress:TrackProgress {name: "Track Progress", metric: "Percentage of Goal"});
MERGE (adjust:AdjustSavings {name: "Adjust Savings", trigger: "Shortfall/Surplus"});

// =============================================
// ATOMIC NODES: RETIREMENT SAVINGS
// =============================================

// Retirement Goals
MERGE (retire_age:RetireByAgeGoal {name: "Retire by Age 65", target_age: 65});
MERGE (retire_income:RetirementIncomeGoal {name: "$80k/year Retirement Income", target_income: 80000});

// Retirement Accounts
MERGE (401k:401kAccount {name: "401(k)", employer_match: true, contribution_limit: "$22,500"});
MERGE (roth_ira:RothIRAAccount {name: "Roth IRA", tax_free_growth: true, income_limit: "$144k"});

// =============================================
// ATOMIC NODES: INVESTING
// =============================================

// Asset Allocations
MERGE (stocks:StockAllocation {name: "Stocks", risk: "High", return: "7-10% avg"});
MERGE (bonds:BondAllocation {name: "Bonds", risk: "Low", return: "2-5% avg"});

// =============================================
// RELATIONSHIPS: SAVINGS WORKFLOW
// =============================================

// Emergency Fund
MATCH (emerg:EmergencyFundGoal), (hy_savings:HighYieldSavingsAccount), (auto_deposit:AutoDeposit), (progress:TrackProgress)
MERGE (emerg)-[:REQUIRES_ACCOUNT]->(hy_savings)
MERGE (emerg)-[:USES_CONTRIBUTION_METHOD]->(auto_deposit)
MERGE (emerg)-[:REQUIRES_MONITORING]->(progress);

// College Savings
MATCH (college:CollegeSavingsGoal), (plan529:529PlanAccount), (auto_deposit:AutoDeposit), (adjust:AdjustSavings)
MERGE (college)-[:REQUIRES_ACCOUNT]->(plan529)
MERGE (college)-[:USES_CONTRIBUTION_METHOD]->(auto_deposit)
MERGE (college)-[:REQUIRES_MONITORING]->(adjust);

// Purchase Goal (e.g., Boat)
MATCH (purchase:PurchaseGoal), (cd:CertificateOfDeposit), (manual_transfer:ManualTransfer)
MERGE (purchase)-[:REQUIRES_ACCOUNT]->(cd)
MERGE (purchase)-[:USES_CONTRIBUTION_METHOD]->(manual_transfer);

// =============================================
// RELATIONSHIPS: RETIREMENT WORKFLOW
// =============================================

// Retire-by-Age Goal
MATCH (retire_age:RetireByAgeGoal), (401k:401kAccount), (roth_ira:RothIRAAccount), (auto_deposit:AutoDeposit)
MERGE (retire_age)-[:USES_ACCOUNT]->(401k)
MERGE (retire_age)-[:USES_ACCOUNT]->(roth_ira)
MERGE (retire_age)-[:USES_CONTRIBUTION_METHOD]->(auto_deposit);

// Retirement Income Goal
MATCH (retire_income:RetirementIncomeGoal), (roth_ira:RothIRAAccount), (auto_deposit:AutoDeposit)
MERGE (retire_income)-[:USES_ACCOUNT]->(roth_ira)
MERGE (retire_income)-[:USES_CONTRIBUTION_METHOD]->(auto_deposit);

// =============================================
// CROSS-AREA DEPENDENCIES
// =============================================

// Investing Influences
MATCH (stocks:StockAllocation), (401k:401kAccount), (bonds:BondAllocation), (hy_savings:HighYieldSavingsAccount)
MERGE (stocks)-[:INFLUENCES]->(401k)
MERGE (bonds)-[:INFLUENCES]->(hy_savings);

// Competing Priorities
MATCH (emerg:EmergencyFundGoal), (retire_age:RetireByAgeGoal)
MERGE (emerg)-[:COMPETES_WITH {reason: "Limited Cash Flow"}]->(retire_age);

// =============================================
// QUERY EXAMPLES (OPTIONAL)
// =============================================

// Example 1: Get all accounts for College Savings
// MATCH (college:CollegeSavingsGoal)-[:REQUIRES_ACCOUNT]->(account)
// RETURN college.name AS Goal, account.name AS Account;

// Example 2: Find contribution methods for Retirement Goals
// MATCH (retire:RetireByAgeGoal)-[:USES_CONTRIBUTION_METHOD]->(method)
// RETURN retire.name AS Goal, method.name AS Method;
