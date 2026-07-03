# Card Stats Reference

> Bot2 - Lookism HXCC Card Catalog

## Battle Connection

- Battle reads each card from `cards.json` through the catalog in runtime data.
- Active battle stats use `stats` with the connected keys `strength`, `speed`, `endurance`, `technique`, `iq`, and `battle_iq`.
- Move buttons are sourced from `attacks`, `special`, and `ultimate` lists.
- Catalog move definitions live in `moves`; each listed move name must match its reference list.
- Higher-rarity cards use `masteries` and `unique_skills`; runtime compatibility also accepts the older `mastery` and `unique_skill` fields.

## Rarity Stat Ranges

| Rarity | Total Range | Cards |
|---|---:|---:|
| Common | 0-20 | 38 |
| Rare | 70-120 | 35 |
| Epic | 170-220 | 29 |
| Legendary | 290-390 | 13 |
| Mythical | 340-440 | 5 |
| Infernal | 390-490 | 1 |
| Abyssal | 440-540 | 1 |

## Cards By Rarity

### Common (38 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Bakgu Noh | Driver of Gapriyoung Kim | 2 | 1 | 2 | 6 | 4 | 5 | 20 |
| 2 | Goo Cousin | Cicada | 1 | 1 | 2 | 1 | 5 | 0 | 10 |
| 3 | Juncheol Yang | Bureau Cheif | 1 | 1 | 2 | 1 | 6 | 2 | 13 |
| 4 | Jinjang | Workers | 1 | 2 | 1 | 3 | 6 | 6 | 19 |
| 5 | Fujii Harushige | Yamazaki Syndicate | 3 | 3 | 3 | 4 | 2 | 3 | 18 |
| 6 | Isu Jo | The 1st Affiliate Haggler | 2 | 2 | 2 | 3 | 6 | 4 | 19 |
| 7 | Changyong Ji | The Suwon Successor | 4 | 3 | 4 | 4 | 2 | 3 | 20 |
| 8 | Chungcheong | Creeper | 4 | 3 | 4 | 3 | 2 | 3 | 19 |
| 9 | Alexander Hwang | The Cowardly King | 1 | 1 | 6 | 1 | 5 | 2 | 16 |
| 10 | Yakuza Guard | Cheonliang | 3 | 2 | 4 | 3 | 1 | 3 | 16 |
| 11 | Kid Seonji | Kind King | 3 | 4 | 3 | 4 | 2 | 4 | 20 |
| 12 | Young Samuel | Passionate | 3 | 3 | 5 | 2 | 3 | 4 | 20 |
| 13 | Worker | Fodder | 2 | 2 | 2 | 1 | 1 | 1 | 9 |
| 14 | Worker2 | Fodder no.2 | 2 | 1 | 3 | 1 | 1 | 1 | 9 |
| 15 | Jay Driver | Common | 2 | 3 | 2 | 3 | 4 | 3 | 17 |
| 16 | Jose Alvarez | Criminal | 3 | 2 | 3 | 2 | 2 | 3 | 15 |
| 17 | Raphael Gracey | Criminal | 2 | 3 | 2 | 3 | 2 | 3 | 15 |
| 18 | Pat Toney | Criminal | 4 | 2 | 4 | 2 | 1 | 2 | 15 |
| 19 | Li Chao | Criminal | 2 | 2 | 3 | 1 | 4 | 2 | 14 |
| 20 | Bully | Fodder | 2 | 2 | 2 | 1 | 1 | 1 | 9 |
| 21 | Dosoo Lee | Stone Head Service No.2 | 4 | 2 | 4 | 3 | 1 | 4 | 18 |
| 22 | Fodder | Suwon Crew Head | 3 | 2 | 3 | 2 | 2 | 3 | 15 |
| 23 | Bayeonggun Heo | Suwon Twins | 4 | 3 | 3 | 3 | 2 | 4 | 19 |
| 24 | Byeonggwang Heo | Suwon Twins | 3 | 3 | 3 | 4 | 2 | 4 | 19 |
| 25 | Wooseok Choi | Vin's Friend | 2 | 3 | 2 | 3 | 2 | 3 | 15 |
| 26 | Hyungjae Lee | Vin's Friend | 2 | 2 | 2 | 2 | 2 | 3 | 13 |
| 27 | Jaewoo Park | Vin's Friend | 2 | 3 | 2 | 3 | 2 | 3 | 15 |
| 28 | Taebong Lim | Vin's Friend | 3 | 2 | 3 | 2 | 2 | 4 | 16 |
| 29 | Shaman Guards | Cheonliang | 3 | 2 | 4 | 3 | 2 | 3 | 17 |
| 30 | Changyong ji | Upgraded Suwon Successor | 3 | 3 | 3 | 4 | 2 | 4 | 19 |
| 31 | Lineman | First Appearance | 2 | 2 | 5 | 2 | 2 | 3 | 16 |
| 32 | Doo Lee | Mother of All Badasses | 1 | 2 | 2 | 1 | 6 | 2 | 14 |
| 33 | Guryong High School | High Fodders | 3 | 2 | 3 | 2 | 2 | 3 | 15 |
| 34 | Black Bear Gang | High Fodders | 3 | 3 | 3 | 2 | 2 | 4 | 17 |
| 35 | Robert Choi | Acting Chief of BB Gang | 4 | 3 | 3 | 3 | 2 | 4 | 19 |
| 36 | Gangseo Middle School Head | Middle School Head | 2 | 2 | 2 | 2 | 2 | 3 | 13 |
| 37 | Old Face | Big Deal No. 2 | 3 | 3 | 3 | 3 | 2 | 4 | 18 |
| 38 | Olly Wang Happy | Middle School Happy | 2 | 2 | 8 | 1 | 2 | 2 | 17 |

### Rare (35 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Vin Jin | Son of Jin Mujin | 23 | 13 | 18 | 22 | 7 | 14 | 97 |
| 2 | Jay Hong | Hostel Arc | 14 | 20 | 14 | 26 | 11 | 15 | 100 |
| 3 | Taegon Wi | Workers | 13 | 20 | 14 | 19 | 9 | 16 | 91 |
| 4 | Hwang Ho | Workers | 20 | 14 | 19 | 17 | 9 | 18 | 97 |
| 5 | Brad Lee | Big Deal no.4 | 18 | 13 | 21 | 15 | 8 | 19 | 94 |
| 6 | Jason Yoon | Big Deal no.3 | 17 | 21 | 17 | 20 | 9 | 16 | 100 |
| 7 | Magami Kenta | Young Master of Magami clan | 15 | 22 | 19 | 25 | 8 | 14 | 103 |
| 8 | Jaesu Noh | Workers | 14 | 15 | 17 | 13 | 11 | 19 | 89 |
| 9 | Beolgu Lee | Old Pre Gen | 18 | 16 | 20 | 24 | 10 | 16 | 104 |
| 10 | Cheonliang Fam | Cheonliang | 17 | 18 | 19 | 16 | 10 | 18 | 98 |
| 11 | Gwang Yu | Old Pre Gen | 20 | 17 | 21 | 23 | 9 | 17 | 107 |
| 12 | Doksu Heo | King of Pyeongtaek | 21 | 13 | 20 | 15 | 8 | 16 | 93 |
| 13 | Jinyong Go | King of Seongnam | 15 | 14 | 17 | 18 | 13 | 15 | 92 |
| 14 | Logan Lee | Workers Executive | 23 | 10 | 25 | 12 | 9 | 19 | 98 |
| 15 | Jay Hong Holiday Arc | Holiday Arc | 15 | 23 | 16 | 28 | 12 | 11 | 105 |
| 16 | Jibeom Kwak | Kwak Brothers | 21 | 14 | 20 | 17 | 8 | 16 | 96 |
| 17 | Vin Jin Workers Arc | Workers Arc | 27 | 16 | 22 | 28 | 8 | 10 | 111 |
| 18 | Jihan Kwak | Allied (Spy) | 19 | 21 | 18 | 24 | 10 | 12 | 104 |
| 19 | Big Samuel | Criminal | 24 | 14 | 25 | 12 | 11 | 19 | 105 |
| 20 | Marcus | Criminal | 22 | 12 | 24 | 11 | 8 | 22 | 99 |
| 21 | Katsuzawa Akira | Criminal | 18 | 21 | 16 | 22 | 8 | 14 | 99 |
| 22 | Magami Kenta 2 | Criminal | 17 | 23 | 19 | 25 | 7 | 12 | 103 |
| 23 | Ryuuto Magami | Head of Magami Clan | 19 | 20 | 21 | 27 | 9 | 9 | 105 |
| 24 | One Eyed Yamazaki | Yamazaki Syndicate Acting Chief | 21 | 23 | 20 | 26 | 14 | 14 | 118 |
| 25 | Sunglasses Yamazaki | Yamazaki Syndicate Acting Chief | 23 | 20 | 24 | 23 | 13 | 14 | 117 |
| 26 | Sato Kazuma | Worker's 2A | 19 | 16 | 20 | 14 | 9 | 19 | 97 |
| 27 | Vasco Lee | Burn Knuckles Head | 26 | 13 | 25 | 16 | 8 | 16 | 104 |
| 28 | Taegon Wi 3A | Workers 3A | 16 | 24 | 16 | 22 | 10 | 14 | 102 |
| 29 | Huseong Ha | Son of a Gorilla | 27 | 12 | 28 | 13 | 8 | 20 | 108 |
| 30 | Brad Lee Gongwon Hippo | Gongwon Hippo | 17 | 11 | 22 | 12 | 8 | 20 | 90 |
| 31 | Vasco Lee 3A | Workers 3A | 30 | 16 | 29 | 20 | 8 | 16 | 119 |
| 32 | OG Daniel Park 3A | Worker's 3A | 12 | 18 | 13 | 17 | 14 | 14 | 88 |
| 33 | Zack Lee Heat Mode | Heat Mode | 18 | 26 | 24 | 20 | 7 | 15 | 110 |
| 34 | Logan Lee 3A | Goo's Friend | 18 | 10 | 24 | 15 | 11 | 28 | 106 |
| 35 | Channing Choi | Ansan Public No.2 | 22 | 15 | 23 | 16 | 9 | 20 | 105 |

### Epic (29 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Hudson | Holiday Arc | 54 | 20 | 35 | 31 | 22 | 22 | 184 |
| 2 | Daniel Park | Masterpiece | 39 | 43 | 34 | 45 | 22 | 24 | 207 |
| 3 | Xiaolung | Lover | 28 | 31 | 27 | 47 | 17 | 30 | 180 |
| 4 | Jerry Kwon | Big Deal No.2 | 43 | 24 | 43 | 24 | 15 | 39 | 188 |
| 5 | Sinu Han | Boy of Promise | 35 | 50 | 37 | 43 | 16 | 25 | 206 |
| 6 | Zack Lee | Iron Boxer | 36 | 37 | 41 | 35 | 18 | 22 | 189 |
| 7 | Kuroda Ryuhae | Biker Gang Leader | 42 | 35 | 40 | 28 | 23 | 34 | 202 |
| 8 | Kojima Brothers | Ghost Brothers | 40 | 34 | 39 | 39 | 23 | 30 | 205 |
| 9 | Jaesu Noh 2 | Old Pre Gen | 40 | 27 | 38 | 31 | 24 | 32 | 192 |
| 10 | Gwang Yu 2 | MMA Creator | 39 | 30 | 38 | 38 | 23 | 26 | 194 |
| 11 | Beolgu Lee 2 | Pre Gen | 40 | 28 | 37 | 30 | 24 | 32 | 191 |
| 12 | Sameul Seo | Crazy Mode | 41 | 36 | 42 | 35 | 21 | 25 | 200 |
| 13 | Zack Lee 2 | Imperfect Iron Fortess | 38 | 42 | 46 | 47 | 13 | 19 | 205 |
| 14 | Hudson 2 | Sun of Ansan | 52 | 26 | 39 | 36 | 21 | 29 | 203 |
| 15 | Vasco | Hero | 49 | 34 | 45 | 38 | 14 | 24 | 204 |
| 16 | Daniel Park 2 | Workers Arc | 39 | 43 | 34 | 45 | 24 | 26 | 211 |
| 17 | Taejin Choi | Kalwa | 43 | 34 | 41 | 36 | 19 | 30 | 203 |
| 18 | Warren Chae | Gangdong's Mighty | 35 | 37 | 34 | 44 | 19 | 27 | 196 |
| 19 | Eli Jang | Hostel No.1 | 35 | 41 | 34 | 43 | 20 | 26 | 199 |
| 20 | Jerry Kwon 2 | Workers Arc 1st | 45 | 26 | 46 | 25 | 16 | 38 | 196 |
| 21 | Jake Kim | Big Deal No.1 | 40 | 36 | 38 | 37 | 22 | 28 | 201 |
| 22 | Minsik Choi | Criminal | 39 | 23 | 38 | 21 | 13 | 38 | 172 |
| 23 | Daniel Park 3 | The Affiliate Hunter | 30 | 33 | 39 | 46 | 17 | 21 | 186 |
| 24 | Vin Jin Workers 2A | Workers 2A | 39 | 30 | 34 | 33 | 17 | 24 | 177 |
| 25 | Shiba Inu Workers 2A | Workers 2A | 39 | 37 | 38 | 39 | 18 | 20 | 191 |
| 26 | Samuel Seo Workers 2A | Workers 2A | 39 | 31 | 41 | 31 | 20 | 24 | 186 |
| 27 | Ryuhei Kuroda Workers 2A | Workers 2A | 40 | 31 | 37 | 29 | 22 | 28 | 187 |
| 28 | Warren Chae Workers 2A | Workers 2A | 32 | 34 | 31 | 42 | 18 | 22 | 179 |
| 29 | Jake Kim Workers 2A | Workers 2A | 38 | 35 | 36 | 36 | 20 | 24 | 189 |

### Legendary (13 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total | Masteries | Unique Skills |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Yamazaki Gun Cheonliang Arc | Cheonliang Arc | 72 | 60 | 67 | 66 | 45 | 57 | 367 | Strength Mastery | Yamazaki Karate, Power Threshold, Oni Pressure |
| 2 | James Lee 2T Cheonliang Arc | Cheonliang Arc | 56 | 81 | 55 | 80 | 42 | 50 | 364 | Speed Mastery, Technique Mastery | Speed Threshold, Technique Threshold, Blindspot Pressure |
| 3 | Jichang Kwak Holiday Arc | Holiday Arc | 73 | 73 | 59 | 60 | 44 | 47 | 356 | Strength Mastery, Speed Mastery | Hand-Blade Style, King's Analysis, Dual Threshold |
| 4 | UI OG Daniel Holiday Arc | Holiday Arc | 66 | 76 | 69 | 78 | 9 | 70 | 368 | - | Ultra Instinct, Copy Response, Automatic Combat |
| 5 | Charles Choi Holiday Arc | Holiday Arc | 68 | 60 | 58 | 69 | 49 | 53 | 357 | Strength Mastery, Speed Mastery, Endurance Mastery, Technique Mastery | Four Masteries, One-Handed Control, Elite Combat Reading |
| 6 | Goo Kim Cheonliang Arc | Cheonliang Arc | 68 | 69 | 61 | 82 | 41 | 48 | 369 | - | Weapon Handling, Improvised Blade, Unpredictable Rhythm |
| 7 | Seongji Yuk 2T | King of Cheonliang | 75 | 51 | 74 | 61 | 46 | 55 | 362 | Strength Mastery, Endurance Mastery | Cheonliang Grip, Power Threshold, Endurance Threshold |
| 8 | The Thing Workers 1A | Workers 1A No.1 | 84 | 50 | 84 | 42 | 8 | 70 | 338 | Strength Mastery, Endurance Mastery | Brute Force, Iron Body, Relentless Pressure |
| 9 | Johan Seong Workers 1A | Workers 1A | 58 | 69 | 52 | 79 | 30 | 47 | 335 | - | Copy, Accelerated Imitation, Blindspot Adaptation |
| 10 | Seokdu Wang | King of Suwon | 79 | 43 | 74 | 50 | 17 | 62 | 325 | Strength Mastery | Suwon Headbutt, King's Pressure, Heavy Frame |
| 11 | Taesoo Ma | King of Ansan | 87 | 45 | 68 | 46 | 22 | 62 | 330 | Strength Mastery | Ansan Fist, Power Threshold, Single-Fist Resolve |
| 12 | Jinyoung Park Medicine Genius | Medicine Genius | 69 | 73 | 67 | 80 | 50 | 47 | 386 | Strength Mastery, Speed Mastery, Endurance Mastery, Technique Mastery | Medical Precision, Four Masteries, Copy Analysis |
| 13 | Goo Kim 1st Moonlight Technique | 1st Moonlight Technique | 67 | 74 | 58 | 94 | 38 | 57 | 388 | - | Moonlight Technique, Blade Control, Weapon Genius |

### Mythical (5 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total | Masteries | Unique Skills |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Gun Park Shiro Oni | Shiro Oni | 95 | 66 | 92 | 74 | 48 | 65 | 440 | Strength Mastery, Endurance Mastery | Shiro Oni, Yamazaki Combat, Iron Pressure |
| 2 | Tom Lee Beggar King | Beggar King | 88 | 68 | 84 | 79 | 48 | 64 | 431 | Strength Mastery, Speed Mastery, Endurance Mastery, Technique Mastery | Fighting Genius, Wild Intercept, Four Masteries |
| 3 | James Lee 3T Cheonliang Arc | Cheonliang Arc | 70 | 93 | 63 | 92 | 49 | 60 | 427 | Speed Mastery, Endurance Mastery, Technique Mastery | Three Thresholds, Invisible Strike, Perfect Footwork |
| 4 | Seongji Yuk 3T | King of Cheonliang | 89 | 66 | 90 | 72 | 48 | 60 | 425 | Strength Mastery, Speed Mastery, Endurance Mastery | Three Thresholds, Mujin Ssireum, Cheonliang King's Grip |
| 5 | Manager Kim White Tiger No.2 | White Tiger No.2 | 76 | 82 | 72 | 89 | 51 | 60 | 430 | Strength Mastery, Speed Mastery, Endurance Mastery, Technique Mastery | CQC Mastery, Military Precision, Four Masteries |

### Infernal (1 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total | Masteries | Unique Skills |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Kitae Kim Silhouette | Silhouette | 98 | 77 | 96 | 82 | 61 | 73 | 487 | Strength Mastery, Endurance Mastery | Brutal Bloodline, Overwhelming Frame, Predatory Pressure |

### Abyssal (1 cards)

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total | Masteries | Unique Skills |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Diego Kang Idol of PTJ Company | Idol of PTJ Company | 94 | 100 | 82 | 100 | 76 | 86 | 538 | Strength Mastery, Speed Mastery, Technique Mastery | Invisible Strike, Perfect Footwork, Peak Technique |

## Summary

- Total cards: 122
- Common: 38
- Rare: 35
- Epic: 29
- Legendary: 13
- Mythical: 5
- Infernal: 1
- Abyssal: 1
