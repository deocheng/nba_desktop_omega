# NBACore Studio v8.3.4

# Analytics Node Builder Specification

> Version: 8.3.4
> Module Type: Visual Analytics Engine
> Status: Development Specification
> Parent: NBACore Studio v8.3 Analytics Workspace

---

# 1. Overview

## 1.1 Purpose

Analytics Node Builder provides a visual programming environment for basketball analysis.

Users can create analytical workflows by connecting nodes.

---

Traditional:

```id="r8w7su"
Select Metric

↓

Write Formula

↓

Calculate

↓

Chart
```

New:

```id="7s0h0b"
Drag Data Node

↓

Connect Processing Node

↓

Generate Result

↓

Visualize

```

---

# 2. Product Goal

Enable users to build:

* Player evaluation models
* Team analysis systems
* League comparison models
* Scouting tools
* Custom rankings

without writing code.

---

# 3. Architecture

```id="6w9v4a"
              Node Builder Engine


                     |


 -------------------------------------------------

 |              |              |                 |

Node Model   Graph Engine   Executor       Converter


                     |


              Formula Engine


                     |


              Data Asset System

```

---

# 4. Core Concept

A Node represents:

* Data input
* Calculation operation
* Transformation
* Output

Example:

```id="4x1x5j"
[PTS]

  |

[Weight 0.4]

  |

        +

  |

[AST]

  |

[Score]

```

---

# 5. Node Types

## 5.1 Data Node

Purpose:

Provide data source.

Examples:

```id="z5zv2n"
Points

Assists

TS%

BPM

Player Age

League

```

---

Input:

None

Output:

```json id="0u5z0j"
{
"type":"number",

"name":"PTS"

}

```

---

# 5.2 Operator Node

Basic calculation.

Supported:

```id="8f8m4k"
Add

Subtract

Multiply

Divide

Average

Maximum

Minimum

```

---

Example:

```
PTS

 |

Multiply

 |

0.5

```

---

# 5.3 Statistical Node

Advanced operations.

Examples:

```id="h0bq3c"
Normalize

Percentile

Rank

Z Score

Moving Average

```

---

Example:

Career ranking:

```
Career PPG

↓

Percentile

↓

Historical Rank

```

---

# 5.4 Filter Node

Purpose:

Select data.

Examples:

```id="5sqvnr"
Season > 2010


Playoffs Only


Age < 25


Position = Guard

```

---

# 5.5 Aggregation Node

Combine data.

Examples:

```id="gq7h3c"
Career Average

Peak 5 Years

Season Maximum

Playoff Average

```

---

# 5.6 Output Node

Produces result.

Examples:

```id="xx4k5d"
Score

Table

Chart

Ranking

Report

```

---

# 6. Node Data Model

Python:

```python id="z4dyk4"
class Node:


    def __init__(

        self,

        node_id,

        node_type

    ):


        self.id=node_id

        self.type=node_type


        self.inputs=[]

        self.outputs=[]


        self.parameters={}

```

---

# 7. Connection Model

Nodes connect through edges.

```python id="qtx9cv"
class Connection:


    source_node

    source_port


    target_node

    target_port

```

---

Example:

```id="r6fw9j"
PTS Node

output

  |

input

Weight Node

```

---

# 8. Graph Structure

The complete analysis is a DAG.

Directed Acyclic Graph:

```id="n7ht8a"
Node A

  |

Node B

  |

Node C

```

---

Requirements:

* No circular dependency
* Execution order automatic
* Error detection

---

# 9. Graph Data Format

Saved as:

```json id="p9k9t0"
{

"nodes":[


{

"id":"node1",

"type":"DATA",

"value":"PTS"

},


{

"id":"node2",

"type":"WEIGHT",

"value":0.5

}


],


"connections":[


{

"from":"node1",

"to":"node2"

}


]

}

```

---

# 10. Node Executor

File:

```
node_engine/executor.py
```

Responsibilities:

* Resolve dependencies
* Execute nodes
* Return output

---

Example:

```python id="zqk6hx"
class NodeExecutor:


    def execute(

        self,

        graph

    ):


        order = graph.topological_sort()


        for node in order:

            node.execute()

```

---

# 11. Graph Validation

Before execution:

Check:

```id="82q0k7"
Missing input

Invalid connection

Circular dependency

Unsupported data type

```

---

Example:

```python id="8f6z4n"
class GraphValidator:


    def validate(graph):


        if graph.has_cycle():

            raise Exception(
            "Invalid Graph"
            )

```

---

# 12. Node To Formula Conversion

Important:

Visual workflow must eventually become Formula Engine expression.

Example:

Visual:

```
PTS

 |

×0.3


AST

 |

×0.2


+

```

Convert:

```text
PTS*0.3+AST*0.2
```

---

Implementation:

```python id="2plp5d"
class FormulaConverter:


    def convert(graph):

        return expression

```

---

# 13. Example Workflow

## MVP Model

Visual:

```
PTS

 |

Weight(0.3)


REB

 |

Weight(0.15)


AST

 |

Weight(0.2)


        SUM


          |

      MVP Score

```

Generated Formula:

```
PTS*0.3+
REB*0.15+
AST*0.2

```

---

# 14. Frontend Architecture

Recommended:

```
frontend/


components/


node_editor/


├── Canvas.jsx

├── Node.jsx

├── Connection.jsx

├── NodePanel.jsx

└── PropertyPanel.jsx

```

---

# 15. User Interface

## Left Panel

Node Library:

```
Data

Math

Statistics

Filter

Output

```

---

## Center

Canvas:

```
Drag Node

Connect Node

Move Node

Zoom

```

---

## Right Panel

Properties:

```
Weight:

0.3


Function:

Normalize

```

---

# 16. Node Library System

New nodes can be registered.

Example:

```python id="g3y0cu"
NodeRegistry.register(

    "TS_Normalize",

    NormalizeNode

)

```

---

# 17. AI Assisted Node Creation

Future:

User:

"Create a defensive impact model"

AI generates:

```
STL

+

BLK

+

DRB%

-

PF

```

---

# 18. Workspace Integration

Node graphs belong to Workspace.

Structure:

```
Workspace


 |

Node Graph


 |

Formula


 |

Result


 |

Chart

```

---

# 19. API Design

## Save Graph

POST

```
/api/workspaces/{id}/graphs

```

Request:

```json id="g9gq1r"
{

"name":

"Defense Model",


"graph":

{}

}

```

---

## Execute Graph

POST

```
/api/graphs/{id}/execute

```

---

Response:

```json id="6v7m7m"
{

"result":

92.5

}

```

---

# 20. Backend Structure

```
backend/


services/


node_engine/


├── node.py

├── graph.py

├── executor.py

├── validator.py

├── registry.py

└── converter.py

```

---

# 21. Development Roadmap

## Phase 1

Implement:

* Node Model
* Connection Model
* Graph Storage

---

## Phase 2

Implement:

* Executor
* Validation
* Formula Conversion

---

## Phase 3

Implement:

* Frontend Node Editor
* Node Library

---

# 22. Testing Requirements

Test:

```id="f0j0mv"
Create Node

Connect Node

Execute Graph

Detect Cycle

Convert Formula

Save Graph

```

---

# 23. Acceptance Criteria

Completed when:

User can:

1. Drag basketball data nodes

2. Connect calculation nodes

3. Generate analysis result

4. Save workflow

5. Reopen and edit workflow

---

# 24. Future Extension

Possible:

```id="5fd6l9"
AI Generated Analysis Graph

Community Node Marketplace

Real-time Data Pipeline

Machine Learning Nodes

```

---

# Final Goal

Analytics Node Builder becomes:

"The visual programming environment for basketball analytics."

It allows anyone to build basketball models without coding.

---
