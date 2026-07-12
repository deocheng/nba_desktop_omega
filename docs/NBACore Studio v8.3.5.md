# NBACore Studio v8.3.5

# Data Import & Multi League Specification

> Version: 8.3.5
> Module Type: Data Integration Layer
> Status: Development Specification
> Parent: NBACore Studio v8.3 Analytics Workspace

---

# 1. Overview

## 1.1 Purpose

Data Import & Multi League System enables NBACore to accept external basketball datasets and convert them into a unified analytical format.

---

Traditional system:

```
NBA Database

↓

NBA Analysis
```

---

New system:

```
Any Basketball Dataset

↓

Data Mapping

↓

Unified Basketball Schema

↓

NBACore Analytics Engine

```

---

# 2. Product Goal

Support:

* NBA
* FIBA
* NCAA
* European leagues
* User-created competitions

Allow users to:

* Upload Excel
* Upload CSV
* Connect API
* Import database
* Create custom league

---

# 3. Architecture

```
                 Import Engine


                       |


 -------------------------------------------------

 |                 |                |

File Parser     Mapper Engine    Validator


                       |

              Unified Schema


                       |

              Data Asset System


```

---

# 4. Module Responsibility

## Import Engine

Responsible for:

* Reading external files
* Parsing data
* Detecting columns

---

## Mapping Engine

Responsible for:

* Matching user fields
* Converting naming differences

---

## Validator

Responsible for:

* Data quality checking
* Missing values
* Type validation

---

## League Adapter

Responsible for:

* Rules differences
* Competition metadata

---

# 5. Supported Input Formats

## CSV

Example:

```
player,pts,reb,ast

James,27.1,7.5,7.2

```

---

## Excel

Supported:

```
.xlsx

.xls

```

---

## JSON

Example:

```json
{
"player":"Jokic",
"points":26
}

```

---

## API

Future:

```
GET /external/player/stats
```

---

# 6. Import Workflow

```
Upload File

↓

File Detection

↓

Column Recognition

↓

Schema Mapping

↓

Data Validation

↓

League Identification

↓

Import Database

↓

Create Data Asset

```

---

# 7. Unified Basketball Schema

## Purpose

All basketball data must eventually convert into this structure.

---

## Player Game Record

```python
class BasketballRecord:


    player_id:str

    player_name:str


    team_id:str

    team_name:str


    league:str

    competition:str


    season:str

    season_type:str


    games:int

    minutes:float


    points:float

    rebounds:float

    assists:float

    steals:float

    blocks:float

    turnovers:float

    fouls:float

```

---

# 8. Extended Schema

Advanced fields:

```python
class AdvancedRecord:


    ts_percent:float

    usage_rate:float

    bpm:float

    vorp:float


    offensive_rating:float

    defensive_rating:float

```

---

# 9. Competition Context Model

Important:

Different leagues have different environments.

```python
class CompetitionContext:


    league:str


    season:str


    rule_set:str


    quarter_length:int


    three_point_distance:float


    court_size:str

```

---

Example:

## NBA

```
league:

NBA


quarter_length:

12


three_point_distance:

7.24

```

---

## FIBA

```
league:

FIBA


quarter_length:

10


three_point_distance:

6.75

```

---

# 10. Column Mapping System

Problem:

Different data sources:

NBA:

```
PTS
REB
AST
```

User Excel:

```
Score
Board
Pass

```

---

Solution:

Mapping:

```
Score

↓

PTS


Board

↓

REB


Pass

↓

AST

```

---

# 11. Mapping Model

```python
class FieldMapping:


    source_field:str


    target_field:str


    confidence:float


```

---

Example:

```json
{
"source":

"Score",


"target":

"points",


"confidence":

0.96

}

```

---

# 12. Automatic Field Recognition

System uses:

* Name matching
* Dictionary matching
* AI assistance

Example:

Input:

```
FG%

```

Recognize:

```
field:

field_goal_percentage

```

---

# 13. Mapping Dictionary

File:

```
mapping_dictionary.json
```

Example:

```json
{

"pts":

"points",


"score":

"points",


"reb":

"rebounds",


"boards":

"rebounds"

}

```

---

# 14. Data Validation

Before import:

Check:

```
Required fields exist

Numbers valid

Player identity valid

Season format valid

League defined

```

---

Example:

Invalid:

```
points="abc"

```

Reject.

---

# 15. Data Cleaning

Operations:

```
Remove duplicate rows

Convert units

Handle missing values

Normalize names

```

---

Example:

Before:

```
Nikola Jokic

Nikola Jokić

```

After:

```
Nikola Jokic

```

---

# 16. Player Identity Matching

Important for cross league.

Example:

NBA:

```
Luka Doncic

```

FIBA:

```
Luka Dončić

```

Need:

```
player_id

```

instead of name.

---

# 17. League Adapter System

Architecture:

```
league_adapter/


├── nba_adapter.py

├── fiba_adapter.py

├── ncaa_adapter.py

└── custom_adapter.py

```

---

Example:

```python
class NBAAdapter:


    def normalize(record):

        return unified_record

```

---

# 18. Custom League Creation

Users can create:

Example:

```
Chinese Basketball League

European Cup

School League

```

---

Required:

```
League Name

Season

Rules

Statistics Mapping

```

---

# 19. Database Design

## datasets

```sql
CREATE TABLE datasets(

id INTEGER PRIMARY KEY,


name TEXT,


source TEXT,


league TEXT,


season TEXT,


schema_version TEXT,


created_at DATETIME

);

```

---

## import_history

```sql
CREATE TABLE import_history(

id INTEGER PRIMARY KEY,


dataset_id INTEGER,


filename TEXT,


status TEXT,


created_at DATETIME

);

```

---

# 20. Import API

## Upload Dataset

POST

```
/api/import/upload

```

---

Response:

```json
{

"task_id":

1001,


"status":

"processing"

}

```

---

# 21. Mapping API

POST

```
/api/import/mapping

```

---

Example:

```json
{

"PTS":

"points",


"REB":

"rebounds"

}

```

---

# 22. Validation API

GET

```
/api/import/{id}/validate

```

---

Response:

```json
{

"valid":

true,


"errors":[]

}

```

---

# 23. Workspace Integration

Imported datasets become assets.

Flow:

```
Import

↓

Dataset

↓

Data Asset

↓

Workspace

```

---

Example:

User uploads:

```
FIBA_WorldCup_2027.xlsx

```

System creates:

```
Dataset:

FIBA World Cup 2027


Assets:

PTS

REB

AST

```

---

# 24. Development Structure

Backend:

```
backend/


services/


import_engine/


├── importer.py

├── parser.py

├── mapper.py

├── validator.py

├── cleaner.py

└── adapters/

```

---

# 25. Development Roadmap

## Phase 1

Implement:

* CSV Import
* Excel Import
* Basic Mapping

---

## Phase 2

Implement:

* Schema Conversion
* Validation
* Cleaning

---

## Phase 3

Implement:

* League Adapter
* Multi League Support

---

# 26. Testing Requirements

Test:

```
Import CSV

Import Excel

Map fields

Reject invalid data

Convert league format

Create dataset

```

---

# 27. Acceptance Criteria

Module completed when:

Users can:

1. Upload basketball data

2. Map custom fields

3. Import into NBACore

4. Analyze different leagues

5. Compare players across competitions

---

# 28. Future Extension

Support:

```
Live Data API

Automatic Web Crawler

AI Data Mapping

Community Dataset Sharing

Real-time League Tracking

```

---

# Final Goal

Data Import & Multi League System becomes:

"The universal basketball data gateway of NBACore."

Any basketball data source should be able to enter the NBACore ecosystem.

---
