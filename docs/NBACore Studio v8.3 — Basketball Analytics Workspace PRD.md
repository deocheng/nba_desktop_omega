# NBACore Studio v8.3 — Basketball Analytics Workspace PRD

> Version: 8.3.0
> Upgrade Type: Platform Transformation
> Based on: NBACore Studio v8.2 Intelligence Layer
> Status: Strategic Architecture Specification

---

# 1. Vision

## 1.1 Product Evolution

NBACore Studio evolution:

```
v8.0

NBA Database System


v8.1

Advanced Basketball Metrics


v8.2

Player Intelligence System


v8.3

Basketball Analytics Workspace
```

---

# 2. Core Objective

Create an open basketball analytics environment.

Users can:

* Import basketball data
* Build custom metrics
* Create evaluation models
* Compare leagues
* Analyze players
* Share analytical projects

---

# 3. Product Positioning

NBACore becomes:

```
Basketball Data Platform

+

Analytics Laboratory

+

Model Creation Environment
```

Comparable concepts:

* Spreadsheet flexibility
* Data visualization power
* Notebook analysis capability

---

# 4. New Architecture

## 4.1 Architecture Extension

Existing:

```
Frontend

API Layer

Intelligence Engine

Metric Engine

Data Layer
```

New:

```
                 User Interface

                       |

          Analytics Workspace Engine


        /              |              \


Data Asset       Formula Engine    Visualization

Engine


                       |

             Unified Basketball Schema


                       |

------------------------------------------------

NBA      FIBA      NCAA      User Dataset

```

---

# 5. Analytics Workspace

## 5.1 Purpose

Create a persistent analysis environment.

Similar to:

* Photoshop Project
* Jupyter Notebook
* Tableau Workbook

---

## 5.2 Project File

Extension:

```
.nbacore
```

Contains:

```json
{
"name":"LeBron vs Jordan",

"datasets":[],

"formulas":[],

"charts":[],

"filters":[],

"notes":[]

}
```

---

# 6. Data Asset Library

## 6.1 Purpose

Provide reusable basketball data components.

---

# Data Pool Structure

## Basic Data Pool

Traditional statistics:

```
Points

Rebounds

Assists

Steals

Blocks

Minutes

Games

FG

3PT

FT

```

---

## Advanced Data Pool

Advanced metrics:

```
TS%

eFG%

USG%

BPM

VORP

WS

PER

ORB%

DRB%

AST%

```

---

## Intelligence Data Pool

From v8.2:

```
Player Role

Player DNA

Peak Score

Era Adjustment

Similarity Score

Availability Score

```

---

# 7. Data Node System

## 7.1 Concept

Users build analysis through nodes.

Example:

```
PTS

 |

Weight Node

 |

+

 |

AST

 |

Score Output

 |

Chart

```

---

# 8. Node Types

## 8.1 Data Node

Input:

```
Player Points

Season

Team Wins

League

Age

```

---

## 8.2 Calculation Node

Basic:

```
+

-

*

/

Average

Maximum

Minimum

```

---

Advanced:

```
Normalize

Percentile

Z Score

Weighted Score

Ranking

```

---

## 8.3 Filter Node

Examples:

```
Season >= 2010


Playoffs Only


Age < 30


Position = Guard

```

---

## 8.4 Aggregation Node

Examples:

```
Career Average


Peak 5 Seasons


Last 3 Seasons


Playoff Career

```

---

# 9. Formula Builder

## 9.1 Purpose

Support advanced users.

Two modes:

---

## Visual Mode

Drag:

```
PTS

+

AST × 1.5

+

TS%

```

---

## Formula Mode

Manual:

```
PTS*0.3
+
AST*0.2
+
TS%*20

```

---

# 10. Formula Library

## 10.1 Storage

Table:

```
custom_formulas
```

Fields:

```
id

name

author

description

formula

version

created_time

usage_count

```

---

# 10.2 Version Control

Example:

```
GOAT Score v1

GOAT Score v2

GOAT Score v3

```

---

# 11. External Data Import System

## 11.1 Supported Formats

```
CSV

Excel

JSON

API

Database

```

---

# 12. Data Import Wizard

Process:

```
Upload File

↓

Field Recognition

↓

Schema Mapping

↓

Validation

↓

Import

```

---

Example:

User file:

```
pts

reb

ast

```

Mapping:

```
pts

↓

Points

```

---

# 13. Unified Basketball Schema

## 13.1 Purpose

Support:

```
NBA

FIBA

NCAA

International Competition

User League

```

---

# 14. Competition Context

New fields:

```
league

competition

season

ruleset

period_length

three_point_distance

court_size

```

Example:

```
NBA_2026

period:

12 minutes


FIBA_2026

period:

10 minutes

```

---

# 15. Cross League Analysis

Example:

```
Player Performance


NBA

↓

FIBA


Changes:

Scoring

Efficiency

Usage

Role

```

---

# 16. Visualization Workspace

Supported outputs:

## Charts

```
Line Chart

Bar Chart

Radar Chart

Scatter Plot

Heat Map

Timeline

```

---

## Dashboard

Users can arrange:

```
Metric Card

Chart

Table

Text Note

```

---

# 17. AI Assistant Integration

Future:

User:

"Create a GOAT ranking formula"

AI generates:

```
Peak Score

Career Value

Championship Impact

Longevity

```

---

AI explains:

```
This model emphasizes longevity and peak dominance.
```

---

# 18. Backend Structure

New:

```
backend/


workspace_engine/


├── project_manager.py

├── data_asset_manager.py

├── formula_builder.py

├── node_engine.py

└── importer.py

```

---

# 19. Core Data Models

## Workspace

```python
class Workspace:

    id

    name

    datasets

    formulas

    charts

```

---

## Formula

```python
class Formula:

    name

    expression

    variables

    version

```

---

## Dataset

```python
class Dataset:

    name

    source

    schema

    league

```

---

# 20. Security Design

Formula execution:

Forbidden:

```
exec()

system()

file access

network access

```

Allowed:

```
Math operations

Registered variables

Safe functions

```

---

# 21. Development Roadmap

## Phase 8.3-A

Foundation

Implement:

* Workspace system
* Formula storage
* Formula execution
* Project save/load

---

## Phase 8.3-B

Analytics Builder

Implement:

* Data nodes
* Formula nodes
* Filter nodes
* Visualization nodes

---

## Phase 8.3-C

Open Platform

Implement:

* CSV import
* Excel import
* External datasets
* Multi league schema

---

# 22. Final Product Goal

After v8.3:

NBACore becomes:

```
Basketball Data

+

Basketball Metrics

+

Basketball Intelligence

+

User Created Models

+

Global Basketball Dataset

```

---

Final vision:

"Every basketball analyst can build their own analytical system on NBACore."

---
