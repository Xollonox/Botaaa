# Card Stats Reference

> Bot2 - Lookism HXCC Card Catalog

## Upgrade Stat System

Common and Rare cards now use a 5-level upgrade stat model. Their old balanced `stats` values are preserved as `max_stats`, and current `stats` now starts at `base_stats` because `upgrade_level` is `0`.

- `base_stats`: pulled card stats at +0
- `max_stats`: final card stats at +5
- `stats`: current active battle stats for the current upgrade level
- `upgrade_level`: current upgrade level, clamped from `0` to `5`
- `max_upgrade`: always `5` for Common and Rare cards

```js
function getCurrentStats(baseStats, maxStats, upgradeLevel) {
  const level = Math.max(0, Math.min(5, upgradeLevel));
  const current = {};

  for (const stat of ["strength", "speed", "endurance", "technique", "iq", "battle_iq"]) {
    current[stat] =
      baseStats[stat] + Math.floor((maxStats[stat] - baseStats[stat]) * level / 5);
  }

  return current;
}
```

## Rarity Stat Ranges

| Rarity | Current Handling | Total Range | Notes |
|---|---|---:|---|
| Common | base/max upgrade stats | 0-50 max total | Starts at base_stats, reaches max_stats at +5 |
| Rare | base/max upgrade stats | 100-150 max total | Normal practical cap is 145; only listed peak exceptions exceed it |
| Epic | flat stats for now | 200-250 total | Do not retrofit yet; will be redesigned later |
| Legendary | not present in current catalog | TBD | Future design |
| Mythical | not present in current catalog | TBD | Future design |
| Infernal | not present in current catalog | TBD | Future design |
| Abyssal | not present in current catalog | TBD | Future design |

## Growth Rules

| Rarity | Max Total | Growth |
|---|---:|---:|
| Common | <= 25 | 6 |
| Common | 26-35 | 9 |
| Common | 36-44 | 12 |
| Common | 45-50 | 14 |
| Rare | 100-120 | 10 |
| Rare | 121-132 | 12 |
| Rare | 133-145 | 16 |
| Rare | 146-147 | 18 |

Growth is intentionally character-shaped, not evenly subtracted. Favored growth stats take most of the gap between `base_stats` and `max_stats`.

## Common Cards (38)

| # | Key | Title | Base STR | Base SPD | Base END | Base TEC | Base IQ | Base BIQ | Base Total | Max Total | Growth | Upgrade |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Bakgu Noh | Driver of Gapriyoung Kim | 2 | 0 | 3 | 11 | 8 | 11 | 35 | 49 | 14 | 0/5 |
| 2 | Goo Cousin | Cicada | 0 | 1 | 4 | 0 | 10 | 0 | 15 | 21 | 6 | 0/5 |
| 3 | Juncheol Yang | Bureau Cheif | 2 | 2 | 2 | 2 | 12 | 3 | 23 | 32 | 9 | 0/5 |
| 4 | Jinjang | Workers | 0 | 4 | 1 | 6 | 12 | 12 | 35 | 49 | 14 | 0/5 |
| 5 | Fujii Harushige | Yamazaki Syndicate | 5 | 5 | 5 | 7 | 3 | 6 | 31 | 45 | 14 | 0/5 |
| 6 | Isu Jo | The 1st Affiliate Haggler | 2 | 4 | 3 | 6 | 11 | 6 | 32 | 46 | 14 | 0/5 |
| 7 | Changyong Ji | The Suwon Successor | 7 | 6 | 7 | 7 | 3 | 5 | 35 | 49 | 14 | 0/5 |
| 8 | Chungcheong | Creeper | 8 | 5 | 7 | 6 | 2 | 6 | 34 | 48 | 14 | 0/5 |
| 9 | Alexander Hwang | The Cowardly King | 0 | 0 | 11 | 0 | 10 | 4 | 25 | 37 | 12 | 0/5 |
| 10 | Yakuza Guard | Cheonliang | 6 | 4 | 7 | 5 | 1 | 5 | 28 | 40 | 12 | 0/5 |
| 11 | Kid Seonji | Kind King | 5 | 6 | 6 | 7 | 3 | 7 | 34 | 48 | 14 | 0/5 |
| 12 | Young Samuel | Passionate | 6 | 5 | 8 | 3 | 5 | 7 | 34 | 48 | 14 | 0/5 |
| 13 | Worker | Fodder | 3 | 3 | 4 | 2 | 1 | 2 | 15 | 21 | 6 | 0/5 |
| 14 | Worker2 | Fodder no.2 | 4 | 2 | 5 | 2 | 1 | 2 | 16 | 22 | 6 | 0/5 |
| 15 | Jay Driver | Common | 2 | 5 | 3 | 6 | 7 | 6 | 29 | 41 | 12 | 0/5 |
| 16 | Jose Alvarez | Criminal | 5 | 4 | 6 | 4 | 2 | 5 | 26 | 38 | 12 | 0/5 |
| 17 | Raphael Gracey | Criminal | 3 | 6 | 3 | 6 | 3 | 6 | 27 | 39 | 12 | 0/5 |
| 18 | Pat Toney | Criminal | 7 | 2 | 8 | 2 | 1 | 5 | 25 | 37 | 12 | 0/5 |
| 19 | Li Chao | Criminal | 4 | 4 | 4 | 2 | 6 | 4 | 24 | 33 | 9 | 0/5 |
| 20 | Bully | Fodder | 5 | 3 | 4 | 1 | 1 | 2 | 16 | 22 | 6 | 0/5 |
| 21 | Dosoo Lee | Stone Head Service No.2 | 7 | 4 | 7 | 6 | 1 | 6 | 31 | 45 | 14 | 0/5 |
| 22 | Fodder | Suwon Crew Head | 5 | 4 | 5 | 4 | 3 | 5 | 26 | 38 | 12 | 0/5 |
| 23 | Bayeonggun Heo | Suwon Twins | 6 | 6 | 6 | 6 | 2 | 6 | 32 | 46 | 14 | 0/5 |
| 24 | Byeonggwang Heo | Suwon Twins | 5 | 6 | 5 | 7 | 3 | 6 | 32 | 46 | 14 | 0/5 |
| 25 | Wooseok Choi | Vin's Friend | 4 | 5 | 4 | 5 | 3 | 6 | 27 | 39 | 12 | 0/5 |
| 26 | Hyungjae Lee | Vin's Friend | 4 | 5 | 4 | 4 | 4 | 5 | 26 | 35 | 9 | 0/5 |
| 27 | Jaewoo Park | Vin's Friend | 4 | 5 | 4 | 5 | 3 | 6 | 27 | 39 | 12 | 0/5 |
| 28 | Taebong Lim | Vin's Friend | 6 | 4 | 6 | 4 | 2 | 6 | 28 | 40 | 12 | 0/5 |
| 29 | Shaman Guards | Cheonliang | 6 | 4 | 7 | 6 | 2 | 6 | 31 | 43 | 12 | 0/5 |
| 30 | Changyong ji | Upgraded Suwon Successor | 6 | 6 | 6 | 7 | 3 | 7 | 35 | 49 | 14 | 0/5 |
| 31 | Lineman | First Appearance | 3 | 3 | 9 | 2 | 3 | 6 | 26 | 38 | 12 | 0/5 |
| 32 | Doo Lee | Mother of All Badasses | 1 | 2 | 4 | 1 | 13 | 4 | 25 | 34 | 9 | 0/5 |
| 33 | Guryong High School | High Fodders | 5 | 4 | 5 | 3 | 2 | 5 | 24 | 36 | 12 | 0/5 |
| 34 | Black Bear Gang | High Fodders | 6 | 5 | 6 | 4 | 2 | 6 | 29 | 41 | 12 | 0/5 |
| 35 | Robert Choi | Acting Chief of BB Gang | 6 | 6 | 6 | 5 | 3 | 6 | 32 | 46 | 14 | 0/5 |
| 36 | Gangseo Middle School Head | Middle School Head | 4 | 4 | 5 | 4 | 3 | 5 | 25 | 34 | 9 | 0/5 |
| 37 | Old Face | Big Deal No. 2 | 6 | 5 | 6 | 5 | 4 | 6 | 32 | 44 | 12 | 0/5 |
| 38 | Olly Wang Happy | Middle School Happy | 2 | 2 | 16 | 1 | 2 | 3 | 26 | 38 | 12 | 0/5 |

## Rare Cards (30)

| # | Key | Title | Base STR | Base SPD | Base END | Base TEC | Base IQ | Base BIQ | Base Total | Max Total | Growth | Upgrade |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Vin Jin | Son of Jin Mujin | 27 | 15 | 21 | 26 | 7 | 16 | 112 | 124 | 12 | 0/5 |
| 2 | Jay Hong | Hostel Arc | 16 | 23 | 16 | 30 | 12 | 17 | 114 | 126 | 12 | 0/5 |
| 3 | Taegon Wi | Workers | 15 | 23 | 17 | 22 | 11 | 18 | 106 | 116 | 10 | 0/5 |
| 4 | Hwang Ho | Workers | 23 | 16 | 22 | 19 | 10 | 21 | 111 | 123 | 12 | 0/5 |
| 5 | Brad Lee | Big Deal no.4 | 21 | 15 | 25 | 17 | 9 | 22 | 109 | 121 | 12 | 0/5 |
| 6 | Jason Yoon | Big Deal no.3 | 19 | 25 | 20 | 23 | 10 | 18 | 115 | 127 | 12 | 0/5 |
| 7 | Magami Kenta | Young Master of Magami clan | 17 | 26 | 22 | 29 | 8 | 15 | 117 | 129 | 12 | 0/5 |
| 8 | Jaesu Noh | Workers | 16 | 17 | 19 | 16 | 13 | 22 | 103 | 113 | 10 | 0/5 |
| 9 | Beolgu Lee | Old Pre Gen | 20 | 19 | 23 | 27 | 11 | 18 | 118 | 134 | 16 | 0/5 |
| 10 | Cheonliang Fam | Cheonliang | 20 | 21 | 22 | 19 | 11 | 21 | 114 | 126 | 12 | 0/5 |
| 11 | Gwang Yu | Old Pre Gen | 22 | 19 | 24 | 26 | 10 | 19 | 120 | 136 | 16 | 0/5 |
| 12 | Doksu Heo | King of Pyeongtaek | 25 | 15 | 24 | 17 | 9 | 19 | 109 | 121 | 12 | 0/5 |
| 13 | Jinyong Go | King of Seongnam | 18 | 17 | 21 | 21 | 15 | 17 | 109 | 119 | 10 | 0/5 |
| 14 | Logan Lee | Workers Executive | 27 | 12 | 30 | 14 | 10 | 23 | 116 | 128 | 12 | 0/5 |
| 15 | Jay Hong Holiday Arc | Holiday Arc | 17 | 27 | 19 | 33 | 13 | 12 | 121 | 137 | 16 | 0/5 |
| 16 | Jibeom Kwak | Kwak Brothers | 25 | 16 | 24 | 20 | 9 | 18 | 112 | 124 | 12 | 0/5 |
| 17 | Vin Jin Workers Arc | Workers Arc | 31 | 18 | 26 | 32 | 8 | 11 | 126 | 142 | 16 | 0/5 |
| 18 | Jihan Kwak | Allied (Spy) | 22 | 25 | 21 | 28 | 11 | 13 | 120 | 132 | 12 | 0/5 |
| 19 | Big Samuel | Criminal | 27 | 15 | 28 | 14 | 12 | 21 | 117 | 133 | 16 | 0/5 |
| 20 | Marcus | Criminal | 26 | 14 | 28 | 13 | 8 | 26 | 115 | 127 | 12 | 0/5 |
| 21 | Katsuzawa Akira | Criminal | 21 | 25 | 19 | 26 | 9 | 16 | 116 | 128 | 12 | 0/5 |
| 22 | Magami Kenta 2 | Criminal | 20 | 27 | 23 | 30 | 7 | 13 | 120 | 132 | 12 | 0/5 |
| 23 | Ryuuto Magami | Head of Magami Clan | 21 | 23 | 24 | 31 | 9 | 10 | 118 | 134 | 16 | 0/5 |
| 24 | One Eyed Yamazaki | Yamazaki Syndicate Acting Chief | 23 | 26 | 22 | 30 | 14 | 14 | 129 | 147 | 18 | 0/5 |
| 25 | Sunglasses Yamazaki | Yamazaki Syndicate Acting Chief | 26 | 22 | 27 | 26 | 13 | 14 | 128 | 146 | 18 | 0/5 |
| 26 | Sato Kazuma | Worker's 2A | 22 | 19 | 23 | 16 | 10 | 22 | 112 | 124 | 12 | 0/5 |
| 27 | Vasco Lee | Burn Knuckles Head | 32 | 16 | 31 | 21 | 8 | 20 | 128 | 144 | 16 | 0/5 |
| 28 | Taegon Wi 3A | Workers 3A | 18 | 28 | 19 | 26 | 11 | 16 | 118 | 130 | 12 | 0/5 |
| 29 | Huseong Ha | Son of a Gorilla | 31 | 12 | 32 | 15 | 9 | 22 | 121 | 137 | 16 | 0/5 |
| 30 | Brad Lee Gongwon Hippo | Gongwon Hippo | 20 | 12 | 26 | 14 | 9 | 23 | 104 | 114 | 10 | 0/5 |

## Epic Cards (23)

Epic cards are intentionally unchanged and still use flat `stats` only. They will get base/max stats later during the Epic-to-Abyssal redesign pass.

| # | Key | Title | STR | SPD | END | TEC | IQ | BIQ | Total |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Hudson | Holiday Arc | 42 | 38 | 40 | 37 | 35 | 38 | 230 |
| 2 | Daniel Park | Masterpiece | 43 | 40 | 39 | 38 | 36 | 39 | 235 |
| 3 | Xiaolung | Lover | 41 | 39 | 40 | 38 | 37 | 40 | 235 |
| 4 | Jerry Kwon | Big Deal No.2 | 44 | 39 | 41 | 37 | 35 | 39 | 235 |
| 5 | Sinu Han | Boy of Promise | 42 | 45 | 38 | 39 | 36 | 40 | 240 |
| 6 | Zack Lee | Iron Boxer | 44 | 38 | 43 | 37 | 35 | 38 | 235 |
| 7 | Kuroda Ryuhae | Biker Gang Leader | 43 | 40 | 39 | 38 | 36 | 39 | 235 |
| 8 | Kojima Brothers | Ghost Brothers | 41 | 39 | 40 | 39 | 37 | 39 | 235 |
| 9 | Jaesu Noh 2 | Old Pre Gen | 42 | 40 | 39 | 38 | 37 | 39 | 235 |
| 10 | Gwang Yu 2 | MMA Creator | 43 | 39 | 40 | 39 | 36 | 38 | 235 |
| 11 | Beolgu Lee 2 | Pre Gen | 41 | 40 | 39 | 40 | 36 | 39 | 235 |
| 12 | Sameul Seo | Crazy Mode | 44 | 39 | 38 | 40 | 37 | 37 | 235 |
| 13 | Zack Lee 2 | Imperfect Iron Fortess | 42 | 41 | 42 | 38 | 36 | 38 | 237 |
| 14 | Hudson 2 | Sun of Ansan | 43 | 39 | 40 | 38 | 36 | 39 | 235 |
| 15 | Vasco | Hero | 44 | 38 | 41 | 37 | 36 | 39 | 235 |
| 16 | Daniel Park 2 | Workers Arc | 44 | 40 | 39 | 38 | 37 | 37 | 235 |
| 17 | Taejin Choi | Kalwa | 42 | 39 | 40 | 39 | 37 | 38 | 235 |
| 18 | Warren Chae | Gangdong's Mighty | 43 | 38 | 41 | 38 | 37 | 38 | 235 |
| 19 | Eli Jang | Hostel No.1 | 42 | 39 | 40 | 39 | 37 | 38 | 235 |
| 20 | Jerry Kwon 2 | Workers Arc 1st | 43 | 39 | 40 | 38 | 37 | 38 | 235 |
| 21 | Jake Kim | Big Deal No.1 | 44 | 39 | 40 | 38 | 37 | 37 | 235 |
| 22 | Minsik Choi | Criminal | 43 | 38 | 40 | 39 | 37 | 38 | 235 |
| 23 | Daniel Park 3 | The Affiliate Hunter | 45 | 39 | 40 | 38 | 36 | 37 | 235 |

## Summary

- Total cards: 91
- Common: 38
- Rare: 30
- Epic: 23
- Legendary: 0
- Mythical: 0
- Infernal: 0
- Abyssal: 0
- Common/Rare upgrade fields: `stats`, `base_stats`, `max_stats`, `upgrade_level`, `max_upgrade`
- Current Common/Rare `stats` equals `base_stats` at upgrade level 0
