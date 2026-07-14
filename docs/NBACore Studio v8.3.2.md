# NBACore Studio v8.3.2

# Data Asset System Specification

> Version: 8.3.2
> Module Type: Data Management Layer
> Status: Development Specification
> Parent: NBACore Studio v8.3 Analytics Workspace

---

# 1. Overview

## 1.1 Purpose

Data Asset System manages all basketball analysis resources inside NBACore.

The system converts raw data into reusable analytical assets.

---

Traditional model:

```
Database Field

↓

Statistic
```

New model:

```
Raw Data

↓

Data Asset

↓

Analytics Tool

↓

User Model
```

---

# 2. Core Concept

A Data Asset is any reusable basketball data element.

Examples:

Basic:

```
Points
Assists
Rebounds
```

Advanced:

```
TS%
BPM
VORP
```

Intelligence:

```
Player Role
Player DNA
Peak Score
```

Custom:

```
User Created Metric
```

---

# 3. Architecture

```
                 Data Asset Engine


                       |


 ------------------------------------------------

 |                    |                         |

Basic Pool       Advanced Pool           Intelligence Pool


                       |


              Custom Asset Pool


                       |


             Analytics Workspace

```

---

# 4. Responsibility Boundary

Data Asset System is responsible for:

## Asset Registration

Register available metrics.

## Asset Metadata

Describe:

* Name
* Category
* Formula
* Source
* Usage

## Asset Discovery

Allow users to search and select assets.

## Asset Permission

Control:

* System asset
* User asset
* Shared asset

---

# 5. Data Pool Design

## 5.1 Basic Data Pool

Purpose:

Provide common basketball statistics.

Examples:

```
PTS

REB

AST

STL

BLK

TOV

PF

FGM

FGA

3PM

3PA

FTM

FTA

MIN

GP

```

---

Metadata Example:

```json
{
"name":"Points",

"code":"PTS",

"type":"basic",

"unit":"point",

"description":
"Total points scored"

}
```

---

# 5.2 Advanced Data Pool

Purpose:

Provide analytical statistics.

Examples:

```
TS%

eFG%

USG%

AST%

ORB%

DRB%

BPM

VORP

WS

PER

```

---

Example:

```json
{
"name":"True Shooting Percentage",

"code":"TS_PCT",

"type":"advanced",

"formula":

"PTS/(2*(FGA+0.44*FTA))"

}
```

---

# 5.3 Intelligence Data Pool

Source:

v8.2 Intelligence Engine

Examples:

```
Player Role

Player DNA

Peak Score

Similarity Score

Availability Score

Era Adjustment

```

---

Example:

```json
{
"name":

"Primary Creator Score",


"type":

"intelligence",


"source":

"role_classifier"

}
```

---

# 5.4 Custom Data Pool

Created by users.

Examples:

```
Deo GOAT Score

Defense Monster Index

FIBA Adaptation Score

```

---

# 6. Data Asset Model

Python:

```python
class DataAsset:


    def __init__(

        self,

        name,

        code,

        category

    ):

        self.name=name

        self.code=code

        self.category=category


        self.formula=None

        self.source=None

        self.permissions=[]

```

---

# 7. Database Design

## Table: data_assets

```sql
CREATE TABLE data_assets (

id INTEGER PRIMARY KEY,


name TEXT NOT NULL,


code TEXT UNIQUE,


category TEXT,


asset_type TEXT,


description TEXT,


formula TEXT,


source TEXT,


owner_id INTEGER,


visibility TEXT,


created_at DATETIME

);

```

---

# 8. Asset Category

Allowed:

```
basic

advanced

intelligence

custom

external

```

---

# 9. Asset Registry

File:

```
data_asset_engine/asset_registry.py
```

Purpose:

Maintain all available assets.

---

Code:

```python
class AssetRegistry:


    def __init__(self):

        self.assets={}



    def register(
        self,
        asset
    ):

        self.assets[
            asset.code
        ]=asset



    def get(
        self,
        code
    ):

        return self.assets.get(code)

```

---

# 10. Asset Search System

Users should search:

Example:

Input:

```
shooting
```

Return:

```
FG%

3P%

TS%

eFG%

Shot Profile

```

---

Search Index:

```
asset_name

description

category

tags

```

---

# 11. Asset Tag System

Each asset supports tags.

Example:

TS%:

```
shooting

efficiency

offense

advanced

```

---

Database:

```sql
CREATE TABLE asset_tags(

asset_id INTEGER,

tag TEXT

);

```

---

# 12. Asset Dependency System

Some assets depend on others.

Example:

BPM:

```
Box Score

+

Advanced Calculation

+

League Context

```

---

Dependency:

```json
{
"asset":

"BPM",


"requires":

[
"PTS",
"AST",
"REB"
]

}
```

---

# 13. Asset Version System

Important for formula evolution.

Example:

```
TS%

v1

↓

v2

↓

v3

```

---

Database:

```sql
CREATE TABLE asset_versions(

id INTEGER PRIMARY KEY,

asset_id INTEGER,

version TEXT,

formula TEXT,

created_at DATETIME

);

```

---

# 14. User Custom Asset Creation

API:

```
POST

/api/assets/create

```

Request:

```json
{

"name":

"My Impact Score",


"formula":

"PTS*0.4+AST*0.3",


"category":

"custom"

}

```

---

# 15. Asset Validation

Before registration:

Check:

```
Formula valid

Variables exist

Dependencies available

No unsafe operation

```

---

# 16. Workspace Integration

Workspace stores:

```
workspace

|

+ selected assets

|

+ formulas

|

+ visualization

```

---

Example:

Workspace:

```
Jokic Analysis

Assets:

PTS

AST

BPM

VORP

My MVP Score

```

---

# 17. Asset Recommendation System

Future AI feature.

Example:

User selects:

```
Compare Scoring Guards
```

System recommends:

```
PTS

TS%

USG%

3P Rate

AST%

```

---

# 18. API Design

## List Assets

GET

```
/api/assets
```

Response:

```json
[
{
"name":"PTS",

"type":"basic"
},

{
"name":"TS%",

"type":"advanced"
}
]

```

---

## Get Asset

GET

```
/api/assets/{code}

```

---

## Create Asset

POST

```
/api/assets

```

---

# 19. Development Structure

Backend:

```
backend/


services/


data_asset_engine/


├── asset_manager.py

├── asset_registry.py

├── asset_search.py

├── asset_validator.py

└── models.py

```

---

# 20. Testing Requirements

## Unit Tests

Required:

```
Register asset

Search asset

Load asset

Validate dependency

Create custom asset

```

---

# 21. Development Tasks

## Phase 1

Implement:

* Asset Model
* Database
* Registry

---

## Phase 2

Implement:

* Search
* Tags
* Categories

---

## Phase 3

Implement:

* Custom assets
* Version control

---

# 22. Acceptance Criteria

Completed when:

Users can:

1. Browse available metrics

2. Select metrics into workspace

3. Create custom metrics

4. Save custom assets

5. Reuse assets in future projects

---

# 23. Future Extension

Data Asset System will support:

```
Community Asset Marketplace

AI Recommended Metrics

League Specific Assets

Real-time Data Assets

```

---

# Final Goal

Data Asset System becomes:

"The basketball knowledge library of NBACore."

Every statistic, metric, and intelligence output should exist as a reusable asset.

---
