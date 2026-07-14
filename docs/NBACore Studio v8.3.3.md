# NBACore Studio v8.3.3

# Custom Formula Engine Specification

> Version: 8.3.3
> Module Type: Calculation Engine
> Status: Development Specification
> Parent: NBACore Studio v8.3 Analytics Workspace

---

# 1. Overview

## 1.1 Purpose

Custom Formula Engine provides user-defined basketball metric calculation.

The engine allows users to create:

* Player evaluation models
* Custom rankings
* Team impact scores
* Historical comparison formulas
* League adaptation models

---

# 2. Design Goal

Traditional:

```id="h9d0s2"
Developer creates metric

↓

User only views result
```

New:

```id="0q8n2p"
User creates formula

↓

System calculates metric

↓

Save as reusable asset

```

---

# 3. Supported Usage Modes

## Mode 1: Visual Formula Builder

For normal users.

Example:

```
PTS

+

AST × 1.5

+

TS%

```

---

## Mode 2: Formula Editor

For advanced users.

Example:

```text
PTS*0.3
+
AST*0.2
+
TS_PCT*20
```

---

## Mode 3: Node Engine

For analysts.

Example:

```
[PTS]

 |

[Weight]

 |

[Normalize]

 |

[Ranking]

```

---

# 4. Architecture

```id="1yqv8j"
              Formula Engine


                    |


 ------------------------------------------------

 |                 |                 |

Parser          Validator        Calculator


                    |


              Result Generator


                    |


             Data Asset System

```

---

# 5. Backend Structure

Recommended:

```id="n2s0px"
backend/


services/


formula_engine/


├── parser.py

├── ast_builder.py

├── validator.py

├── calculator.py

├── function_library.py

├── formula_manager.py

└── models.py

```

---

# 6. Formula Data Model

## Formula Object

Python:

```python id="8k9z3m"
class Formula:


    def __init__(

        self,

        name,

        expression

    ):


        self.name=name

        self.expression=expression


        self.variables=[]

        self.version="1.0"

        self.author=None

```

---

# 7. Database Design

## custom_formulas

```sql id="g5h7oi"
CREATE TABLE custom_formulas (

id INTEGER PRIMARY KEY,


name TEXT,


description TEXT,


expression TEXT,


variables JSON,


version TEXT,


owner_id INTEGER,


visibility TEXT,


created_at DATETIME

);

```

---

# 8. Formula Syntax

## Supported Operators

Basic:

```
+

-

*

/

()

```

---

## Comparison

```
>

<

>=

<=

==

```

---

## Functions

Built-in:

```
AVG()

MAX()

MIN()

SUM()

RANK()

NORMALIZE()

PERCENTILE()

```

---

# 9. Variable System

Formula variables come from Data Asset System.

Example:

Formula:

```
PTS*0.4+AST*0.3
```

Variables:

```json id="5v6w3y"
[
"PTS",

"AST"

]

```

---

# 10. Formula Parsing

## Requirement

Never directly execute user input.

Forbidden:

```python
eval(user_formula)
```

---

Correct:

```
Formula

↓

Parser

↓

AST Tree

↓

Validator

↓

Safe Executor

```

---

# 11. Parser Implementation

File:

```
parser.py
```

Example:

```python id="f5m9y1"
import ast


class FormulaParser:


    def parse(
        self,
        expression
    ):


        tree = ast.parse(

            expression,

            mode="eval"

        )


        return tree

```

---

# 12. AST Validation

Purpose:

Prevent malicious operations.

Allowed:

```
Expression

Binary Operation

Numbers

Variables

Functions

```

Forbidden:

```
Import

File

System Call

Class

Lambda

```

---

Implementation:

```python id="8j0y1f"
class FormulaValidator:


    allowed = [

        "Expression",

        "BinOp",

        "Name",

        "Num"

    ]


    def validate(self,tree):


        for node in ast.walk(tree):

            if type(node).__name__ not in self.allowed:

                raise Exception(
                "Unsafe Formula"
                )

        return True

```

---

# 13. Safe Calculator

File:

```
calculator.py
```

Example:

```python id="v3v3kw"
class FormulaCalculator:


    def calculate(

        self,

        ast_tree,

        data

    ):


        return self.evaluate(

            ast_tree.body,

            data

        )

```

---

# 14. Evaluation Logic

Example:

Formula:

```
PTS*0.5+AST*1.5
```

Input:

```json id="3t0gcu"
{

"PTS":30,

"AST":10

}

```

Calculation:

```
30*0.5+10*1.5

=

30

```

---

# 15. Function Library

File:

```
function_library.py
```

Example:

```python id="j7d0gq"
def percentile(values):

    return rank(values)


FUNCTIONS={


"AVG":average,


"PERCENTILE":percentile

}

```

---

# 16. Formula Examples

## MVP Score

```
PTS*0.3

+

AST*0.2

+

REB*0.15

+

TS_PCT*20

```

---

## Two Way Player Score

```
PTS

+

AST*1.5

+

STL*2

+

BLK*2

-

TOV

```

---

## FIBA Adaptation Score

```
NBA_TS*0.5

+

FIBA_TS*0.5

+

ROLE_CHANGE_SCORE

```

---

# 17. Formula Testing Sandbox

Purpose:

Before saving, test formula.

Example:

Dataset:

```
LeBron 2013

Curry 2016

Jokic 2023

```

Output:

```
LeBron

95.2


Curry

93.5


Jokic

96.1

```

---

# 18. Formula Version Control

Every modification creates version.

Example:

```
GOAT Score


v1.0

↓

v1.1

↓

v2.0

```

---

Database:

```sql id="wq8v9b"
CREATE TABLE formula_versions(

id INTEGER PRIMARY KEY,


formula_id INTEGER,


version TEXT,


expression TEXT,


created_at DATETIME

);

```

---

# 19. Formula API

## Create Formula

POST

```
/api/formulas
```

Request:

```json id="h1kg0j"
{

"name":

"My MVP Score",


"expression":

"PTS*0.3+AST*0.2"

}

```

---

## Calculate Formula

POST

```
/api/formulas/{id}/calculate
```

Request:

```json id="0vl6hs"
{

"player":

"LeBron James",


"season":

2013

}

```

---

Response:

```json id="7n6v1c"
{

"formula":

"MVP Score",


"value":

95.4

}

```

---

# 20. Integration With Data Asset System

Flow:

```
User Formula

↓

Variable Extraction

↓

Asset Registry

↓

Load Data

↓

Calculate

↓

Return Result

```

---

Example:

Formula:

```
PTS+AST
```

System:

```
Need:

PTS Asset

AST Asset

```

---

# 21. Integration With Node Builder

Visual Node:

```
PTS Node

     |

Weight Node

     |

AST Node

     |

Formula Output

```

Internally:

Convert into:

```
Formula Expression

```

---

# 22. AI Explanation Interface

Future:

Input:

```
PTS*0.4+TS%*30
```

AI Output:

```
This formula emphasizes scoring volume and efficiency.
It favors elite scorers.

```

---

# 23. Development Tasks

## Phase 1

Implement:

* Formula Model
* Parser
* Validator

---

## Phase 2

Implement:

* Safe Calculator
* Function Library

---

## Phase 3

Implement:

* Formula Storage
* Version System
* Testing Sandbox

---

# 24. Acceptance Criteria

Module completed when:

Users can:

1. Create formula

2. Save formula

3. Execute formula

4. Reuse formula

5. Modify formula versions

6. Use formula inside workspace

---

# 25. Future Extension

Formula Engine will support:

```
Machine Learning Features

Optimization Search

AI Formula Generation

Community Formula Marketplace

```

---

# Final Goal

Custom Formula Engine becomes:

"The calculation brain of NBACore."

Every basketball evaluation model should be creatable, stored, tested, and shared through this engine.

---
