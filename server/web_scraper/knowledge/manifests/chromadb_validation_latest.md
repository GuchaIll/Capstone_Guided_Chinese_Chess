# ChromaDB Collection Validation Report

- Run at: 2026-04-22T17:25:12.323757+00:00
- Status: failed

## Service Health

- chromadb: OK (HTTP 200)
- embedding: OK (HTTP 200)

## Executive Summary

- count_checks_passed: True
- structure_checks_passed: True
- metadata_checks_passed: True
- semantic_checks_passed: False
- isolation_checks_passed: False
- duplicate_leakage_detected: True
- overall_pass: False

## Collection Counts

| Collection | Expected | Actual | Match | Metadata label sample |
|---|---:|---:|---|---|
| openings | 111 | 111 | True | openings, openings, openings, openings, openings |
| tactics | 31 | 31 | True | tactics, tactics, tactics, tactics, tactics |
| endgames | 80 | 80 | True | endgames, endgames, endgames, endgames, endgames |
| beginner_principles | 199 | 199 | True | beginner_principles, beginner_principles, beginner_principles, beginner_principles, beginner_principles |

## Structural Integrity

### openings

- collection_id: 84c96a97-f8fc-44be-bde5-03995b6230dc
- structural_keys: ['data', 'documents', 'embeddings', 'ids', 'included', 'metadatas', 'uris']
- has_ids: True
- has_documents: True
- has_metadatas: True
- has_embeddings: True
- missing_documents: 0
- missing_metadatas: 0
- missing_embeddings: 0
- metadata mismatches: 0
- sample: Basics of Xiangqi (Chinese Chess) 05 The Opening Phase If we were to dissect the game of Xiangqi or International Chess, we would find that it consists of the Opening Phase , th...
- sample: First Move Initiative/Advantage By default, Red moves first, which gives Red a slight advantage known as the First Move Initiative. Initiative (先手) can be defined as having the ...
- sample: Goals for the Opening System The goal for Red in the opening is to gain traction or momentum in the Opening Phase such that this advantage can turn into a winning position. Ther...

### tactics

- collection_id: df04541e-3bae-492c-b62e-d2555d9481e5
- structural_keys: ['data', 'documents', 'embeddings', 'ids', 'included', 'metadatas', 'uris']
- has_ids: True
- has_documents: True
- has_metadatas: True
- has_embeddings: True
- missing_documents: 0
- missing_metadatas: 0
- missing_embeddings: 0
- metadata mismatches: 0
- sample: Strategical Advice in the Xiangqi (Chinese Chess) Middle Game Author: Jim Png from www.xqinenglish.com Note: This article first appeared on Xiangqi.com. A game of Xiangqi is div...
- sample: based on the principles listed in Grandmaster Liu Dianzhong's book and remains one of the most comprehensive pieces of advice the author has encountered. There were plenty of ex...
- sample: (1) The top priority is to gain control of the situation before attempting to gain positional advantage or material advantage The two colors in Xiangqi are like different sides ...

### endgames

- collection_id: b0e1e534-1ba7-4cc5-8a36-bebb91b052fe
- structural_keys: ['data', 'documents', 'embeddings', 'ids', 'included', 'metadatas', 'uris']
- has_ids: True
- has_documents: True
- has_metadatas: True
- has_embeddings: True
- missing_documents: 0
- missing_metadatas: 0
- missing_embeddings: 0
- metadata mismatches: 0
- sample: The Xiangqi Endgame ---“it starts and ends with the endgame…” In Xiangqi, the end game can be defined as the last phase of the game. Thisphase is usually the stage where the fin...
- sample: Practical Endgames In the last century, advances in endgame theory have allowed Xiangqi experts to identify various situations whereby the result can be predicted with certainty...
- sample: Introduction to Basic Kills in Xiangqi (Chinese Chess) An Introduction to the Basic Kills in Xiangqi (Chinese Chess) After learning how to move the pieces, it would be best to l...

### beginner_principles

- collection_id: a51323ac-7a39-4a75-be30-c16202d34fae
- structural_keys: ['data', 'documents', 'embeddings', 'ids', 'included', 'metadatas', 'uris']
- has_ids: True
- has_documents: True
- has_metadatas: True
- has_embeddings: True
- missing_documents: 0
- missing_metadatas: 0
- missing_embeddings: 0
- metadata mismatches: 0
- sample: Basics of Xiangqi (Chinese Chess) 05 The Opening Phase If we were to dissect the game of Xiangqi or International Chess, we would find that it consists of the Opening Phase , th...
- sample: First Move Initiative/Advantage By default, Red moves first, which gives Red a slight advantage known as the First Move Initiative. Initiative (先手) can be defined as having the ...
- sample: Goals for the Opening System The goal for Red in the opening is to gain traction or momentum in the Opening Phase such that this advantage can turn into a winning position. Ther...

## Canonical Semantic Queries

### openings

- query: central cannon opening strategy control the center early develop pieces in the opening
- expected_best: openings
- actual_best: openings
- pass: True

| Collection | Top distance | Top id | Preview |
|---|---:|---|---|
| openings | 0.3951210379600525 | xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-012 | Cannon: Leading the Charge The Cannon is usually the first piece to be moved. The Central Cannon Opening (中炮 zhōng pào, C2=5) is the most commonly used opening. It has been esti... |
| tactics | 0.5611097092484254 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#tactics#chunk-005 | The Devil is in the Details When the situation and material are even, the deciding factor is usually the position of the pieces. Well-placed pieces with potential for further de... |
| endgames | 0.44077829356841325 | xiangqi.com/all_phases/xiangqi_com_how_to_play#endgames#chunk-026 | 4.2 What are the Common Chinese Chess Opening lines? - Same Direction Cannons Same Direction Cannons - Opposite Direction Cannons Opposite Direction Cannons - Central Cannon vs.... |
| beginner_principles | 0.3951210379600525 | xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-012 | Cannon: Leading the Charge The Cannon is usually the first piece to be moved. The Central Cannon Opening (中炮 zhōng pào, C2=5) is the most commonly used opening. It has been esti... |

### tactics

- query: fork attack pin piece clearance tactic dislodge tactical motif
- expected_best: tactics
- actual_best: tactics
- pass: True

| Collection | Top distance | Top id | Preview |
|---|---:|---|---|
| openings | 0.6279382109642029 | xqinenglish/opening/xqinenglish_choosing_opening#openings#chunk-007 | Tooth for Tooth Style 对攻型 duì gōng xíng As the saying goes, "Attack is the best defense." Tooth for Tooth counters refers to opening lines whereby both colors go at it right fro... |
| tactics | 0.476960316455294 | xqinenglish/middlegame/xqinenglish_tactics_07c_dislodge#tactics#chunk-000 | Chapter 7: Dislodge 逐 Chasing away or dislodging an enemy piece is a type of midgame tactic that is worthy of study. This tactic is used when fighting for the important lines, t... |
| endgames | 0.630553398507667 | xiangqi.com/all_phases/xiangqi_com_how_to_play#endgames#chunk-019 | 3.3 Capturing tactics Here is a list of Xiangqi Capturing tactics: - Fork Fork - Skewer Skewer - Discovered Attack Discovered Attack - Pin Pin - Trapping Trapping - Elimination ... |
| beginner_principles | 0.4769604802131653 | xqinenglish/middlegame/xqinenglish_tactics_07c_dislodge#beginner_principles#chunk-000 | Chapter 7: Dislodge 逐 Chasing away or dislodging an enemy piece is a type of midgame tactic that is worthy of study. This tactic is used when fighting for the important lines, t... |

### endgames

- query: king opposition zugzwang practical endgame king and pawn technique
- expected_best: endgames
- actual_best: beginner_principles
- pass: False

| Collection | Top distance | Top id | Preview |
|---|---:|---|---|
| openings | 0.514758825302124 | xiangqi.com/all_phases/xiangqi_com_how_to_play#openings#chunk-029 | 4.5 How to Play Chinese Chess Endgame? (Main article: 10 Most Important Xiangqi Endgame Principles ) Solid knowledge for Endgame is indispensable in order to become a strong xia... |
| tactics | 0.5439923709551506 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#tactics#chunk-012 | Trade away the enemy's essential pieces. Utilize the King to join in combat. There was an example of a game by Grandmaster Liu Dahua, who utilized his King very early to provide... |
| endgames | 0.47166228559266443 | xqinenglish/endgame/xqinenglish_endgame_basics_08#endgames#chunk-001 | Practical Endgames In the last century, advances in endgame theory have allowed Xiangqi experts to identify various situations whereby the result can be predicted with certainty... |
| beginner_principles | 0.47166192531585693 | xqinenglish/endgame/xqinenglish_endgame_basics_08#beginner_principles#chunk-001 | Practical Endgames In the last century, advances in endgame theory have allowed Xiangqi experts to identify various situations whereby the result can be predicted with certainty... |

### beginner_principles

- query: develop pieces early protect the king avoid moving the same piece twice beginner fundamentals
- expected_best: beginner_principles
- actual_best: beginner_principles
- pass: True

| Collection | Top distance | Top id | Preview |
|---|---:|---|---|
| openings | 0.49979168176651 | xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-005 | Things to do: - 1. Try to move your major pieces (Chariot, horse, Cannon) to control important positions on the board as early as possible. This is perhaps the most important ru... |
| tactics | 0.49648197601749733 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#tactics#chunk-005 | The Devil is in the Details When the situation and material are even, the deciding factor is usually the position of the pieces. Well-placed pieces with potential for further de... |
| endgames | 0.47858395274435095 | xqinenglish/general/xqinenglish_basic_checkmate_methods#endgames#chunk-003 | Basic Kills are relatively simple with fixed patterns for recognition. Basic Kills in Xiangqi (Chinese Chess) have been broken down into various tactical combinations for study.... |
| beginner_principles | 0.43566287167353546 | xqinenglish/all_phases/xqinenglish_how_to_play_basics_02#beginner_principles#chunk-001 | How to Play Xiangqi Learning how to play a game of Xiangqi would mean to learn how to move the chess pieces on the Xiangqi chessboard to capture the enemy king. There are seven ... |

## Cross-Collection Isolation Tests

### opening concept in tactics

- query: develop pieces early and control the center
- expected_best: openings
- expected_weak: tactics
- actual_best: beginner_principles
- pass: False

| Rank | Collection | Top distance | Top id | Preview |
|---:|---|---:|---|---|
| 1 | beginner_principles | 0.4199340343475342 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#beginner_principles#chunk-005 | The Devil is in the Details When the situation and material are even, the deciding factor is usually the position of the pieces. Well-placed pieces with potential for further de... |
| 2 | tactics | 0.4199342725013695 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#tactics#chunk-005 | The Devil is in the Details When the situation and material are even, the deciding factor is usually the position of the pieces. Well-placed pieces with potential for further de... |
| 3 | endgames | 0.5664449522598483 | xqinenglish/general/xqinenglish_basic_checkmate_methods#endgames#chunk-003 | Basic Kills are relatively simple with fixed patterns for recognition. Basic Kills in Xiangqi (Chinese Chess) have been broken down into various tactical combinations for study.... |
| 4 | openings | 0.5831252932548523 | xiangqi.com/all_phases/xiangqi_com_how_to_play#openings#chunk-010 | 2.2 How to set up the Board? (Main article: How to Start ) The Xiangqi board is a 9 × 10 square consisting of 9 vertical lines intersected by 10 horizontal lines. The vertical l... |

### tactical concept in openings

- query: fork attack with tactical motif
- expected_best: tactics
- expected_weak: openings
- actual_best: beginner_principles
- pass: False

| Rank | Collection | Top distance | Top id | Preview |
|---:|---|---:|---|---|
| 1 | beginner_principles | 0.601891279220581 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#beginner_principles#chunk-014 | Attacking the enemy's weak spots is the best defense! When the enemy is attacking a particular area on the board, and you have the means to launch a counter-attack, it is a good... |
| 2 | tactics | 0.6018913552422295 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#tactics#chunk-014 | Attacking the enemy's weak spots is the best defense! When the enemy is attacking a particular area on the board, and you have the means to launch a counter-attack, it is a good... |
| 3 | openings | 0.6071535348892212 | xiangqi.com/all_phases/xiangqi_com_how_to_play#openings#chunk-019 | 3.3 Capturing tactics Here is a list of Xiangqi Capturing tactics: - Fork Fork - Skewer Skewer - Discovered Attack Discovered Attack - Pin Pin - Trapping Trapping - Elimination ... |
| 4 | endgames | 0.6071536121383003 | xiangqi.com/all_phases/xiangqi_com_how_to_play#endgames#chunk-019 | 3.3 Capturing tactics Here is a list of Xiangqi Capturing tactics: - Fork Fork - Skewer Skewer - Discovered Attack Discovered Attack - Pin Pin - Trapping Trapping - Elimination ... |

### endgame concept in openings

- query: king opposition and zugzwang in practical endgames
- expected_best: endgames
- expected_weak: openings
- actual_best: beginner_principles
- pass: False

| Rank | Collection | Top distance | Top id | Preview |
|---:|---|---:|---|---|
| 1 | beginner_principles | 0.4641299247741699 | xqinenglish/endgame/xqinenglish_endgame_basics_08#beginner_principles#chunk-001 | Practical Endgames In the last century, advances in endgame theory have allowed Xiangqi experts to identify various situations whereby the result can be predicted with certainty... |
| 2 | endgames | 0.46412993053491547 | xqinenglish/endgame/xqinenglish_endgame_basics_08#endgames#chunk-001 | Practical Endgames In the last century, advances in endgame theory have allowed Xiangqi experts to identify various situations whereby the result can be predicted with certainty... |
| 3 | openings | 0.5342913269996643 | xiangqi.com/all_phases/xiangqi_com_how_to_play#openings#chunk-031 | 4.6.1 Theoretical Endgame patterns involving Chariots Endgames involving Chariots means that both players have Chariot(s) in the current phase: - Chariot, Horse, and Advisor wou... |
| 4 | tactics | 0.5342952270078443 | xqinenglish/middlegame/xqinenglish_strategical_advice_middle_game#tactics#chunk-021 | Balanced development of the pieces and a steady improvement of the situation. An example was given in the book of a game. Grandmaster Yu Youhua played the match against Master H... |

### beginner concept in tactics

- query: basic opening fundamentals for beginners
- expected_best: beginner_principles
- expected_weak: tactics
- actual_best: openings
- pass: False

| Rank | Collection | Top distance | Top id | Preview |
|---:|---|---:|---|---|
| 1 | openings | 0.3742832541465759 | xqinenglish/opening/xqinenglish_intro_opening#openings#chunk-011 | Choose a practical and conventional opening. Conventional and orthodox openings have stood the test of time. While unconventional or unorthodox openings may seem flashy and inte... |
| 2 | beginner_principles | 0.3742832541465759 | xqinenglish/opening/xqinenglish_intro_opening#beginner_principles#chunk-011 | Choose a practical and conventional opening. Conventional and orthodox openings have stood the test of time. While unconventional or unorthodox openings may seem flashy and inte... |
| 3 | tactics | 0.5321603794866565 | xqinenglish/middlegame/xqinenglish_intro_midgame#tactics#chunk-000 | Introduction to the Xiangqi (Chinese Chess) Midgame 中局 The midgame is perhaps the hardest stage in the game of Xiangqi. It is also the defining stage of a player's skill. The op... |
| 4 | endgames | 0.5654486291564214 | xiangqi.com/all_phases/xiangqi_com_how_to_play#endgames#chunk-003 | 3. Basic Xiangqi Tactics 3.1 What are the Xiangqi Basic Attack and Defense Tactics? 3.2 Checkmate tactics 3.3 Capturing tactics - 4. Basic Xiangqi Strategies 4.1 How to Play Xia... |

## Duplicate Leakage

- Duplicate groups detected: 157
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-000 Basics of Xiangqi (Chinese Chess) 05 The Opening Phase If we were to dissect the game of Xiangqi or International Che...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-000 Basics of Xiangqi (Chinese Chess) 05 The Opening Phase If we were to dissect the game of Xiangqi or International Che...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-001 First Move Initiative/Advantage By default, Red moves first, which gives Red a slight advantage known as the First Mo...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-001 First Move Initiative/Advantage By default, Red moves first, which gives Red a slight advantage known as the First Mo...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-002 Goals for the Opening System The goal for Red in the opening is to gain traction or momentum in the Opening Phase suc...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-002 Goals for the Opening System The goal for Red in the opening is to gain traction or momentum in the Opening Phase suc...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-003 A short word about formations In the Opening Phase, both colors would choose their attacking and defensive formations...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-003 A short word about formations In the Opening Phase, both colors would choose their attacking and defensive formations...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-004 Fundamental Concepts There are many fundamental concepts in the Xiangqi Opening Phase. The Webmaster has found the in...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-004 Fundamental Concepts There are many fundamental concepts in the Xiangqi Opening Phase. The Webmaster has found the in...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-005 Things to do: - 1. Try to move your major pieces (Chariot, horse, Cannon) to control important positions on the board...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-005 Things to do: - 1. Try to move your major pieces (Chariot, horse, Cannon) to control important positions on the board...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-006 Things NEVER to do: - 1. Never move the same piece too many times. - 2. Never move the Chariot too late in the openin...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-006 Things NEVER to do: - 1. Never move the same piece too many times. - 2. Never move the Chariot too late in the openin...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-007 King: Rest. The King does almost NOTHING in the opening. Unlike International Chess, there is no castling in Xiangqi,...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-007 King: Rest. The King does almost NOTHING in the opening. Unlike International Chess, there is no castling in Xiangqi,...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-008 Advisors: Allow for prophylactic defense and to consolidate defensive formations. Advisors play a defensive role in t...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-008 Advisors: Allow for prophylactic defense and to consolidate defensive formations. Advisors play a defensive role in t...
- Collections: beginner_principles, openings
- occurrence: openings xqinenglish/opening/xqinenglish_opening_basics_05#openings#chunk-009 Elephant: Initially used for defense and consolidation. The Elephant has a similar role as the Advisor and is used pr...
- occurrence: beginner_principles xqinenglish/opening/xqinenglish_opening_basics_05#beginner_principles#chunk-009 Elephant: Initially used for defense and consolidation. The Elephant has a similar role as the Advisor and is used pr...

