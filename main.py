import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import os
import asyncio
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta

# ===================== MongoDB (Secured via Environment Variables) =====================
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["blackjack_db"]
balances_col = db["user_balances"]

def get_user_data(user_id):
    user_data = balances_col.find_one({"user_id": user_id})
    if not user_data:
        default_data = {
            "user_id": user_id,
            "balance": 1000,
            "wins": 0,
            "losses": 0,
            "last_daily": None,
            "loan_owed": 0
        }
        balances_col.insert_one(default_data)
        return default_data

    updated = False
    for field, default in [("wins", 0), ("losses", 0), ("last_daily", None), ("loan_owed", 0)]:
        if field not in user_data:
            user_data[field] = default
            updated = True

    if updated:
        balances_col.update_one({"user_id": user_id}, {"$set": user_data})

    return user_data

def get_balance(user_id):
    return get_user_data(user_id)["balance"]

def update_balance(user_id, amount):
    current_data = get_user_data(user_id)
    new_bal = max(0, current_data["balance"] + amount)
    balances_col.update_one({"user_id": user_id}, {"$set": {"balance": new_bal}}, upsert=True)
    return new_bal

def increment_stats(user_id, stat_type):
    get_user_data(user_id)
    balances_col.update_one({"user_id": user_id}, {"$inc": {stat_type: 1}})

# ===================== CASINO CONFIGURATION =====================
SHOP_ITEMS = {
    "item_1": {"name": "Gambler 🎲", "price": 5000, "color": discord.Color.blue(), "desc": "Starter casino badge for active players."},
    "item_2": {"name": "High Roller 💰", "price": 25000, "color": discord.Color.green(), "desc": "Premium badge for deep-pocket wagerers."},
    "item_3": {"name": "Casino VIP ✨", "price": 100000, "color": discord.Color.gold(), "desc": "Elite entitlement for exclusive lounge access."},
    "item_4": {"name": "Card Shark 🦈", "price": 250000, "color": discord.Color.teal(), "desc": "Master title for blackjack table veterans."},
    "item_5": {"name": "Millionaire 👑", "price": 1000000, "color": discord.Color.purple(), "desc": "Prestigious tier for server economic elites."},
    "item_6": {"name": "The Casino Boss 🏰", "price": 5000000, "color": discord.Color.dark_red(), "desc": "The ultimate luxury crown of system ownership."}
}

LOAN_LIMITS = [
    {"role": "The Casino Boss 🏰", "max_loan": 10000000, "interest": 0.03},
    {"role": "Millionaire 👑",     "max_loan": 2000000,  "interest": 0.05},
    {"role": "Card Shark 🦈",      "max_loan": 500000,   "interest": 0.06},
    {"role": "Casino VIP ✨",      "max_loan": 200000,   "interest": 0.08},
    {"role": "High Roller 💰",     "max_loan": 50000,    "interest": 0.10},
    {"role": "Gambler 🎲",         "max_loan": 10000,    "interest": 0.12},
]
DEFAULT_LOAN_LIMIT = 2000
DEFAULT_INTEREST   = 0.15

def get_user_loan_tier(member):
    user_roles = [role.name for role in member.roles]
    for tier in LOAN_LIMITS:
        if tier["role"] in user_roles:
            return tier["max_loan"], tier["interest"], tier["role"]
    return DEFAULT_LOAN_LIMIT, DEFAULT_INTEREST, "Default Player"

# ── Media assets ──────────────────────────────────────────────────────────────
IMG_COIN_FLIP    = "https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExNXN6MHZwd3RndXU3M3F6MndvM3BtYm92ZXpxdTlia3RhcG01N3N4dyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7bu3XilJ5XRE9NNm/giphy.gif"
IMG_SLOTS        = "https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExbWZvYno1NTR3Y3VvYno4ZzFmbmFpZ2R5NDhkd3E3N3V5Y3F5b3pwMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/VdbyGEvY4Qe64/giphy.gif"
IMG_ROULETTE     = "https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExbWZid3p5dWh6cnVpaXAwZXAwODZpYnV6dWt6M2RiaWpld2p2MnkyMiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/26uf8rcYmRtoUo8Y8/giphy.gif"
IMG_HORSE_RACING = "https://i.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHYwZWNvMGwzdzNreHlqMHBmYml4Zmt6ZmxtYzR0cmJwbjN5czc4ayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/13Zt9nscX96I6s/giphy.gif"
IMG_HEADS_RESULT = "https://i.postimg.cc/D0Yg0Xg7/heads.png"
IMG_TAILS_RESULT = "https://i.postimg.cc/0jXmH8Xy/tails.png"

# ── Divider helper ────────────────────────────────────────────────────────────
DIVIDER = "─" * 32   # used inside embed descriptions as a visual separator

# ===================== SLOTS =====================
SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
SLOT_PAYOUTS = {
    ("💎", "💎", "💎"): 20,
    ("7️⃣", "7️⃣", "7️⃣"): 15,
    ("⭐", "⭐", "⭐"): 10,
    ("🍇", "🍇", "🍇"): 8,
    ("🍊", "🍊", "🍊"): 6,
    ("🍋", "🍋", "🍋"): 4,
    ("🍒", "🍒", "🍒"): 3,
}

def spin_slots():
    weights = [20, 18, 16, 14, 12, 8, 5]
    return random.choices(SLOT_SYMBOLS, weights=weights, k=3)

def get_slot_payout(reels, bet):
    combo = tuple(reels)
    if combo in SLOT_PAYOUTS:
        return SLOT_PAYOUTS[combo] * bet, f"**Triple {combo[0]}**"
    if reels.count("🍒") == 2:
        return bet * 2, "Double Cherry 🍒🍒"
    return 0, "No Match"

# ── Luxury colour palette ─────────────────────────────────────────────────────
CLR_GOLD    = 0xD4A843   # main accent
CLR_WIN     = 0x2ECC71   # emerald green
CLR_LOSS    = 0xC0392B   # deep red
CLR_NEUTRAL = 0xF1C40F   # yellow / push
CLR_DARK    = 0x1A1F2E   # dark navy (embed sidebar)

# ── Embed footer helper ───────────────────────────────────────────────────────
def luxury_footer(bet: int, balance: int) -> str:
    return f"Wager  ·  ${bet:,}   │   Balance  ·  ${balance:,}"


# ===================== SHOP =====================
CONFIRMATION_PRICE_THRESHOLD = 50_000

async def execute_shop_purchase(interaction: discord.Interaction, user, guild, item_id: str):
    item = SHOP_ITEMS[item_id]
    role = discord.utils.get(guild.roles, name=item["name"])
    if not role:
        try:
            role = await guild.create_role(name=item["name"], color=item["color"],
                                           reason="Auto-created via Casino Shop")
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing `Manage Roles` permission.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Role creation error: {e}", ephemeral=True)
            return

    if role in user.roles:
        await interaction.followup.send(f"⚠️ You already own **{item['name']}**!", ephemeral=True)
        return

    try:
        await user.add_roles(role)
    except discord.Forbidden:
        await interaction.followup.send("❌ Role is above the bot's hierarchy tier.", ephemeral=True)
        return

    update_balance(user.id, -item["price"])
    new_bal = get_balance(user.id)

    embed = discord.Embed(title="🛍️  Purchase Complete", color=CLR_GOLD)
    embed.description = (
        f"**{item['name']}** has been added to your profile, {user.mention}.\n"
        f"{DIVIDER}"
    )
    embed.add_field(name="Charged",  value=f"`-${item['price']:,}`", inline=True)
    embed.add_field(name="Balance",  value=f"`${new_bal:,}`",         inline=True)
    embed.set_footer(text="Casino Shop  ·  Vanity Role Unlocked ✨")
    await interaction.followup.send(embed=embed)


class ShopConfirmView(discord.ui.View):
    def __init__(self, buyer_id: int, item_id: str):
        super().__init__(timeout=30)
        self.buyer_id = buyer_id
        self.item_id  = item_id
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.buyer_id:
            await interaction.response.send_message("❌ This confirmation is not yours.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="✅  Confirm Purchase", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            await interaction.response.send_message("⚠️ Already used.", ephemeral=True)
            return
        self.resolved = True
        self.stop()
        await interaction.response.defer(ephemeral=True)
        await execute_shop_purchase(interaction, interaction.user, interaction.guild, self.item_id)

    @discord.ui.button(label="❌  Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.resolved = True
        self.stop()
        item = SHOP_ITEMS[self.item_id]
        embed = discord.Embed(title="🚫  Transaction Cancelled", color=CLR_LOSS)
        embed.description = f"Purchase of **{item['name']}** was cancelled. Your funds are safe."
        embed.set_footer(text="Re-open the shop any time with /shop")
        await interaction.response.edit_message(embed=embed, view=None)


class ShopDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=info["name"],
                value=item_id,
                description=f"${info['price']:,}  ·  {info['desc']}"
            )
            for item_id, info in SHOP_ITEMS.items()
        ]
        super().__init__(placeholder="Select a role to purchase…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user      = interaction.user
        guild     = interaction.guild
        user_data = get_user_data(user.id)
        debt_role = discord.utils.get(guild.roles, name="Debtor 🔴")

        if user_data.get("loan_owed", 0) > 0 or (debt_role and debt_role in user.roles):
            await interaction.followup.send(
                f"❌ **Shop Locked** — you have an active loan of **${user_data.get('loan_owed', 0):,}**.\n"
                f"Settle it with `/pay_loan` first.", ephemeral=True)
            return

        item_id     = self.values[0]
        item        = SHOP_ITEMS[item_id]
        current_bal = get_balance(user.id)

        if current_bal < item["price"]:
            await interaction.followup.send(
                f"❌ **Insufficient Funds** — need `${item['price']:,}` · have `${current_bal:,}`.",
                ephemeral=True)
            return

        existing = discord.utils.get(guild.roles, name=item["name"])
        if existing and existing in user.roles:
            await interaction.followup.send(f"⚠️ You already own **{item['name']}**!", ephemeral=True)
            return

        if item["price"] >= CONFIRMATION_PRICE_THRESHOLD:
            balance_after = current_bal - item["price"]
            embed = discord.Embed(title="🏦  High-Value Transaction", color=CLR_NEUTRAL)
            embed.description = (
                f"Please review before confirming.\n"
                f"{DIVIDER}"
            )
            embed.add_field(name="Item",           value=f"**{item['name']}**",       inline=True)
            embed.add_field(name="Cost",           value=f"`${item['price']:,}`",      inline=True)
            embed.add_field(name="Current Balance",value=f"`${current_bal:,}`",        inline=True)
            embed.add_field(name="After Purchase", value=f"`${balance_after:,}`",      inline=True)
            embed.add_field(name="Description",    value=f"*{item['desc']}*",          inline=False)
            embed.set_footer(text="⏳ Expires in 30 seconds")
            view = ShopConfirmView(buyer_id=user.id, item_id=item_id)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        await execute_shop_purchase(interaction, user, guild, item_id)


class ShopDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShopDropdown())


# ===================== BLACKJACK =====================
# Card suit map for coloured rendering in descriptions
SUIT_HEARTS   = "♥"
SUIT_DIAMONDS = "♦"
SUIT_CLUBS    = "♣"
SUIT_SPADES   = "♠"
RED_SUITS     = {SUIT_HEARTS, SUIT_DIAMONDS}

def card_display(card: str) -> str:
    """Returns a card string like  K♥  or  10♠ ."""
    for rank in sorted(["10", "J", "Q", "K", "A", "2","3","4","5","6","7","8","9"], key=len, reverse=True):
        if card.startswith(rank):
            suit = card[len(rank):]
            return f"`{rank}{suit}`"
    return f"`{card}`"

def hand_display(hand: list) -> str:
    return "  ".join(card_display(c) for c in hand)


class BlackjackView(discord.ui.View):
    def __init__(self, player_id, deck, player_hand, dealer_hand, bet):
        super().__init__(timeout=60)
        self.player_id   = player_id
        self.deck        = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.bet         = bet

    def calculate_score(self, hand):
        score, aces = 0, 0
        card_values = {
            '2':2,'3':3,'4':4,'5':5,'6':6,'7':7,
            '8':8,'9':9,'10':10,'J':10,'Q':10,'K':10,'A':11
        }
        ranks = list(card_values.keys())
        for card in hand:
            for rank in sorted(ranks, key=len, reverse=True):
                if card.startswith(rank):
                    score += card_values[rank]
                    if rank == 'A':
                        aces += 1
                    break
        while score > 21 and aces:
            score -= 10
            aces  -= 1
        return score

    def _build_game_embed(self, player_score: int, hide_dealer: bool = True, title: str = "🃏  Blackjack", color=None) -> discord.Embed:
        color = color or CLR_DARK
        embed = discord.Embed(title=title, color=color)
        dealer_str = f"{card_display(self.dealer_hand[0])}  `??`" if hide_dealer else hand_display(self.dealer_hand)
        dealer_score_str = "?" if hide_dealer else str(self.calculate_score(self.dealer_hand))

        embed.add_field(
            name="🎩  Dealer",
            value=f"{dealer_str}\n`Score: {dealer_score_str}`",
            inline=True
        )
        embed.add_field(
            name="🙋  Your Hand",
            value=f"{hand_display(self.player_hand)}\n`Score: {player_score}`",
            inline=True
        )
        embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ This table is not yours!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    # ── HIT ──────────────────────────────────────────────────────────────────
    @discord.ui.button(label="Hit  🃏", style=discord.ButtonStyle.blurple)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.player_hand.append(self.deck.pop())
            player_score = self.calculate_score(self.player_hand)

            if player_score > 21:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                embed = discord.Embed(title="💥  Busted!", color=CLR_LOSS)
                embed.description = (
                    f"You drew too high and went over 21.\n"
                    f"{DIVIDER}"
                )
                embed.add_field(name="Your Hand",  value=f"{hand_display(self.player_hand)}\n`Score: {player_score}`", inline=True)
                embed.add_field(name="Dealer Hand",value=f"{card_display(self.dealer_hand[0])}  `??`",                 inline=True)
                embed.add_field(name="Result",     value=f"**-${self.bet:,}**  lost",                                   inline=False)
                embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
                self.stop()
                await interaction.response.edit_message(embed=embed, view=None)
            else:
                embed = self._build_game_embed(player_score)
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred.", ephemeral=True)

    # ── DOUBLE DOWN ───────────────────────────────────────────────────────────
    @discord.ui.button(label="Double  💰", style=discord.ButtonStyle.secondary)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if get_balance(self.player_id) < self.bet:
                await interaction.response.send_message("❌ Not enough balance to double down.", ephemeral=True)
                return
            self.stop()
            self.bet *= 2
            self.player_hand.append(self.deck.pop())
            player_score = self.calculate_score(self.player_hand)

            if player_score > 21:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                embed = discord.Embed(title="💥  Double Bust!", color=CLR_LOSS)
                embed.description = f"Doubled down and busted.\n{DIVIDER}"
                embed.add_field(name="Your Hand",  value=f"{hand_display(self.player_hand)}\n`Score: {player_score}`", inline=True)
                embed.add_field(name="Dealer Hand",value=hand_display(self.dealer_hand),                                inline=True)
                embed.add_field(name="Result",     value=f"**-${self.bet:,}**  lost",                                   inline=False)
                embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
                await interaction.response.edit_message(embed=embed, view=None)
                return

            dealer_score = self.calculate_score(self.dealer_hand)
            while dealer_score < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_score = self.calculate_score(self.dealer_hand)

            title, color, delta = self._resolve(player_score, dealer_score)
            embed = discord.Embed(title=f"🃏  Double Down  ·  {title}", color=color)
            embed.description = DIVIDER
            embed.add_field(name="Your Hand",  value=f"{hand_display(self.player_hand)}\n`Score: {player_score}`",  inline=True)
            embed.add_field(name="Dealer Hand",value=f"{hand_display(self.dealer_hand)}\n`Score: {dealer_score}`", inline=True)
            embed.add_field(name="Result",     value=delta,                                                          inline=False)
            embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred.", ephemeral=True)

    # ── STAND ─────────────────────────────────────────────────────────────────
    @discord.ui.button(label="Stand  🛑", style=discord.ButtonStyle.green)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.stop()
            player_score = self.calculate_score(self.player_hand)
            dealer_score = self.calculate_score(self.dealer_hand)
            while dealer_score < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_score = self.calculate_score(self.dealer_hand)

            title, color, delta = self._resolve(player_score, dealer_score)
            embed = discord.Embed(title=f"🃏  Blackjack  ·  {title}", color=color)
            embed.description = DIVIDER
            embed.add_field(name="Your Hand",  value=f"{hand_display(self.player_hand)}\n`Score: {player_score}`",  inline=True)
            embed.add_field(name="Dealer Hand",value=f"{hand_display(self.dealer_hand)}\n`Score: {dealer_score}`", inline=True)
            embed.add_field(name="Result",     value=delta,                                                          inline=False)
            embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred.", ephemeral=True)

    def _resolve(self, player_score: int, dealer_score: int):
        if dealer_score > 21 or player_score > dealer_score:
            update_balance(self.player_id, self.bet)
            increment_stats(self.player_id, "wins")
            return "Victory! 🎉", CLR_WIN, f"**+${self.bet:,}**  won"
        elif player_score < dealer_score:
            update_balance(self.player_id, -self.bet)
            increment_stats(self.player_id, "losses")
            return "Dealer Wins ❌", CLR_LOSS, f"**-${self.bet:,}**  lost"
        else:
            return "Push 🤝", CLR_NEUTRAL, "Bet returned — no change"


# ===================== COIN FLIP =====================
class CoinFlipView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=45)
        self.player_id = player_id
        self.bet       = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Start your own flip session!", ephemeral=True)
            return False
        return True

    async def process_flip(self, interaction: discord.Interaction, choice: str):
        if self.bet > get_balance(self.player_id):
            msg = "❌ Balance too low for this bet."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        result  = random.choice(["heads", "tails"])
        won     = (choice == result)
        res_img = IMG_HEADS_RESULT if result == "heads" else IMG_TAILS_RESULT

        if won:
            update_balance(self.player_id, self.bet)
            increment_stats(self.player_id, "wins")
            title, color = "🎉  Correct Prediction!", CLR_WIN
            delta = f"**+${self.bet:,}**"
        else:
            update_balance(self.player_id, -self.bet)
            increment_stats(self.player_id, "losses")
            title, color = "💥  Wrong Prediction", CLR_LOSS
            delta = f"**-${self.bet:,}**"

        coin_icon = "🦅" if result == "heads" else "🪙"
        embed = discord.Embed(title=title, color=color)
        embed.description = DIVIDER
        embed.add_field(name="Your Call",    value=f"{choice.capitalize()}", inline=True)
        embed.add_field(name="Flip Outcome", value=f"{coin_icon} {result.capitalize()}", inline=True)
        embed.add_field(name="Result",       value=delta, inline=False)
        embed.set_image(url=res_img)
        embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))

        replay = CoinFlipReplayView(self.player_id, self.bet, choice)
        if interaction.response.is_done():
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=replay)
        else:
            await interaction.response.edit_message(embed=embed, view=replay)


class CoinFlipReplayView(discord.ui.View):
    def __init__(self, player_id, bet, choice):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.bet       = bet
        self.choice    = choice

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Start your own session!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Flip Again  🔄", style=discord.ButtonStyle.green)
    async def flip_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        handler = CoinFlipView(self.player_id, self.bet)
        await handler.process_flip(interaction, self.choice)


# ===================== SLOTS =====================
class SlotsReplayView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.bet       = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Launch your own session!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Spin Again  🎰", style=discord.ButtonStyle.blurple)
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.bet > get_balance(self.player_id):
            await interaction.response.send_message("❌ Insufficient funds to spin.", ephemeral=True)
            return
        await interaction.response.defer()
        update_balance(self.player_id, -self.bet)
        reels = spin_slots()
        payout, combo_name = get_slot_payout(reels, self.bet)
        await _send_slots_result(interaction, self.player_id, self.bet, reels, payout, combo_name, followup_edit=True, message_id=interaction.message.id)


async def _send_slots_result(interaction, player_id, bet, reels, payout, combo_name, followup_edit=False, message_id=None):
    reels_display = f"❮  {'  ·  '.join(reels)}  ❯"
    if payout > 0:
        update_balance(player_id, payout)
        increment_stats(player_id, "wins")
        embed = discord.Embed(title="🎰  Jackpot!", color=CLR_WIN)
        embed.add_field(name="Payout", value=f"**+${payout:,}**", inline=True)
    else:
        increment_stats(player_id, "losses")
        embed = discord.Embed(title="🎰  No Match", color=CLR_LOSS)
        embed.add_field(name="Lost",   value=f"**-${bet:,}**",    inline=True)

    embed.description = f"```{reels_display}```"
    embed.add_field(name="Combination", value=combo_name,                    inline=True)
    embed.add_field(name="Balance",     value=f"`${get_balance(player_id):,}`", inline=False)
    embed.set_image(url=IMG_SLOTS)
    embed.set_footer(text=luxury_footer(bet, get_balance(player_id)))

    view = SlotsReplayView(player_id, bet)
    if followup_edit and message_id:
        await interaction.followup.edit_message(message_id=message_id, embed=embed, view=view)
    elif followup_edit:
        await interaction.followup.send(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed, view=view)


# ===================== ROULETTE =====================
ROULETTE_NUMBERS = list(range(0, 37))
RED_NUMBERS      = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMBERS    = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

class RouletteView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=45)
        self.player_id = player_id
        self.bet       = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Find your own table!", ephemeral=True)
            return False
        return True

    async def resolve(self, interaction, bet_type, display_name):
        self.stop()
        result      = random.choice(ROULETTE_NUMBERS)
        color_emoji = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        won, payout = False, 0

        checks = {
            "red":   lambda r: r in RED_NUMBERS,
            "black": lambda r: r in BLACK_NUMBERS,
            "even":  lambda r: r != 0 and r % 2 == 0,
            "odd":   lambda r: r % 2 == 1,
            "low":   lambda r: 1 <= r <= 18,
            "high":  lambda r: 19 <= r <= 36,
        }
        if checks[bet_type](result):
            won    = True
            payout = self.bet

        if won:
            update_balance(self.player_id, payout)
            increment_stats(self.player_id, "wins")
            embed = discord.Embed(title="🎡  Roulette  ·  Winner!", color=CLR_WIN)
        else:
            update_balance(self.player_id, -self.bet)
            increment_stats(self.player_id, "losses")
            embed = discord.Embed(title="🎡  Roulette  ·  House Wins", color=CLR_LOSS)

        embed.description = DIVIDER
        embed.add_field(name="Result",  value=f"{color_emoji} **{result}**",                  inline=True)
        embed.add_field(name="Your Bet",value=display_name,                                    inline=True)
        embed.add_field(name="Payout",  value=f"**{'+'if won else '-'}${payout if won else self.bet:,}**", inline=True)
        embed.add_field(name="Balance", value=f"`${get_balance(self.player_id):,}`",           inline=False)
        embed.set_image(url=IMG_ROULETTE)
        embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="🔴 Red  ×2",   style=discord.ButtonStyle.danger)
    async def bet_red(self,   i, b): await self.resolve(i, "red",   "🔴 Red")
    @discord.ui.button(label="⚫ Black  ×2", style=discord.ButtonStyle.secondary)
    async def bet_black(self, i, b): await self.resolve(i, "black", "⚫ Black")
    @discord.ui.button(label="Even  ×2",     style=discord.ButtonStyle.blurple)
    async def bet_even(self,  i, b): await self.resolve(i, "even",  "Even")
    @discord.ui.button(label="Odd  ×2",      style=discord.ButtonStyle.blurple)
    async def bet_odd(self,   i, b): await self.resolve(i, "odd",   "Odd")
    @discord.ui.button(label="1–18  ×2",     style=discord.ButtonStyle.green)
    async def bet_low(self,   i, b): await self.resolve(i, "low",   "1–18 Low")
    @discord.ui.button(label="19–36  ×2",    style=discord.ButtonStyle.green)
    async def bet_high(self,  i, b): await self.resolve(i, "high",  "19–36 High")


# ===================== HORSE RACING =====================
HORSES = [
    {"name": "Lightning ⚡", "odds": 2.0},
    {"name": "Blizzard 💨",  "odds": 2.5},
    {"name": "Falcon 🦅",    "odds": 3.0},
    {"name": "Phantom 😈",   "odds": 4.0},
    {"name": "Clover 🍀",    "odds": 5.0},
]

class HorseRacingView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=45)
        self.player_id = player_id
        self.bet       = bet
        for i, horse in enumerate(HORSES):
            btn = discord.ui.Button(
                label=f"{horse['name']}  ×{horse['odds']}",
                style=discord.ButtonStyle.blurple,
                custom_id=f"horse_{i}"
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, horse_index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.player_id:
                await interaction.response.send_message("❌ Find your own betting slip!", ephemeral=True)
                return
            self.stop()
            if self.bet > get_balance(self.player_id):
                await interaction.response.send_message("❌ Insufficient funds.", ephemeral=True)
                return

            chosen  = HORSES[horse_index]
            weights = [1 / h["odds"] for h in HORSES]
            winner_idx   = random.choices(range(len(HORSES)), weights=weights, k=1)[0]
            winner_horse = HORSES[winner_idx]

            others  = [h for i, h in enumerate(HORSES) if i != winner_idx]
            random.shuffle(others)
            medals  = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            standings = [f"{medals[0]} {winner_horse['name']}"] + \
                        [f"{medals[i+1]} {h['name']}" for i, h in enumerate(others)]

            won = (horse_index == winner_idx)
            if won:
                payout = int(self.bet * chosen["odds"])
                update_balance(self.player_id, payout)
                increment_stats(self.player_id, "wins")
                embed = discord.Embed(title="🐎  Race Finish  ·  You Won!", color=CLR_WIN)
                embed.add_field(name="Payout", value=f"**+${payout:,}**", inline=True)
            else:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                embed = discord.Embed(title="🐎  Race Finish  ·  Not This Time", color=CLR_LOSS)
                embed.add_field(name="Lost",   value=f"**-${self.bet:,}**",   inline=True)

            embed.description = DIVIDER
            embed.add_field(name="📋  Final Standings", value="\n".join(standings), inline=False)
            embed.add_field(name="Your Pick",           value=chosen["name"],        inline=True)
            embed.add_field(name="Balance",             value=f"`${get_balance(self.player_id):,}`", inline=False)
            embed.set_image(url=IMG_HORSE_RACING)
            embed.set_footer(text=luxury_footer(self.bet, get_balance(self.player_id)))
            await interaction.response.edit_message(embed=embed, view=None)
        return callback


# ===================== BOT SETUP =====================
class BlackjackBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members          = True
        super().__init__(command_prefix="!", intents=intents)
        self.current_status_index = 0

    async def setup_hook(self):
        print("Setup hook executed.")
        self.update_live_stats.start()

    async def on_error(self, event_method, *args, **kwargs):
        print(f"[Bot Error in {event_method}]")
        traceback.print_exc()

    @tasks.loop(seconds=60)
    async def update_live_stats(self):
        if not self.is_ready():
            return
        try:
            pipeline      = [{"$group": {"_id": None, "total": {"$sum": "$balance"}}}]
            result        = list(balances_col.aggregate(pipeline))
            total_circ    = result[0]["total"] if result else 0
            active_loans  = balances_col.count_documents({"loan_owed": {"$gt": 0}})

            if self.current_status_index == 0:
                text = f"${total_circ:,} in circulation 💰"
                self.current_status_index = 1
            else:
                text = f"{active_loans} active vault loans 🏦"
                self.current_status_index = 0

            await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=text))
        except Exception as e:
            print(f"[Live Stats Loop Error] {e}")

    @update_live_stats.before_loop
    async def before_update_live_stats(self):
        await self.wait_until_ready()


client = BlackjackBot()


@client.event
async def on_ready():
    print(f"Logged in as {client.user.name}!")
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Sync failed: {e}")


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    traceback.print_exc()
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ Cooldown — retry in **{error.retry_after:.1f}s**.", ephemeral=True)
        return
    msg = f"An error occurred: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"[Error Handler Failed] {e}")


# ── /help ─────────────────────────────────────────────────────────────────────
@client.tree.command(name="help", description="Show all available casino commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🎰  Casino Bot  ·  Command Guide", color=CLR_GOLD)
    embed.description = DIVIDER
    embed.add_field(
        name="🃏  Games",
        value=(
            "`/blackjack [bet]`  — Classic card game vs the dealer\n"
            "`/coinflip [bet]`   — Heads or tails prediction\n"
            "`/slots [bet]`      — Spin the reel machine\n"
            "`/roulette [bet]`   — European wheel betting\n"
            "`/horse_racing [bet]` — Pick your winning runner"
        ),
        inline=False
    )
    embed.add_field(
        name="💰  Economy",
        value=(
            "`/balance`         — Check your wallet\n"
            "`/daily`           — Claim 24h bonus\n"
            "`/leaderboard`     — Server wealth rankings\n"
            "`/stats [user]`    — Full performance card\n"
            "`/shop`            — Buy vanity roles\n"
            "`/borrow [amount]` — Take a vault loan\n"
            "`/pay_loan`        — Settle outstanding debt"
        ),
        inline=False
    )
    embed.set_footer(text="Casino Bot  ·  Built with precision 🎲")
    await interaction.response.send_message(embed=embed)


# ── /balance ──────────────────────────────────────────────────────────────────
@client.tree.command(name="balance", description="Check your current casino wallet balance")
async def balance(interaction: discord.Interaction):
    bal   = get_balance(interaction.user.id)
    embed = discord.Embed(title="💼  Wallet", color=CLR_GOLD)
    embed.description = DIVIDER
    embed.add_field(name="Account", value=interaction.user.mention, inline=True)
    embed.add_field(name="Balance", value=f"`${bal:,}`",            inline=True)
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)


# ── /daily ────────────────────────────────────────────────────────────────────
@client.tree.command(name="daily", description="Claim your 24-hour bonus reward")
async def daily_bonus(interaction: discord.Interaction):
    user_id   = interaction.user.id
    user_data = get_user_data(user_id)
    now       = datetime.now(timezone.utc)

    if user_data.get("last_daily"):
        last = user_data["last_daily"]
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except ValueError:
                last = None
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            nxt = last + timedelta(days=1)
            if now < nxt:
                remaining = nxt - now
                h, rem    = divmod(int(remaining.total_seconds()), 3600)
                m, _      = divmod(rem, 60)
                await interaction.response.send_message(
                    f"⏳ Already claimed! Come back in **{h}h {m}m**.", ephemeral=True)
                return

    reward = 500
    balances_col.update_one({"user_id": user_id}, {"$set": {"last_daily": now}})
    update_balance(user_id, reward)
    new_bal = get_balance(user_id)

    embed = discord.Embed(title="🎁  Daily Reward", color=CLR_GOLD)
    embed.description = f"**+${reward:,}** added to your wallet!\n{DIVIDER}"
    embed.add_field(name="New Balance", value=f"`${new_bal:,}`", inline=True)
    embed.set_footer(text="Returns in 24 hours")
    await interaction.response.send_message(embed=embed)


# ── /leaderboard ──────────────────────────────────────────────────────────────
@client.tree.command(name="leaderboard", description="View the wealthiest players on the server")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    top = list(balances_col.find().sort("balance", -1).limit(10))

    embed = discord.Embed(title="🏆  Wealth Leaderboard", color=CLR_GOLD)
    embed.description = DIVIDER
    medals = ["🥇", "🥈", "🥉"]
    lines  = []

    for idx, u in enumerate(top):
        uid   = u["user_id"]
        bal   = u["balance"]
        rank  = medals[idx] if idx < 3 else f"`#{idx+1}`"
        try:
            member = await interaction.guild.fetch_member(uid)
            name   = member.display_name
        except Exception:
            name = f"User({uid})"
        lines.append(f"{rank}  **{name}** — `${bal:,}`")

    embed.description += "\n" + ("\n".join(lines) if lines else "No players recorded yet.")
    embed.set_footer(text="Keep playing to climb the ranks!")
    await interaction.followup.send(embed=embed)


# ── /stats ────────────────────────────────────────────────────────────────────
def build_bar(value: float, total: float, length: int = 12) -> str:
    filled = max(0, min(length, round((value / total) * length) if total else 0))
    return "🟩" * filled + "⬛" * (length - filled)

def get_player_title(balance: int, win_rate: float, total_games: int) -> str:
    if balance >= 5_000_000:  return "👑 Casino Overlord"
    if balance >= 1_000_000:  return "💎 Server Elite"
    if balance >= 500_000:    return "🏆 High Roller Legend"
    if balance >= 250_000:    return "🦈 Card Shark"
    if balance >= 100_000:    return "✨ Casino VIP"
    if balance >= 25_000:     return "💰 Wealthy Gambler"
    if balance >= 5_000:      return "🎲 Active Player"
    if total_games == 0:      return "🆕 Newcomer"
    return "🃏 Casual Visitor"

def get_streak_badge(win_rate: float, total_games: int) -> str:
    if total_games < 5:   return "📊 Not Enough Data"
    if win_rate >= 75:    return "🔥 On Fire"
    if win_rate >= 60:    return "⚡ Hot Streak"
    if win_rate >= 50:    return "✅ Profitable"
    if win_rate >= 35:    return "📉 Struggling"
    return "💀 House Always Wins"

def wealth_color(balance: int) -> discord.Color:
    if balance >= 1_000_000: return discord.Color.gold()
    if balance >= 100_000:   return discord.Color.purple()
    if balance >= 25_000:    return discord.Color.teal()
    if balance >= 5_000:     return discord.Color.blue()
    return discord.Color.greyple()


@client.tree.command(name="stats", description="View your full casino performance profile")
@app_commands.describe(user="Target member (defaults to yourself)")
async def stats_command(interaction: discord.Interaction, user: discord.User = None):
    target    = user or interaction.user
    data      = get_user_data(target.id)
    wins      = data.get("wins",     0)
    losses    = data.get("losses",   0)
    balance   = data.get("balance",  0)
    loan_owed = data.get("loan_owed",0)
    total     = wins + losses
    win_rate  = (wins / total * 100) if total > 0 else 0.0

    title_str  = get_player_title(balance, win_rate, total)
    badge      = get_streak_badge(win_rate, total)
    rank_pos   = balances_col.count_documents({"balance": {"$gt": balance}}) + 1

    embed = discord.Embed(color=wealth_color(balance))
    embed.set_author(name=f"{target.display_name}  ·  {title_str}", icon_url=target.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)

    debt_line = f"\n> ⚠️ Active Debt: **`${loan_owed:,}`**" if loan_owed > 0 else ""
    embed.add_field(
        name=f"{DIVIDER}\n💼  Wallet",
        value=(
            f"> 💵 Balance: **`${balance:,}`**{debt_line}\n"
            f"> 🏅 Server Rank: **`#{rank_pos}`**"
        ),
        inline=False
    )
    embed.add_field(
        name=f"{DIVIDER}\n📊  Performance",
        value=(
            f"> 🎮 Games Played: `{total}`\n"
            f"> 🎉 Wins: `{wins}`  {badge}\n"
            f"> ❌ Losses: `{losses}`\n"
            f"> 📈 Win Rate: `{win_rate:.1f}%`"
        ),
        inline=False
    )
    embed.add_field(
        name=f"{DIVIDER}\n📉  Win / Loss Ratio",
        value=(
            f"> 🟩 Wins    `{win_rate:5.1f}%`  {build_bar(wins, total)}\n"
            f"> ⬛ Losses  `{100-win_rate:5.1f}%`  {build_bar(losses, total)}"
        ),
        inline=False
    )
    embed.set_footer(text=f"Casino Profile  ·  ID {target.id}")
    await interaction.response.send_message(embed=embed)


# ── /shop ─────────────────────────────────────────────────────────────────────
@client.tree.command(name="shop", description="Purchase premium vanity roles for your profile")
async def shop_command(interaction: discord.Interaction):
    embed = discord.Embed(title="💎  Casino Shop", color=CLR_GOLD)
    embed.description = (
        "Upgrade your server profile with exclusive vanity roles.\n"
        f"{DIVIDER}"
    )
    for info in SHOP_ITEMS.values():
        embed.add_field(
            name=info["name"],
            value=f"`${info['price']:,}`\n*{info['desc']}*",
            inline=True
        )
    embed.set_footer(text="Roles are created automatically on first purchase.")
    await interaction.response.send_message(embed=embed, view=ShopDropdownView())


# ── /manage_money ─────────────────────────────────────────────────────────────
@client.tree.command(name="manage_money", description="[Dev] Adjust a user's virtual balance")
@app_commands.describe(action="Action to perform", user="Target user", amount="Amount (positive)")
@app_commands.choices(action=[
    app_commands.Choice(name="Add ➕",    value="add"),
    app_commands.Choice(name="Deduct ➖", value="deduct"),
])
async def manage_money(interaction: discord.Interaction, action: str, user: discord.User, amount: int):
    app_info = await interaction.client.application_info()
    if interaction.user.id not in {app_info.owner.id, 339082987114627072}:
        await interaction.response.send_message("❌ Developer-only command.", ephemeral=True)
        return
    if amount < 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    actual = amount if action == "add" else -amount
    update_balance(user.id, actual)
    new_bal = get_balance(user.id)

    embed = discord.Embed(title="⚙️  Admin Balance Adjustment", color=CLR_GOLD)
    embed.description = DIVIDER
    embed.add_field(name="Action",      value="Added ➕" if action == "add" else "Deducted ➖", inline=True)
    embed.add_field(name="Target",      value=user.mention,    inline=True)
    embed.add_field(name="Amount",      value=f"`${amount:,}`",  inline=True)
    embed.add_field(name="New Balance", value=f"`${new_bal:,}`", inline=False)
    embed.set_footer(text="Authorized by Bot Developer")
    await interaction.response.send_message(embed=embed)


# ── /borrow ───────────────────────────────────────────────────────────────────
@client.tree.command(name="borrow", description="Request a vault loan backed by your role tier")
@app_commands.describe(amount="Amount to borrow (minimum $100)")
async def borrow_command(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    user  = interaction.user
    guild = interaction.guild

    user_data = get_user_data(user.id)
    if user_data.get("loan_owed", 0) > 0:
        await interaction.followup.send(
            f"❌ You already hold an active loan of **`${user_data['loan_owed']:,}`**.\n"
            f"Settle it with `/pay_loan` first.", ephemeral=True)
        return
    if amount < 100:
        await interaction.followup.send("❌ Minimum loan is **$100**.", ephemeral=True)
        return

    max_loan, interest_rate, tier_name = get_user_loan_tier(user)
    if amount > max_loan:
        await interaction.followup.send(
            f"❌ Credit limit exceeded! Your tier (**{tier_name}**) allows up to `${max_loan:,}`.",
            ephemeral=True)
        return

    debt_role = discord.utils.get(guild.roles, name="Debtor 🔴")
    if not debt_role:
        try:
            debt_role = await guild.create_role(name="Debtor 🔴", color=discord.Color.red(), reason="Auto-created Debtor role")
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing `Manage Roles` permission.", ephemeral=True)
            return

    try:
        await user.add_roles(debt_role)
    except discord.Forbidden:
        await interaction.followup.send("❌ Cannot apply Debtor role — check hierarchy.", ephemeral=True)
        return

    total_debt = int(amount * (1 + interest_rate))
    balances_col.update_one({"user_id": user.id}, {"$set": {"loan_owed": total_debt}})
    update_balance(user.id, amount)

    embed = discord.Embed(title="🏦  Loan Approved", color=CLR_NEUTRAL)
    embed.description = f"Funds have been deposited to your wallet.\n{DIVIDER}"
    embed.add_field(name="Principal",   value=f"`${amount:,}`",               inline=True)
    embed.add_field(name="Interest",    value=f"`{interest_rate*100:.0f}%`  ({tier_name})", inline=True)
    embed.add_field(name="Total Owed",  value=f"**`${total_debt:,}`**",        inline=False)
    embed.set_footer(text="Shop purchases are locked until /pay_loan is used.")
    await interaction.followup.send(embed=embed)


# ── /pay_loan ─────────────────────────────────────────────────────────────────
@client.tree.command(name="pay_loan", description="Settle your outstanding loan to unlock full account access")
async def pay_loan_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user  = interaction.user
    guild = interaction.guild

    user_data = get_user_data(user.id)
    owed = user_data.get("loan_owed", 0)
    if owed <= 0:
        await interaction.followup.send("❌ No active loan found on your account.", ephemeral=True)
        return

    if get_balance(user.id) < owed:
        await interaction.followup.send(
            f"❌ Insufficient funds — debt is `${owed:,}`, balance is `${get_balance(user.id):,}`.",
            ephemeral=True)
        return

    update_balance(user.id, -owed)
    balances_col.update_one({"user_id": user.id}, {"$set": {"loan_owed": 0}})

    debt_role = discord.utils.get(guild.roles, name="Debtor 🔴")
    if debt_role and debt_role in user.roles:
        try:
            await user.remove_roles(debt_role)
        except discord.Forbidden:
            pass

    embed = discord.Embed(title="✅  Loan Settled", color=CLR_WIN)
    embed.description = f"Your account restrictions have been lifted, {user.mention}.\n{DIVIDER}"
    embed.add_field(name="Paid",    value=f"`${owed:,}`",              inline=True)
    embed.add_field(name="Balance", value=f"`${get_balance(user.id):,}`", inline=True)
    embed.set_footer(text="All shop and transfer privileges restored.")
    await interaction.followup.send(embed=embed)


# ── /blackjack ────────────────────────────────────────────────────────────────
@client.tree.command(name="blackjack", description="Play a hand of Blackjack at the casino table")
@app_commands.describe(bet="Amount to wager")
async def blackjack(interaction: discord.Interaction, bet: int):
    await interaction.response.defer()
    user_id     = interaction.user.id
    current_bal = get_balance(user_id)

    if current_bal <= 0:
        update_balance(user_id, 100)
        current_bal = 100
        await interaction.channel.send(f"⚠️ {interaction.user.mention} — bankrupt! The house granted **$100** as a safety fund.")

    if bet < 1:
        await interaction.followup.send("❌ Bet must be at least $1.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.followup.send(f"❌ You cannot bet `${bet:,}` — wallet holds `${current_bal:,}`.", ephemeral=True)
        return

    suits  = ["♠️","♥️","♦️","♣️"]
    ranks  = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    deck   = [f"{r}{s}" for r in ranks for s in suits]
    random.shuffle(deck)
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    view         = BlackjackView(user_id, deck, player_hand, dealer_hand, bet)
    player_score = view.calculate_score(player_hand)

    embed = discord.Embed(title="🃏  Blackjack  ·  Your Turn", color=CLR_DARK)
    embed.description = DIVIDER
    embed.add_field(name="🎩  Dealer", value=f"{card_display(dealer_hand[0])}  `??`\n`Score: ?`",                                inline=True)
    embed.add_field(name="🙋  Your Hand", value=f"{hand_display(player_hand)}\n`Score: {player_score}`", inline=True)
    embed.set_footer(text=luxury_footer(bet, current_bal))
    await interaction.followup.send(embed=embed, view=view)


# ── /coinflip ─────────────────────────────────────────────────────────────────
@client.tree.command(name="coinflip", description="Flip a coin — call heads or tails")
@app_commands.describe(bet="Amount to wager")
async def coinflip_cmd(interaction: discord.Interaction, bet: int):
    user_id     = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ Bet must be at least $1.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds — balance: `${current_bal:,}`", ephemeral=True)
        return

    embed = discord.Embed(title="🪙  Coin Flip", color=CLR_GOLD)
    embed.description = f"The coin is in the air — call it!\n{DIVIDER}"
    embed.add_field(name="Wager",   value=f"`${bet:,}`",      inline=True)
    embed.add_field(name="Balance", value=f"`${current_bal:,}`", inline=True)
    embed.set_image(url=IMG_COIN_FLIP)
    embed.set_footer(text="Choose heads 🦅 or tails 🪙")

    view = CoinFlipView(user_id, bet)

    heads_btn = discord.ui.Button(label="Heads 🦅", style=discord.ButtonStyle.blurple)
    tails_btn = discord.ui.Button(label="Tails 🪙",  style=discord.ButtonStyle.secondary)

    async def heads_cb(i): await CoinFlipView(user_id, bet).process_flip(i, "heads")
    async def tails_cb(i): await CoinFlipView(user_id, bet).process_flip(i, "tails")

    heads_btn.callback = heads_cb
    tails_btn.callback = tails_cb
    view.clear_items()
    view.add_item(heads_btn)
    view.add_item(tails_btn)

    await interaction.response.send_message(embed=embed, view=view)


# ── /slots ────────────────────────────────────────────────────────────────────
@client.tree.command(name="slots", description="Spin the slot machine reels")
@app_commands.describe(bet="Amount to wager per spin")
async def slots_cmd(interaction: discord.Interaction, bet: int):
    user_id     = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ Bet must be at least $1.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds — balance: `${current_bal:,}`", ephemeral=True)
        return

    await interaction.response.defer()
    update_balance(user_id, -bet)
    reels  = spin_slots()
    payout, combo = get_slot_payout(reels, bet)
    await _send_slots_result(interaction, user_id, bet, reels, payout, combo)


# ── /roulette ─────────────────────────────────────────────────────────────────
@client.tree.command(name="roulette", description="Place your bet on the European roulette wheel")
@app_commands.describe(bet="Amount to wager")
async def roulette_cmd(interaction: discord.Interaction, bet: int):
    user_id     = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ Bet must be at least $1.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds — balance: `${current_bal:,}`", ephemeral=True)
        return

    embed = discord.Embed(title="🎡  Roulette", color=CLR_GOLD)
    embed.description = f"The wheel is spinning — place your chips!\n{DIVIDER}"
    embed.add_field(name="Wager",   value=f"`${bet:,}`",         inline=True)
    embed.add_field(name="Balance", value=f"`${current_bal:,}`", inline=True)
    embed.set_image(url=IMG_ROULETTE)
    embed.set_footer(text="All bets pay ×2 on a win")
    await interaction.response.send_message(embed=embed, view=RouletteView(user_id, bet))


# ── /horse_racing ─────────────────────────────────────────────────────────────
@client.tree.command(name="horse_racing", description="Pick a runner and bet on the race outcome")
@app_commands.describe(bet="Amount to wager")
async def horse_racing_cmd(interaction: discord.Interaction, bet: int):
    user_id     = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ Bet must be at least $1.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds — balance: `${current_bal:,}`", ephemeral=True)
        return

    odds_lines = "\n".join(f"`×{h['odds']}`  {h['name']}" for h in HORSES)
    embed = discord.Embed(title="🐎  Horse Racing", color=CLR_GOLD)
    embed.description = f"Pick your runner from the buttons below!\n{DIVIDER}"
    embed.add_field(name="📋  Race Odds", value=odds_lines, inline=False)
    embed.add_field(name="Wager",   value=f"`${bet:,}`",         inline=True)
    embed.add_field(name="Balance", value=f"`${current_bal:,}`", inline=True)
    embed.set_image(url=IMG_HORSE_RACING)
    embed.set_footer(text="Higher odds = bigger payout & lower chance of winning")
    await interaction.response.send_message(embed=embed, view=HorseRacingView(user_id, bet))


# ── /purge ────────────────────────────────────────────────────────────────────
@client.tree.command(name="purge", description="Delete a number of messages from this channel")
@app_commands.describe(amount="Number of messages to delete")
async def purge(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ Missing `Manage Messages` permission.", ephemeral=True)
        return
    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Deleted {len(deleted)} message(s).", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ===================== HEALTH SERVER =====================
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port   = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()


async def main():
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_TOKEN missing.")
        return
    threading.Thread(target=run_health_server, daemon=True).start()
    print("Health check server started.")
    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
