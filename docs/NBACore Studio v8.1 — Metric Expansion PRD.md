\# NBACore Studio v8.1 — Metric Expansion PRD



> Version: 8.1.0

> Upgrade Type: Metric \& Visualization Expansion

> Based on: NBACore Studio v8.0 Architecture

> Status: Development Specification



\---



\# 1. Upgrade Overview



\## 1.1 Purpose



NBACore Studio v8.1 focuses on improving player analysis depth.



The upgrade introduces:



1\. Advanced rebounding analysis

2\. Playmaking efficiency analysis

3\. Defensive activity evaluation

4\. Shooting profile evolution

5\. Career defensive totals

6\. Team scoring contribution analysis



The goal is to move from traditional box-score presentation toward a professional player evaluation system.



\---



\# 2. Architecture Impact



\## 2.1 No Architecture Change



The v8.0 four-layer architecture remains unchanged.



```

Frontend

&#x20;   |

API Layer

&#x20;   |

Metric Engine

&#x20;   |

Data Layer

```



Rules:



\* Frontend only renders data

\* API only orchestrates requests

\* Metric Engine owns all calculations

\* Data Layer only reads database



\---



\# 3. Metric Engine Expansion



\## 3.1 New Basic Metrics



File:



```

backend/services/metric\_engine/metrics/basic.py

```



Add:



\---



\## Offensive Rebound Per Game



Metric:



```

orb\_per\_game

```



Formula:



```

ORB / Games

```



Description:



Average offensive rebounds per game.



\---



\## Defensive Rebound Per Game



Metric:



```

drb\_per\_game

```



Formula:



```

DRB / Games

```



Description:



Average defensive rebounds per game.



\---



\## Assist Turnover Ratio



Metric:



```

ast\_to\_ratio

```



Formula:



```

AST / TOV

```



Minimum denominator:



```

TOV > 0

```



Description:



Playmaking efficiency.



\---



\## Defensive Activity Efficiency



Metric:



```

def\_activity\_efficiency

```



Formula:



```

(STL + BLK) / PF

```



Description:



Defensive events created per personal foul.



Interpretation:



Higher value indicates:



\* More defensive impact

\* Better defensive discipline



\---



\# 4. Rebounding Module Upgrade



\## 4.1 Replace Traditional Rebounding Display



Old:



```

REB

```



New:



```

Rebounding Profile

```



\---



\## Display Metrics



| Metric | Description            |

| ------ | ---------------------- |

| ORB    | Offensive rebounds     |

| DRB    | Defensive rebounds     |

| TRB    | Total rebounds         |

| ORB%   | Offensive rebound rate |

| DRB%   | Defensive rebound rate |



\---



\## Visualization



Component:



```

ReboundingCard

```



Layout:



```

Rebounding



ORB █████

DRB ██████████

TRB █████████████

```



\---



\# 5. Playmaking Module Upgrade



\## New Metrics



| Metric                | Code         |

| --------------------- | ------------ |

| Assists               | ast          |

| Turnovers             | tov          |

| Assist/Turnover Ratio | ast\_to\_ratio |

| Assist Percentage     | ast\_pct      |



\---



\## Visualization



Component:



```

PlaymakingCard

```



Example:



```

AST       9.2

TOV       3.1

AST/TO    2.97

```



\---



\# 6. Defensive Profile Module



\## 6.1 New Defensive Evaluation



Component:



```

DefenseProfileCard

```



Metrics:



| Metric                        | Code |

| ----------------------------- | ---- |

| Steals                        | STL  |

| Blocks                        | BLK  |

| Personal Fouls                | PF   |

| Defensive Activity Efficiency | DAE  |



\---



\## Formula



```

DAE = (STL + BLK) / PF

```



\---



\## Purpose



Used to identify:



\* Defensive anchors

\* Elite perimeter defenders

\* High-impact role players



\---



\# 7. Shooting Profile Evolution



\## 7.1 New Module



Name:



```

Shot Profile Evolution

```



Purpose:



Replace simple shooting hot-zone display.



\---



\## Data Source



Existing:



```

player\_shooting

```



\---



\## Required Data



Zone:



```

Restricted Area

Paint

Mid Range

Corner 3

Above Break 3

```



Fields:



```

zone

FGA

FGM

FG%

FGA%

season

```



\---



\# 7.2 Visualization



Component:



```

ShotProfileChart

```



Chart:



Grouped Bar Chart



Example:



```

Season Change



&#x20;            FG%    FGA%

RA           ████   ███████

Paint        ███    ████

Mid Range    ██     █████

Corner 3     ████   ███

3PT          ███    ██████

```



\---



\# 8. Team Scoring Share



\## 8.1 New Metric



Name:



```

team\_scoring\_share

```



Formula:



```

Player Points / Team Points

```



\---



\## Data Sources



Player:



```

fact\_player\_season\_stats

```



Team:



```

fact\_team\_season\_stats

```



\---



\## Example



```

LeBron James 2006



Player Points:

31.4



Team Points:

97.6



Share:



32.2%

```



\---



\# 8.2 Visualization



Component:



```

TeamContributionChart

```



Display:



Line Chart



```

Team Scoring Share



35%

&#x20;|

30%        \*

&#x20;|

25%

&#x20;|

20%

&#x20;|

&#x20;+----------------

&#x20;2005 2010 2015 2025

```



\---



\# 9. Career Statistics Expansion



\## 9.1 Career Summary Additions



Current:



```

Points

Rebounds

Assists

Games

Minutes

```



Add:



```

Steals

Blocks

Turnovers

Personal Fouls

```



\---



\## Career Defensive Summary



New Component:



```

CareerDefenseSummary

```



Display:



```

Career Defense



STL      2,000+

BLK      1,000+

PF       3,000+

```



\---



\# 10. API Expansion



\## 10.1 Player Detail API



Existing:



```

GET /players/{player\_id}

```



Add response fields:



```json

{

&#x20;   "orb\_per\_game": 2.1,

&#x20;   "drb\_per\_game": 6.5,

&#x20;   "ast\_to\_ratio": 3.2,

&#x20;   "def\_activity\_efficiency": 0.8,

&#x20;   "team\_scoring\_share": 0.31

}

```



\---



\# 10.2 Shooting API



New endpoint:



```

GET /players/{player\_id}/shooting-profile

```



Response:



```json

{

&#x20;   "season":2025,

&#x20;   "zones":\[

&#x20;       {

&#x20;           "zone":"restricted\_area",

&#x20;           "fg\_pct":0.72,

&#x20;           "fga\_rate":0.35

&#x20;       }

&#x20;   ]

}

```



\---



\# 11. Frontend Components



New components:



```

frontend/js/components/



├── ReboundingCard.js

├── PlaymakingCard.js

├── DefenseProfileCard.js

├── ShotProfileChart.js

├── TeamContributionChart.js

└── CareerDefenseSummary.js

```



\---



\# 12. Development Priority



\## Phase 8.1-A Low Cost



Implement:



1\. ORB

2\. DRB

3\. AST/TO

4\. STL

5\. BLK

6\. Career totals



Estimated:



Small change



\---



\## Phase 8.1-B Visualization



Implement:



1\. Rebounding Card

2\. Defense Card

3\. Playmaking Card



\---



\## Phase 8.1-C Advanced Analysis



Implement:



1\. Shot Profile Evolution

2\. Team Scoring Share



Requires:



\* Additional joins

\* Historical data validation



\---



\# 13. Acceptance Criteria



\## Metric Layer



\* All metrics registered in Metric Registry

\* All calculations performed in Metric Engine

\* Unit tests added



\---



\## API Layer



\* No SQL

\* No pandas

\* No calculations



\---



\## Frontend



\* Receives JSON only

\* No statistical computation



\---



\# 14. Final Goal



NBACore Studio v8.1 should provide:



```

Traditional Stats

&#x20;       +

Advanced Metrics

&#x20;       +

Role Analysis

&#x20;       +

Shooting Evolution

&#x20;       +

Team Impact

&#x20;       +

Defensive Evaluation

```



Transforming NBACore from:



"NBA statistics viewer"



into:



"NBA player intelligence analysis platform"



\---



