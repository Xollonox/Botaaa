# 💰 Economy System — Complete Reference

---

## 1. 🪙 Currency Types

| Currency | Variable | Sources | Sinks |
|----------|----------|---------|-------|
| **Coins** | `user["balance"]` | Battle wins, rewards, market sales, quick sell, redeem codes, milestones | Pack purchases, market fees, tournament entry, gang creation, card fusion |
| **Premium Gems** | `user["premium_balance"]` | Season pass, milestones, redeem codes | Season pass unlock (200 gems) |

---

## 2. 💸 Reward System

### Reward Command Config
```python
REWARD_COOLDOWNS = {
    "hourly": 3600,     # 1 hour
    "daily": 86400,     # 24 hours
    "weekly": 604800,   # 7 days
    "monthly": 2592000, # 30 days
}

REWARD_COIN_BONUS = {
    "hourly": 100,
    "daily": 150,
    "weekly": 1_500,
    "monthly": 10_000,
}

REWARD_CARD_RATES = {
    "daily":   {"Common": 100},
    "weekly":  {"Common": 70, "Rare": 30},
    "monthly": {"Rare": 60, "Epic": 35, "Legendary": 5},
}

REWARD_COIN_CHANCE = {
    "daily":   0.5,   # 50% chance of coins vs card
    "weekly":  0.5,
    "monthly": 0.5,
}
```

### Login Streak System
```python
streak_multipliers = {
    3:  1.25,  # 3+ days → 25% bonus
    7:  1.5,   # 7+ days → 50% bonus
    14: 2.0,   # 14+ days → 100% bonus
    30: 3.0,   # 30+ days → 200% bonus
}
```
- Streak resets if a day is missed
- Daily rewards fire a streak check on claim

---

## 3. 📦 Pack Economics

### Pack Pricing & Expected Value
| Pack | Price | Avg Cards | Avg Rarity* | EV (coins) |
|------|-------|-----------|-------------|------------|
| Newbie | 750 | 1 | Common (0.8) + Rare (0.2) | ~350 |
| Amateur | 3,000 | 1 | Common (0.5) + Rare (0.45) + Epic (0.05) | ~1,150 |
| Basic | 5,000 | 1 | Common (0.3) + Rare (0.6) + Epic (0.1) | ~2,100 |
| Intermediate | 10,000 | 1 | Rare (0.4) + Epic (0.5) + Legendary (0.1) | ~5,300 |
| Experienced | 25,000 | 1 | Epic (0.6) + Legendary (0.3) + Mythical (0.1) | ~14,500 |
| Advanced | 40,000 | 1 | Legendary (0.65) + Mythical (0.25) + Infernal (0.1) | ~28,000 |
| Veteran | 50,000 | 1 | Legendary (0.3) + Mythical (0.5) + Infernal (0.2) | ~37,000 |
| VIP | 75,000 | 1 | Mythical (0.5) + Infernal (0.4) + Abyssal (0.1) | ~62,000 |
| Ranker | 90,000 | 1 | Infernal (0.5) + Abyssal (0.5) | ~85,000 |

\*EV = quick_sell_value × probability weighted

### Quick Sell Values
| Rarity | Quick Sell |
|--------|-----------|
| Common | 250 |
| Rare | 1,000 |
| Epic | 5,000 |
| Legendary | 20,000 |
| Mythical | 40,000 |
| Infernal | 60,000 |
| Abyssal | 80,000 |

---

## 4. 📈 Market Economy

### Price Bands (per rarity)
| Rarity | Min Price | Max Price | Market Fee |
|--------|-----------|-----------|------------|
| Common | 500 | 1,000 | 5% |
| Rare | 3,000 | 5,000 | 5% |
| Epic | 10,000 | 20,000 | 5% |
| Legendary | 30,000 | 40,000 | 5% |
| Mythical | 50,000 | 60,000 | 5% |
| Infernal | 70,000 | 80,000 | 5% |
| Abyssal | 90,000 | 100,000 | 5% |

### Seller Payout
```
seller_payout = price - (price * fee_percent / 100)
For a 50,000 coin Legendary: 50,000 - 2,500 = 47,500 coins
```

### Market Constraints
- Max 10 listings per user (configurable)
- Cards must be unlocked (not in squad/market/trade)
- Listings expire after 7 days

---

## 5. ⚔️ Battle Economy

### Coin Rewards
```
Ranked Win:  50-90 coins  (random)
Ranked Loss: 0
CPU Win:     50-90 coins  (random, scaled down if farm detected)
CPU Loss:    0
```

### XP & CP Table
| Outcome | XP | CP |
|---------|----|----|
| Ranked Win | 200 | 50 |
| Ranked Loss | 75 | 20 |
| Friendly Win | 100 | 25 |
| Friendly Loss | 40 | 10 |
| Tournament Win | 250 | 75 |
| Tournament Loss | 100 | 30 |

### Event Multipliers
- Double XP: ×2 XP (configurable duration)
- Double CP: ×1.5 CP (configurable duration)

---

## 6. 🏆 Tournament Prize Split

| Rank | Prize % | 10k Pool | 50k Pool |
|------|---------|----------|----------|
| 1st | 40% | 4,000 | 20,000 |
| 2nd | 20% | 2,000 | 10,000 |
| 3rd | 12% | 1,200 | 6,000 |
| 4th | 8% | 800 | 4,000 |
| 5th | 5% | 500 | 2,500 |
| 6th | 5% | 500 | 2,500 |
| 7th | 2.5% | 250 | 1,250 |
| 8th | 2.5% | 250 | 1,250 |
| 9th | 2.5% | 250 | 1,250 |
| 10th | 2.5% | 250 | 1,250 |

---

## 7. 📊 XP & Level System

### XP Requirements (Exponential)
```python
def xp_for_level(level):
    total = 0
    for lvl in range(2, level + 1):
        total += int(500 * (1.2 ** (lvl - 2)))
    return total

# Key thresholds:
Level 1: 0 XP       Level 10: 12,570 XP
Level 5: 3,105 XP   Level 25: 215,000 XP
Level 50: 2,400,000 XP   Level 100: 315,000,000 XP
```

### Level Milestone Rewards
| Level | Reward |
|-------|--------|
| 5 | 500 coins |
| 10 | 1,000 coins + Amateur Pack |
| 15 | 1,500 coins |
| 20 | 2,000 coins + Basic Pack + 10 gems |
| 25 | 3,000 coins |
| 30 | 4,000 coins + Intermediate Pack |
| 40 | 5,000 coins + 15 gems |
| 50 | 8,000 coins + Experienced Pack + 25 gems |
| 75 | 12,000 coins + Veteran Pack + 50 gems |
| 100 | 20,000 coins + 100 gems (MAX LEVEL) |

---

## 8. 💎 Season Pass Economy

### Pass Cost
- Paid Pass: 200 premium gems

### Tier Rewards (15 tiers)
| Tier | CP | Free Reward | Paid Reward |
|------|----|-------------|-------------|
| 1 | 100 | 500 coins | Newbie Pack |
| 2 | 300 | 1,000 coins | 30 gems |
| 3 | 600 | Amateur Pack | Basic Pack |
| 4 | 1,000 | 1,500 coins | 40 gems |
| 5 | 1,500 | Basic Pack | Intermediate Pack |
| 6 | 2,100 | 2,000 coins | 70 gems |
| 7 | 2,800 | 2,500 coins | Experienced Pack |
| 8 | 3,600 | Intermediate Pack | 40 gems |
| 9 | 4,500 | 3,000 coins | Advanced Pack |
| 10 | 5,500 | Experienced Pack | Veteran Pack |
| 11 | 6,600 | 5,000 coins | 30 gems |
| 12 | 7,800 | Advanced Pack | 2x Experienced Pack |
| 13 | 9,100 | 7,500 coins | 40 gems |
| 14 | 10,500 | Veteran Pack | VIP Pack |
| 15 | 12,000 | 10,000 coins | Ranker Pack |

### Total Rewards if MAX Pass
```
Free track: 35,500 coins + 5 packs
Paid track: 250 gems + 7 packs (includes 250 gem return on investment)
```

---

## 9. 🏰 Gang War Economy

### War Reward Tiers
| Format | Winner Coins | Loser Coins | Winner Packs | Loser Packs |
|--------|-------------|-------------|--------------|-------------|
| 2v2 | 500 | 250 | 3 | 1 |
| 10v10 | 1,000 | 500 | 3 | 1 |
| 20v20 | 3,000 | 1,500 | 3 | 1 |
| 30v30 | 5,000 | 2,500 | 3 | 1 |

### Gang Creation Cost
```
10,000 coins (one-time, non-refundable)
```

---

## 10. 📉 Inflation / Deflation Analysis

### Coin Sources (Inflationary)
| Source | Per Day (active user) |
|--------|----------------------|
| Hourly | 1,200 (12×100, if claimed perfectly) |
| Daily | 150 (or card) |
| Weekly | 1,500 (or card) |
| Monthly | 10,000 (or card) |
| Battles (PvP) | ~500 (10 battles) |
| Battles (CPU) | ~300 (capped by anti-farm) |
| **Total** | **~14,000 coins/day max** |

### Coin Sinks (Deflationary)
| Sink | Cost |
|------|------|
| Newbie Pack | 750 |
| Amateur Pack | 3,000 |
| Basic Pack | 5,000 |
| Intermediate Pack | 10,000 |
| Experienced Pack | 25,000 |
| Card Fusion | 500-20,000 (varies by rarity) |
| Market Fee | 5% per sale |
| Tournament Entry | 2,000 |
| Gang Creation | 10,000 |

### Balance Notes
- Active players can earn ~14,000 coins/day
- Top pack (Ranker) costs 90,000 coins → ~6.4 days of grinding
- Paid season pass costs 200 gems → ~2 weeks of milestone grinding
- Market creates a P2P economy with 5% money sink per trade
- Fusion costs scale exponentially (1.6^stars)
