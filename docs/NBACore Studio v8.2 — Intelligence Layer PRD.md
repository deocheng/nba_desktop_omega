# NBACore Studio v8.2 — Intelligence Layer PRD

> Version: 8.2.0
> Upgrade Type: Player Intelligence & Context Analysis
> Based on: NBACore Studio v8.1 Metric Expansion
> Status: Planning Specification

---

# 1. Overview

## 1.1 Purpose

NBACore Studio v8.2 introduces the Intelligence Layer.

The objective is transforming NBACore from:

```
NBA Statistics Viewer
```

into:

```
NBA Player Intelligence Platform
```

---

# 2. Design Philosophy

Traditional basketball statistics answer:

> What happened?

v8.2 answers:

> Why did it happen?

and:

> What type of player produced these results?

---

# 3. Architecture Impact

## 3.1 Architecture Extension

Existing:

```
Frontend
    |
API Layer
    |
Metric Engine
    |
Data Layer
```

New:

```
Frontend
    |
API Layer
    |
Intelligence Engine
    |
Metric Engine
    |
Data Layer
```

---

# 4. Intelligence Engine

New service:

```
backend/services/intelligence_engine/
```

Responsibilities:

* Player classification
* Context adjustment
* Similarity analysis
* Career trajectory analysis
* Historical comparison

---

# 5. Pace Adjusted Statistics

## 5.1 Purpose

Different eras and teams have different possessions.

Raw statistics cannot directly compare players.

---

## New Metrics

```
adjusted_points
adjusted_assists
adjusted_rebounds
adjusted_usage
```

---

## Formula

```
Adjusted Stat = 
Player Stat × League Average Pace / Team Pace
```

---

## Usage

Example:

Compare:

* 1990s low pace players
* Modern high pace players

---

# 6. Era Adjustment System

## 6.1 New Module

```
era_adjustment.py
```

---

## Supported Adjustments

```
Pace
League Scoring
Three Point Environment
Rule Changes
```

---

## Output

Example:

```
Player Season

Raw PPG:
28.0

Era Adjusted PPG:
31.5
```

---

# 7. Availability Intelligence

## 7.1 Purpose

Player value depends on availability.

---

## New Metrics

### Availability Score

Formula:

```
Games Played / Team Games
```

---

### Minutes Share

Formula:

```
Player Minutes / Team Minutes
```

---

## Display

Component:

```
AvailabilityCard
```

Example:

```
Availability

Games:
78/82

Score:
95%
```

---

# 8. Player Role Classification

## 8.1 New Feature

Name:

```
Player Role Engine
```

---

## Goal

Automatically classify player archetypes.

---

## Role Types

```
Primary Creator

Secondary Creator

Scoring Guard

3&D Wing

Shot Creator

Rim Protector

Stretch Big

Two Way Star

Role Player
```

---

## Input Metrics

```
USG%
AST%
TS%
3P Rate
REB%
BLK%
STL%
```

---

## Output Example

```
LeBron James

Primary Creator
+
Point Forward
+
Transition Engine
```

---

# 9. Player DNA System

## 9.1 Purpose

Create a basketball identity profile.

---

## New Component

```
PlayerDNAChart
```

---

## Dimensions

```
Scoring
Playmaking
Defense
Rebounding
Efficiency
Durability
Leadership
```

---

## Example

```
Player DNA

Scoring        █████████
Passing        ██████████
Defense        ███████
Rebounding     ███████
Efficiency     ████████
```

---

# 10. Scoring Profile Analysis

## 10.1 New Module

```
scoring_profile.py
```

---

## Categories

```
At Rim

Post Up

Isolation

Pick & Roll

Spot Up

Transition

Pull Up
```

---

## Purpose

Differentiate:

Same points ≠ Same scoring ability

---

# 11. Clutch Performance Module

## 11.1 Definition

Clutch:

```
Last 5 minutes
Point Difference <= 5
```

---

## Metrics

```
Clutch Points

Clutch TS%

Clutch FG%

Clutch Assists

Clutch Turnovers
```

---

## Component

```
ClutchPerformanceCard
```

---

# 12. Season Type Separation

## 12.1 Database Change

Add:

```
season_type
```

Values:

```
regular

playoffs

play_in
```

---

## Requirement

All metrics must support:

```
season_type filter
```

---

# 13. Peak Performance Analysis

## 13.1 Purpose

Compare players using peak ability.

---

## New Metrics

```
Peak PPG

Peak TS%

Peak BPM

Peak WS

Peak VORP
```

---

## Definition

Default:

Best consecutive 5 seasons

---

## Component

```
PeakComparisonCard
```

---

# 14. Age Curve Analysis

## 14.1 Purpose

Analyze development and decline.

---

## New Chart

```
AgeCurveChart
```

---

## X Axis

```
Player Age
```

---

## Y Axis

```
Performance Index
```

---

## Applications

Identify:

* Early peak
* Late development
* Longevity

---

# 15. Similar Player Evolution

## 15.1 Upgrade Existing Similar Player System

Old:

```
Who is similar?
```

New:

```
Who developed similarly?
```

---

## Comparison

Timeline:

```
Age 20

Player A

↓

Age 25

Player B

↓

Age 30

Player C
```

---

# 16. Historical Percentile Ranking

## 16.1 Purpose

Provide historical context.

---

## Example

```
Career PPG

27.2

Historical Percentile:

98.5%
```

---

## Supported Metrics

```
PPG

TS%

AST

REB

BPM

VORP
```

---

# 17. Data Confidence System

## 17.1 Purpose

Handle incomplete historical data.

---

## New Field

```
data_confidence
```

---

## Levels

```
A

Complete modern data

B

Partial advanced data

C

Historical estimate
```

---

## API Example

```json
{
 "metric":"def_rating",
 "value":105,
 "confidence":"B"
}
```

---

# 18. Frontend Components

New components:

```
frontend/components/

├── PlayerDNAChart.js
├── RoleClassificationCard.js
├── AvailabilityCard.js
├── ClutchPerformanceCard.js
├── PeakComparisonCard.js
├── AgeCurveChart.js
├── HistoricalPercentile.js
└── EraAdjustmentPanel.js
```

---

# 19. API Expansion

## Player Intelligence API

New:

```
GET /players/{id}/intelligence
```

Response:

```json
{
 "role":
 "Primary Creator",

 "dna":
 {
  "scoring":90,
  "passing":95,
  "defense":80
 },

 "availability":0.94,

 "peak":{
  "season":"2012",
  "bpm":11.5
 }
}
```

---

# 20. Development Priority

## Phase 8.2-A

Core Intelligence

1. Pace Adjustment
2. Availability Score
3. Season Type Separation
4. Historical Percentile

---

## Phase 8.2-B

Player Understanding

1. Role Classification
2. Player DNA
3. Scoring Profile

---

## Phase 8.2-C

Advanced Analysis

1. Clutch Performance
2. Peak Comparison
3. Age Curve
4. Similar Evolution

---

# 21. Acceptance Criteria

## Intelligence Engine

* Independent calculation layer
* Metric reusable
* Fully tested

## API

* Returns intelligence objects
* No frontend calculations

## Frontend

* Explains player characteristics
* Provides historical context

---

# 22. Final Goal

After v8.2:

NBACore provides:

```
Statistics
+
Advanced Metrics
+
Context Adjustment
+
Player Identity
+
Career Understanding
+
Historical Comparison
```

The platform evolves from:

"NBA database"

into:

"Basketball intelligence system"

---
