// Needs
MERGE (n1:Need {name: 'Saving'})
MERGE (n2:Need {name: 'Retirement'})

// SubNeeds
MERGE (s1:SubNeed {name: 'Emergency Fund'})
MERGE (s2:SubNeed {name: 'College Savings'})
MERGE (s3:SubNeed {name: '401k'})

// Tasks
MERGE (t1:Task {name: 'Open savings account'})
MERGE (t2:Task {name: 'Set emergency goal'})
MERGE (t3:Task {name: 'Start monthly contributions'})
MERGE (t4:Task {name: 'Enroll in 401k plan'})
MERGE (t5:Task {name: 'Create a goal'})

// Relationships
MERGE (n1)-[:HAS_SUBNEED]->(s1)
MERGE (n1)-[:HAS_SUBNEED]->(s2)
MERGE (n2)-[:HAS_SUBNEED]->(s3)

MERGE (s1)-[:HAS_TASK]->(t1)
MERGE (s1)-[:HAS_TASK]->(t2)
MERGE (s1)-[:HAS_TASK]->(t5)
MERGE (s2)-[:HAS_TASK]->(t3)
MERGE (s2)-[:HAS_TASK]->(t5)
MERGE (s3)-[:HAS_TASK]->(t4)
MERGE (s3)-[:HAS_TASK]->(t5)
