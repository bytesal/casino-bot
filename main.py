import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import os
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from pymongo import MongoClient
from datetime import datetime, timedelta

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
    if "wins" not in user_data:
        user_data["wins"] = 0
        updated = True
    if "losses" not in user_data:
        user_data["losses"] = 0
        updated = True
    if "last_daily" not in user_data:
        user_data["last_daily"] = None
        updated = True
    if "loan_owed" not in user_data:
        user_data["loan_owed"] = 0
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
    {"role": "Millionaire 👑", "max_loan": 2000000, "interest": 0.05},
    {"role": "Card Shark 🦈", "max_loan": 500000, "interest": 0.06},
    {"role": "Casino VIP ✨", "max_loan": 200000, "interest": 0.08},
    {"role": "High Roller 💰", "max_loan": 50000, "interest": 0.10},
    {"role": "Gambler 🎲", "max_loan": 10000, "interest": 0.12},
]
DEFAULT_LOAN_LIMIT = 2000
DEFAULT_INTEREST = 0.15

def get_user_loan_tier(member):
    user_roles = [role.name for role in member.roles]
    for tier in LOAN_LIMITS:
        if tier["role"] in user_roles:
            return tier["max_loan"], tier["interest"], tier["role"]
    return DEFAULT_LOAN_LIMIT, DEFAULT_INTEREST, "Default Player"

# ===================== INTERACTIVE SHOP COMPONENTS =====================
class ShopDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=info["name"], value=item_id, description=f"${info['price']:,} — {info['desc']}")
            for item_id, info in SHOP_ITEMS.items()
        ]
        super().__init__(placeholder="Select a premium role to purchase... 🛍️", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        guild = interaction.guild
        
        user_data = get_user_data(user.id)
        debt_role = discord.utils.get(guild.roles, name="Debtor 🔴")
        if user_data.get("loan_owed", 0) > 0 or (debt_role and debt_role in user.roles):
            await interaction.followup.send(
                f"❌ Transaction Blocked! You have an active unpaid loan debt of **${user_data.get('loan_owed', 0):,}**. Please fulfill your financial obligations via `/pay_loan` first!",
                ephemeral=True
            )
            return

        item_id = self.values[0]
        item = SHOP_ITEMS[item_id]
        
        current_bal = get_balance(user.id)
        if current_bal < item["price"]:
            await interaction.followup.send(
                f"❌ Transaction Denied! You need **${item['price']:,}** to buy **{item['name']}**, but your current balance is only **${current_bal}**.", 
                ephemeral=True
            )
            return

        role = discord.utils.get(guild.roles, name=item["name"])
        if not role:
            try:
                role = await guild.create_role(
                    name=item["name"], 
                    color=item["color"], 
                    reason="Automatic dynamic creation via Casino Interactive Shop"
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ Bot Configuration Error! The bot is missing `Manage Roles` authorization permission to create this role.", 
                    ephemeral=True
                )
                return
            except Exception as e:
                await interaction.followup.send(f"❌ Structural error generating server role: {e}", ephemeral=True)
                return

        if role in user.roles:
            await interaction.followup.send(f"⚠️ Account Note: You already own the premium **{item['name']}** role designation!", ephemeral=True)
            return

        try:
            await user.add_roles(role)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Hierarchy Permission Exception! This role is positioned higher than the bot's current maximum management group tier.", 
                ephemeral=True
            )
            return

        update_balance(user.id, -item["price"])
        new_bal = get_balance(user.id)
        
        embed = discord.Embed(title="🛍️ Interactive Shop Purchase Successful!", color=discord.Color.green())
        embed.description = f"Congratulations {user.mention}! You have successfully purchased and unlocked the **{item['name']}** role directly from the menu!"
        embed.add_field(name="Amount Charged", value=f"-${item['price']:,}", inline=True)
        embed.add_field(name="Remaining Funds Wallet", value=f"${new_bal:,}", inline=True)
        embed.set_footer(text="Vanity badge profile upgrade complete ✨")
        
        await interaction.followup.send(embed=embed, ephemeral=False)

class ShopDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShopDropdown())

# ===================== BLACKJACK =====================
class BlackjackView(discord.ui.View):
    def __init__(self, player_id, deck, player_hand, dealer_hand, bet):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.deck = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.bet = bet

    def calculate_score(self, hand):
        score = 0
        aces = 0
        card_values = {
            '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
            '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11
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
            aces -= 1
        return score

    def get_hand_string(self, hand):
        return ", ".join(hand)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ This game is not for you!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Hit 🃏", style=discord.ButtonStyle.blurple)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.player_hand.append(self.deck.pop())
            player_score = self.calculate_score(self.player_hand)
            if player_score > 21:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                new_bal = get_balance(self.player_id)
                embed = discord.Embed(title="💥 Blackjack - Busted!", color=discord.Color.red())
                embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
                embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]}, [Hidden]", inline=False)
                embed.add_field(name="Result", value=f"You lost **${self.bet}**! Your new balance is **${new_bal}**.", inline=False)
                self.stop()
                await interaction.response.edit_message(embed=embed, view=None)
            else:
                embed = discord.Embed(title="🃏 Blackjack Game", color=discord.Color.blue())
                embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
                embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]}, [Hidden]", inline=False)
                embed.set_footer(text=f"Current Bet: ${self.bet}")
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @discord.ui.button(label="Double Down 💰", style=discord.ButtonStyle.secondary)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            current_bal = get_balance(self.player_id)
            if current_bal < self.bet * 2:
                await interaction.response.send_message("❌ You do not have enough balance to Double Down!", ephemeral=True)
                return
            self.stop()
            self.bet *= 2
            self.player_hand.append(self.deck.pop())
            player_score = self.calculate_score(self.player_hand)
            if player_score > 21:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                new_bal = get_balance(self.player_id)
                embed = discord.Embed(title="💥 Blackjack - Busted on Double!", color=discord.Color.red())
                embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
                embed.add_field(name="Dealer Hand", value=self.get_hand_string(self.dealer_hand), inline=False)
                embed.add_field(name="Result", value=f"You lost **${self.bet}**! Your balance is: **${new_bal}**.", inline=False)
                await interaction.response.edit_message(embed=embed, view=None)
                return
            dealer_score = self.calculate_score(self.dealer_hand)
            while dealer_score < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_score = self.calculate_score(self.dealer_hand)
            if dealer_score > 21 or player_score > dealer_score:
                update_balance(self.player_id, self.bet)
                increment_stats(self.player_id, "wins")
                title, color, res_msg = "You Win! 🎉", discord.Color.green(), f"You won **${self.bet}**!"
            elif player_score < dealer_score:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                title, color, res_msg = "Dealer Wins! ❌", discord.Color.red(), f"You lost **${self.bet}**!"
            else:
                title, color, res_msg = "Push! 🤝", discord.Color.gold(), "Your bet was returned."
            new_bal = get_balance(self.player_id)
            embed = discord.Embed(title=f"🃏 Blackjack (Double Down) - {title}", color=color)
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)} (Score: {dealer_score})", inline=False)
            embed.add_field(name="Result", value=f"{res_msg} Your new balance is **${new_bal}**.", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @discord.ui.button(label="Stand 🛑", style=discord.ButtonStyle.green)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.stop()
            player_score = self.calculate_score(self.player_hand)
            dealer_score = self.calculate_score(self.dealer_hand)
            while dealer_score < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_score = self.calculate_score(self.dealer_hand)
            if dealer_score > 21 or player_score > dealer_score:
                update_balance(self.player_id, self.bet)
                increment_stats(self.player_id, "wins")
                title, color, res_msg = "You Win! 🎉", discord.Color.green(), f"Congratulations! You won **${self.bet}**!"
            elif player_score < dealer_score:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                title, color, res_msg = "Dealer Wins! ❌", discord.Color.red(), f"You lost **${self.bet}**!"
            else:
                title, color, res_msg = "Push! 🤝", discord.Color.gold(), "Your bet was returned."
            new_bal = get_balance(self.player_id)
            embed = discord.Embed(title=f"🃏 Blackjack - {title}", color=color)
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)} (Score: {dealer_score})", inline=False)
            embed.add_field(name="Result", value=f"{res_msg} Your new balance is **${new_bal}**.", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)


# ===================== COIN FLIP 🪙 =====================
async def coinflip(interaction: discord.Interaction, bet: int, choice: str):
    user_id = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ The bet must be greater than 0.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds! Your balance is: **${current_bal}**", ephemeral=True)
        return
    result = random.choice(["heads", "tails"])
    result_emoji = "🦅" if result == "heads" else "🪙"
    won = choice == result
    if won:
        update_balance(user_id, bet)
        increment_stats(user_id, "wins")
        title, color, res_msg = "🎉 Correct! You Won!", discord.Color.green(), f"You won **${bet}**!"
    else:
        update_balance(user_id, -bet)
        increment_stats(user_id, "losses")
        title, color, res_msg = "💥 Wrong! You Lost!", discord.Color.red(), f"You lost **${bet}**!"
    new_bal = get_balance(user_id)
    embed = discord.Embed(title=f"🪙 Coin Flip - {title}", color=color)
    embed.add_field(name="Your Choice", value=choice.capitalize(), inline=True)
    embed.add_field(name="Result", value=f"{result_emoji} {result.capitalize()}", inline=True)
    embed.add_field(name="Outcome", value=f"{res_msg} Your new balance is **${new_bal}**", inline=False)
    await interaction.response.send_message(embed=embed)


# ===================== SLOTS 🎰 =====================
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
        return SLOT_PAYOUTS[combo] * bet, f"**Triple {combo[0]}** 🎊"
    if reels.count("🍒") == 2:
        return bet, "Double Cherry 🍒🍒"
    return 0, "No Combination 😔"

async def slots(interaction: discord.Interaction, bet: int):
    user_id = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ The bet must be greater than 0.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds! Your balance is: **${current_bal}**", ephemeral=True)
        return
    await interaction.response.defer()
    spinning_embed = discord.Embed(title="🎰 Slot Machine", description="🎰 | 🔄 🔄 🔄 | Spinning...", color=discord.Color.gold())
    msg = await interaction.followup.send(embed=spinning_embed)
    await asyncio.sleep(1.5)
    reels = spin_slots()
    payout, combo_name = get_slot_payout(reels, bet)
    reels_display = " | ".join(reels)
    if payout > 0:
        update_balance(user_id, payout)
        increment_stats(user_id, "wins")
        new_bal = get_balance(user_id)
        embed = discord.Embed(title="🎰 Slot Machine - 🎉 Jackpot!", color=discord.Color.green())
        embed.add_field(name="Result", value=f"🎰 | {reels_display} |", inline=False)
        embed.add_field(name="Combination", value=combo_name, inline=True)
        embed.add_field(name="Payout", value=f"**+${payout}**", inline=True)
        embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
    else:
        update_balance(user_id, -bet)
        increment_stats(user_id, "losses")
        new_bal = get_balance(user_id)
        embed = discord.Embed(title="🎰 Slot Machine - Lost!", color=discord.Color.red())
        embed.add_field(name="Result", value=f"🎰 | {reels_display} |", inline=False)
        embed.add_field(name="Combination", value=combo_name, inline=True)
        embed.add_field(name="Loss", value=f"**-${bet}**", inline=True)
        embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
    embed.set_footer(text="💎x20 | 7️⃣x15 | ⭐x10 | 🍇x8 | 🍊x6 | 🍋x4 | 🍒x3 (Multiplied by Bet)")
    await msg.edit(embed=embed)


# ===================== ROULETTE 🎡 =====================
ROULETTE_NUMBERS = list(range(0, 37))
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMBERS = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

class RouletteView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=45)
        self.player_id = player_id
        self.bet = bet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ This table is not for you!", ephemeral=True)
            return False
        return True

    async def resolve(self, interaction, bet_type, display_name):
        self.stop()
        result = random.choice(ROULETTE_NUMBERS)
        color_emoji = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        won = False
        payout = 0
        if bet_type == "red" and result in RED_NUMBERS: won = True; payout = self.bet
        elif bet_type == "black" and result in BLACK_NUMBERS: won = True; payout = self.bet
        elif bet_type == "even" and result != 0 and result % 2 == 0: won = True; payout = self.bet
        elif bet_type == "odd" and result % 2 == 1: won = True; payout = self.bet
        elif bet_type == "low" and 1 <= result <= 18: won = True; payout = self.bet
        elif bet_type == "high" and 19 <= result <= 36: won = True; payout = self.bet

        if won:
            update_balance(self.player_id, payout)
            increment_stats(self.player_id, "wins")
            new_bal = get_balance(self.player_id)
            embed = discord.Embed(title="🎡 Roulette - 🎉 You Won!", color=discord.Color.green())
        else:
            update_balance(self.player_id, -self.bet)
            increment_stats(self.player_id, "losses")
            new_bal = get_balance(self.player_id)
            embed = discord.Embed(title="🎡 Roulette - Lost!", color=discord.Color.red())

        embed.add_field(name="Ball Landed On", value=f"{color_emoji} **{result}**", inline=True)
        embed.add_field(name="Your Bet", value=display_name, inline=True)
        embed.add_field(name="Payout/Loss", value=f"**{'+ ' if won else '- '}${payout if won else self.bet}**", inline=True)
        embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="🔴 Red (x2)", style=discord.ButtonStyle.danger)
    async def bet_red(self, i, b): await self.resolve(i, "red", "🔴 Red")
    @discord.ui.button(label="⚫ Black (x2)", style=discord.ButtonStyle.secondary)
    async def bet_black(self, i, b): await self.resolve(i, "black", "⚫ Black")
    @discord.ui.button(label="Even (x2)", style=discord.ButtonStyle.blurple)
    async def bet_even(self, i, b): await self.resolve(i, "even", "Even")
    @discord.ui.button(label="Odd (x2)", style=discord.ButtonStyle.blurple)
    async def bet_odd(self, i, b): await self.resolve(i, "odd", "Odd")
    @discord.ui.button(label="1-18 (x2)", style=discord.ButtonStyle.green)
    async def bet_low(self, i, b): await self.resolve(i, "low", "1-18")
    @discord.ui.button(label="19-36 (x2)", style=discord.ButtonStyle.green)
    async def bet_high(self, i, b): await self.resolve(i, "high", "19-36")

async def roulette(interaction: discord.Interaction, bet: int, number: int = None):
    user_id = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ The bet must be greater than 0.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds! Balance: **${current_bal}**", ephemeral=True)
        return
    if number is not None:
        if not (0 <= number <= 36):
            await interaction.response.send_message("❌ Number must be between 0 and 36.", ephemeral=True)
            return
        result = random.choice(ROULETTE_NUMBERS)
        color_emoji = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        if result == number:
            payout = bet * 35
            update_balance(user_id, payout)
            increment_stats(user_id, "wins")
            new_bal = get_balance(user_id)
            embed = discord.Embed(title="🎡 Roulette - 🤑 Jackpot!", color=discord.Color.gold())
            embed.add_field(name="Ball Landed On", value=f"{color_emoji} **{result}**", inline=True)
            embed.add_field(name="Payout", value=f"**+${payout}** (x35!) 🤑", inline=False)
            embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
        else:
            update_balance(user_id, -bet)
            increment_stats(user_id, "losses")
            new_bal = get_balance(user_id)
            embed = discord.Embed(title="🎡 Roulette - Lost!", color=discord.Color.red())
            embed.add_field(name="Ball Landed On", value=f"{color_emoji} **{result}**", inline=True)
            embed.add_field(name="Your Bet", value=f"Number {number}", inline=True)
            embed.add_field(name="Loss", value=f"**-${bet}**", inline=False)
            embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
        await interaction.response.send_message(embed=embed)
        return
    view = RouletteView(user_id, bet)
    embed = discord.Embed(title="🎡 Roulette Table", description="Choose your bet type below! 👇", color=discord.Color.gold())
    embed.add_field(name="Active Bet", value=f"**${bet}**", inline=True)
    embed.add_field(name="Your Wallet", value=f"**${current_bal}**", inline=True)
    embed.set_footer(text="You have 45 seconds to choose!")
    await interaction.response.send_message(embed=embed, view=view)


# ===================== HORSE RACING 🐎 =====================
HORSES = [
    {"name": "Lightning ⚡", "odds": 2.0},
    {"name": "Blizzard 💨", "odds": 2.5},
    {"name": "Falcon 🦅", "odds": 3.0},
    {"name": "Phantom 😈", "odds": 4.0},
    {"name": "Clover 🍀", "odds": 5.0},
]

class HorseRacingView(discord.ui.View):
    def __init__(self, player_id, bet):
        super().__init__(timeout=45)
        self.player_id = player_id
        self.bet = bet
        for i, horse in enumerate(HORSES):
            button = discord.ui.Button(
                label=f"{horse['name']} (x{horse['odds']})",
                style=discord.ButtonStyle.blurple,
                custom_id=f"horse_{i}"
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

    def _make_callback(self, horse_index):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.player_id:
                await interaction.response.send_message("❌ This race is not for you!", ephemeral=True)
                return
            self.stop()
            chosen_horse = HORSES[horse_index]
            weights = [1 / h["odds"] for h in HORSES]
            winner_index = random.choices(range(len(HORSES)), weights=weights, k=1)[0]
            winner_horse = HORSES[winner_index]
            others = [h for i, h in enumerate(HORSES) if i != winner_index]
            random.shuffle(others)
            race_display = [f"🥇 {winner_horse['name']}"]
            medals = ["🥈", "🥉", "4.", "5."]
            for rank, h in enumerate(others):
                race_display.append(f"{medals[rank]} {h['name']}")
            won = horse_index == winner_index
            if won:
                payout = int(self.bet * chosen_horse["odds"])
                update_balance(self.player_id, payout)
                increment_stats(self.player_id, "wins")
                new_bal = get_balance(self.player_id)
                embed = discord.Embed(title="🐎 Horse Racing - 🎉 Victory!", color=discord.Color.green())
                embed.add_field(name="Race Standings", value="\n".join(race_display), inline=False)
                embed.add_field(name="Your Horse", value=chosen_horse["name"], inline=True)
                embed.add_field(name="Payout", value=f"**+${payout}** (x{chosen_horse['odds']})", inline=True)
                embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
            else:
                update_balance(self.player_id, -self.bet)
                increment_stats(self.player_id, "losses")
                new_bal = get_balance(self.player_id)
                embed = discord.Embed(title="🐎 Horse Racing - Defeat!", color=discord.Color.red())
                embed.add_field(name="Race Standings", value="\n".join(race_display), inline=False)
                embed.add_field(name="Your Horse", value=chosen_horse["name"], inline=True)
                embed.add_field(name="Winner", value=winner_horse["name"], inline=True)
                embed.add_field(name="Loss", value=f"**-${self.bet}**", inline=True)
                embed.add_field(name="New Balance", value=f"**${new_bal}**", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        return callback

async def horse_racing(interaction: discord.Interaction, bet: int):
    user_id = interaction.user.id
    current_bal = get_balance(user_id)
    if bet < 1:
        await interaction.response.send_message("❌ The bet must be greater than 0.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.response.send_message(f"❌ Insufficient funds! Balance: **${current_bal}**", ephemeral=True)
        return
    view = HorseRacingView(user_id, bet)
    embed = discord.Embed(title="🐎 Derby Horse Racing", description="Choose your winning horse! 👇", color=discord.Color.gold())
    for horse in HORSES:
        embed.add_field(name=horse["name"], value=f"Pays x{horse['odds']}", inline=True)
    embed.set_footer(text=f"Bet: ${bet} | Wallet: ${current_bal} | Time: 45s")
    await interaction.response.send_message(embed=embed, view=view)


# ===================== BOT SETUP & LOOPS =====================
class BlackjackBot(commands.Bot):
    def __init__(self):
        bot_intents = discord.Intents.default()
        bot_intents.message_content = True
        bot_intents.members = True
        super().__init__(command_prefix="!", intents=bot_intents)
        self.current_status_index = 0

    async def setup_hook(self):
        print("Setup hook executed.")
        self.update_live_stats.start()

    async def on_error(self, event_method, *args, **kwargs):
        import traceback
        print(f"[Bot Error in {event_method}]")
        traceback.print_exc()

    @tasks.loop(seconds=60)
    async def update_live_stats(self):
        if not self.is_ready():
            return
        try:
            pipeline = [{"$group": {"_id": None, "total": {"$sum": "$balance"}}}]
            result = list(balances_col.aggregate(pipeline))
            total_circulation = result[0]["total"] if result else 0

            active_loans = balances_col.count_documents({"loan_owed": {"$gt": 0}})

            if self.current_status_index == 0:
                activity_text = f"${total_circulation:,} in circulation 💰"
                self.current_status_index = 1
            else:
                activity_text = f"{active_loans} Active Vault Loans 🏦"
                self.current_status_index = 0

            custom_activity = discord.Activity(
                type=discord.ActivityType.watching, 
                name=activity_text
            )
            await self.change_presence(activity=custom_activity)
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
        # Automated Background Global Sync on System Startup Log
        synced = await client.tree.sync()
        print(f"Global commands automated synchronization completed. Synced {len(synced)} entries.")
    except Exception as e:
        print(f"Failed to execute automated tree sync: {e}")


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"⏳ On Cooldown! You can use this command again in **{error.retry_after:.1f}** seconds.", ephemeral=True)
        return
    msg = f"An error occurred: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"[Error Handler Failed] {e}")


# ---- Commands ----

@client.tree.command(name="help", description="Display full guidelines and instructions on how to use the casino bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Casino Bot - Help Dashboard", color=discord.Color.gold())
    embed.add_field(
        name="🎮 Casino Game Commands",
        value=(
            "`/blackjack [bet]` - Play a high-stakes game of Blackjack.\n"
            "`/coinflip [bet] [choice]` - Flip a virtual coin to double your stakes.\n"
            "`/slots [bet]` - Spin the classic slot machine.\n"
            "`/roulette [bet] [number]` - Bet on a color, type, or specific number.\n"
            "`/horse_racing [bet]` - Wager on server horse derby racing.\n"
        ),
        inline=False
    )
    embed.add_field(
        name="💰 Server Economy & Shop",
        value=(
            "`/balance` - Check your wallet data.\n"
            "`/daily` - Collect your 24-hour bonus salary reward.\n"
            "`/leaderboard` - Review the wealthiest system users.\n"
            "`/stats [user]` - Look up casino play analytics & performance metrics.\n"
            "`/shop` - Open the interactive premium luxury roles store menu.\n"
            "`/borrow [amount]` - Request a temporary loan backed by your highest tier role.\n"
            "`/pay_loan` - Settle your outstanding debts and unfreeze your profile permissions.\n"
        ),
        inline=False
    )
    embed.add_field(
        name="🃏 Blackjack Overview Rules",
        value="1. Match or get closer to **21** than the dealer without going over.\n2. **Hit**: Take another card.\n3. **Stand**: Hold your hand and pass.\n4. **Double Down**: Double your initial bet, draw exactly one card, and stand.",
        inline=False
    )
    embed.add_field(
        name="🎰 Slot Machine Multipliers",
        value="💎x20 | 7️⃣x15 | ⭐x10 | 🍇x8 | 🍊x6 | 🍋x4 | 🍒x3",
        inline=False
    )
    embed.set_footer(text="Developed with pure passion 💻")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="balance", description="Check your current server virtual money balance statement")
async def balance(interaction: discord.Interaction):
    user_bal = get_balance(interaction.user.id)
    embed = discord.Embed(title="💰 Bank Account Statement", color=discord.Color.green())
    embed.add_field(name="Account Holder", value=interaction.user.mention, inline=True)
    embed.add_field(name="Net Balance", value=f"**${user_bal}**", inline=True)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="daily", description="Claim your 24-hour bonus casino reward allowance")
async def daily_bonus(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_data = get_user_data(user_id)
    now = datetime.utcnow()
    
    if user_data.get("last_daily"):
        last_claimed = user_data["last_daily"]
        if isinstance(last_claimed, str):
            try:
                last_claimed = datetime.fromisoformat(last_claimed)
            except ValueError:
                last_claimed = None

        if last_claimed:
            next_claim = last_claimed + timedelta(days=1)
            if now < next_claim:
                time_remaining = next_claim - now
                hours, remainder = divmod(int(time_remaining.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                await interaction.response.send_message(
                    f"⏳ You have already claimed your daily reward! Please return in **{hours} hours and {minutes} minutes**.", 
                    ephemeral=True
                )
                return

    daily_reward = 500
    balances_col.update_one(
        {"user_id": user_id}, 
        {"$set": {"last_daily": now}}
    )
    update_balance(user_id, daily_reward)
    new_bal = get_balance(user_id)
    
    embed = discord.Embed(title="🎁 Daily Reward Allowance", color=discord.Color.gold())
    embed.description = f"Successfully collected your daily grant reward of **${daily_reward}**! 💸"
    embed.set_footer(text=f"Your current balance is now: ${new_bal}")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="leaderboard", description="View the global server richest casino player rankings")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    top_users = list(balances_col.find().sort("balance", -1).limit(10))
    
    embed = discord.Embed(title="🏆 Casino Wealth Leaderboard", color=discord.Color.gold())
    description_lines = []
    
    medals = ["🥇", "🥈", "🥉"]
    for idx, u_data in enumerate(top_users):
        user_id = u_data["user_id"]
        bal = u_data["balance"]
        rank_label = medals[idx] if idx < 3 else f"`#{idx + 1}`"
        
        try:
            member = await interaction.guild.fetch_member(user_id)
            name_display = member.display_name
        except discord.NotFound:
            name_display = f"User({user_id})"
        except Exception:
            name_display = f"User({user_id})"
            
        description_lines.append(f"{rank_label} **{name_display}** — ${bal:,}")
        
    embed.description = "\n".join(description_lines) if description_lines else "No users recorded yet."
    embed.set_footer(text="Keep working and playing to climb to the peak!")
    await interaction.followup.send(embed=embed)


@client.tree.command(name="stats", description="Look up full win/loss records and system analytics for a user")
@app_commands.describe(user="The target member to view records for (Defaults to yourself)")
async def stats_command(interaction: discord.Interaction, user: discord.User = None):
    target_user = user or interaction.user
    user_data = get_user_data(target_user.id)
    
    wins = user_data.get("wins", 0)
    losses = user_data.get("losses", 0)
    total_games = wins + losses
    win_rate = (wins / total_games * 100) if total_games > 0 else 0.0
    
    embed = discord.Embed(title=f"📊 Analytics Summary - {target_user.display_name}", color=discord.Color.blue())
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Current Balance", value=f"${user_data.get('balance', 0):,}", inline=False)
    embed.add_field(name="Total Wins 🎉", value=f"{wins} match(es)", inline=True)
    embed.add_field(name="Total Losses ❌", value=f"{losses} match(es)", inline=True)
    embed.add_field(name="Win Rate Percentage", value=f"**{win_rate:.1f}%**", inline=True)
    embed.set_footer(text="Analytics tracking engine active 🛡️")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="shop", description="Open the premium interactive casino shop to purchase luxury vanity roles")
async def shop_command(interaction: discord.Interaction):
    embed = discord.Embed(title="💎 Luxury Casino Shop", color=discord.Color.purple())
    embed.description = "Upgrade your profile status by purchasing high-tier vanity roles! Select a role from the dropdown menu below to instantly finalize your purchase.\n\n"
    
    for item_id, info in SHOP_ITEMS.items():
        embed.add_field(
            name=info["name"], 
            value=f"Price: **${info['price']:,}**\n*{info['desc']}*", 
            inline=False
        )
        
    embed.set_footer(text="Roles are created automatically on purchase if missing.")
    view = ShopDropdownView()
    await interaction.response.send_message(embed=embed, view=view)


@client.tree.command(name="manage_money", description="Developer Administrative Command: Adjust or deduct user virtual balance")
@app_commands.describe(action="Financial action to take", user="Target member account", amount="The exact non-negative money size")
@app_commands.choices(action=[
    app_commands.Choice(name="Add Balance ➕", value="add"),
    app_commands.Choice(name="Deduct Balance ➖", value="deduct")
])
async def manage_money(interaction: discord.Interaction, action: str, user: discord.User, amount: int):
    if interaction.user.id != interaction.client.application.owner.id and interaction.user.id != 339082987114627072:
        await interaction.response.send_message("❌ Access Denied! This command is strictly reserved for the Bot Creator.", ephemeral=True)
        return
    
    if amount < 0:
        await interaction.response.send_message("❌ Error: Value must be a positive number.", ephemeral=True)
        return

    actual_amount = amount if action == "add" else -amount
    update_balance(user.id, actual_amount)
    new_bal = get_balance(user.id)
    
    embed = discord.Embed(title="⚙️ Executive Administrative Action", color=discord.Color.purple())
    embed.add_field(name="Action Executed", value="Balance Added ➕" if action == "add" else "Balance Deducted ➖", inline=True)
    embed.add_field(name="Target User Account", value=user.mention, inline=True)
    embed.add_field(name="Value Size Change", value=f"${amount:,}", inline=False)
    embed.add_field(name="New Resulting Balance", value=f"**${new_bal:,}**", inline=False)
    embed.set_footer(text="Action authorized by Core Bot Developer")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="borrow", description="Request a financial vault loan backed by your current server role credentials")
@app_commands.describe(amount="The size of the virtual funds cash you wish to borrow")
async def borrow_command(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    user = interaction.user
    guild = interaction.guild
    
    user_data = get_user_data(user.id)
    if user_data.get("loan_owed", 0) > 0:
        await interaction.followup.send(
            f"❌ Application Denied! You already have an outstanding active loan balance of **${user_data['loan_owed']:,}** which must be settled.",
            ephemeral=True
        )
        return
        
    if amount < 100:
        await interaction.followup.send("❌ Minimum required borrowing amount size is **$100**.", ephemeral=True)
        return
        
    max_loan, interest_rate, tier_name = get_user_loan_tier(user)
    if amount > max_loan:
        await interaction.followup.send(
            f"❌ Credit Limit Exceeded! Based on your tier (**{tier_name}**), your maximum absolute borrow limit is **${max_loan:,}**.",
            ephemeral=True
        )
        return

    debt_role = discord.utils.get(guild.roles, name="Debtor 🔴")
    if not debt_role:
        try:
            debt_role = await guild.create_role(
                name="Debtor 🔴", 
                color=discord.Color.red(), 
                reason="Automatic creation of system Debtor group"
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Configuration Error: Bot lacks `Manage Roles` authorization.", ephemeral=True)
            return

    try:
        await user.add_roles(debt_role)
    except discord.Forbidden:
        await interaction.followup.send("❌ Error applying Debtor tag restriction. Check hierarchy levels.", ephemeral=True)
        return

    total_debt = int(amount * (1 + interest_rate))
    balances_col.update_one({"user_id": user.id}, {"$set": {"loan_owed": total_debt}})
    update_balance(user.id, amount)
    
    embed = discord.Embed(title="🏦 Casino Vault Loan Approved!", color=discord.Color.orange())
    embed.description = f"Your requested cash allowance has been dispatched to your balance vault."
    embed.add_field(name="Principal Funded", value=f"${amount:,}", inline=True)
    embed.add_field(name="Interest Rate Applied", value=f"{interest_rate * 100:.0f}% ({tier_name})", inline=True)
    embed.add_field(name="Total Owed Repayment", value=f"**${total_debt:,}**", inline=False)
    embed.set_footer(text="Profile shop operations frozen until debt settlement via /pay_loan.")
    
    await interaction.followup.send(embed=embed, ephemeral=False)


@client.tree.command(name="pay_loan", description="Settle your outstanding system debt balances completely to unfreeze shop privileges")
async def pay_loan_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user = interaction.user
    guild = interaction.guild
    
    user_data = get_user_data(user.id)
    owed = user_data.get("loan_owed", 0)
    
    if owed <= 0:
        await interaction.followup.send("❌ Account Status: Your profile does not hold any active unpaid debt values.", ephemeral=True)
        return
        
    current_bal = get_balance(user.id)
    if current_bal < owed:
        await interaction.followup.send(
            f"❌ Settlement Failure! Your total debt is **${owed:,}**, but you only hold **${current_bal:,}** in your bank wallet.",
            ephemeral=True
        )
        return

    update_balance(user.id, -owed)
    balances_col.update_one({"user_id": user.id}, {"$set": {"loan_owed": 0}})
    
    debt_role = discord.utils.get(guild.roles, name="Debtor 🔴")
    if debt_role and debt_role in user.roles:
        try:
            await user.remove_roles(debt_role)
        except discord.Forbidden:
            pass

    new_bal = get_balance(user.id)
    embed = discord.Embed(title="🎉 Financial Debt Settled Completely!", color=discord.Color.green())
    embed.description = f"Thank you for fulfilling your casino loan obligations, {user.mention}."
    embed.add_field(name="Amount Paid", value=f"${owed:,}", inline=True)
    embed.add_field(name="Remaining Funds Wallet", value=f"${new_bal:,}", inline=True)
    embed.set_footer(text="Your account profiles limitations have been fully removed.")
    
    await interaction.followup.send(embed=embed, ephemeral=False)


@client.tree.command(name="blackjack", description="Join the official high-stakes casino table to play Blackjack")
@app_commands.describe(bet="The amount of virtual cash you want to wager")
async def blackjack(interaction: discord.Interaction, bet: int):
    await interaction.response.defer()
    user_id = interaction.user.id
    current_bal = get_balance(user_id)
    if current_bal <= 0:
        update_balance(user_id, 100)
        current_bal = 100
        await interaction.channel.send(f"⚠️ {interaction.user.mention}, you were completely bankrupt! The house granted you a **$100 safety fund**! 💸")
    if bet < 1:
        await interaction.followup.send("❌ The bet must be greater than 0.", ephemeral=True)
        return
    if bet > current_bal:
        await interaction.followup.send(f"❌ Rejected! You cannot bet **${bet}** when your current wallet balance is **${current_bal}**.", ephemeral=True)
        return
    suits = ['♠️', '♥️', '♦️', '♣️']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = [f"{rank}{suit}" for rank in ranks for suit in suits]
    random.shuffle(deck)
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    view = BlackjackView(user_id, deck, player_hand, dealer_hand, bet)
    player_score = view.calculate_score(player_hand)
    embed = discord.Embed(title="🃏 Blackjack Casino Table", color=discord.Color.blue())
    embed.add_field(name="Your Hand", value=f"{player_hand[0]}, {player_hand[1]} (Score: {player_score})", inline=False)
    embed.add_field(name="Dealer Hand", value=f"{dealer_hand[0]}, [Hidden]", inline=False)
    embed.set_footer(text=f"Wagered Bet: ${bet} | Wallet Account: ${current_bal}")
    await interaction.followup.send(embed=embed, view=view)


@client.tree.command(name="coinflip", description="Flip the official casino coin to double your active wager")
@app_commands.describe(bet="Money amount to bet", choice="Choose Heads or Tails")
@app_commands.choices(choice=[
    app_commands.Choice(name="Heads 🦅", value="heads"),
    app_commands.Choice(name="Tails 🪙", value="tails")
])
async def coinflip_cmd(interaction: discord.Interaction, bet: int, choice: str):
    await coinflip(interaction, bet, choice)


@client.tree.command(name="slots", description="Pull the handle on the classic diamond virtual slot machine")
@app_commands.describe(bet="Money amount to spin")
async def slots_cmd(interaction: discord.Interaction, bet: int):
    await slots(interaction, bet)


@client.tree.command(name="roulette", description="Wager your money on the high-fidelity European roulette wheel")
@app_commands.describe(bet="Money amount to bet", number="Specific raw number target from 0-36 (Optional, pays x35)")
async def roulette_cmd(interaction: discord.Interaction, bet: int, number: int = None):
    await roulette(interaction, bet, number)


@client.tree.command(name="horse_racing", description="Place an economic wager on the active server derby race")
@app_commands.describe(bet="Money amount to bet")
async def horse_racing_cmd(interaction: discord.Interaction, bet: int):
    await horse_racing(interaction, bet)


@client.tree.command(name="purge", description="Administrative command to delete a specified amount of channel text messages")
@app_commands.describe(amount="The exact number of text messages to erase")
async def purge(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ Security Exception: Missing administrative permissions.", ephemeral=True)
        return
    if amount < 1:
        await interaction.response.send_message("❌ Argument Error: Amount parameter must be strictly greater than 0.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Successfully purged {len(deleted)} message(s) from the history log.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Execution Error: {e}", ephemeral=True)


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
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()


async def main():
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN is missing from configuration variables.")
        return
    threading.Thread(target=run_health_server, daemon=True).start()
    print("Health check server started.")
    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
