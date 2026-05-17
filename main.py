import discord
from discord import app_commands
from discord.ext import commands
import random
import os
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from pymongo import MongoClient

# MongoDB Connection
MONGO_URI = "mongodb+srv://salehnakkar_db_user:QqUIaSkMryHShmbY@cluster0.j8uynar.mongodb.net/?appName=Cluster0"
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["blackjack_db"]
balances_col = db["user_balances"]

def get_balance(user_id):
    user_data = balances_col.find_one({"user_id": user_id})
    if not user_data:
        balances_col.insert_one({"user_id": user_id, "balance": 1000})
        return 1000
    return user_data["balance"]

def update_balance(user_id, amount):
    current_bal = get_balance(user_id)
    new_bal = max(0, current_bal + amount)
    balances_col.update_one({"user_id": user_id}, {"$set": {"balance": new_bal}}, upsert=True)
    return new_bal

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
                new_bal = get_balance(self.player_id)
                embed = discord.Embed(title="💥 Blackjack - You Busted!", color=discord.Color.red())
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
                await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)
            print(f"[Hit Error] {e}")

    @discord.ui.button(label="Double Down 💰", style=discord.ButtonStyle.secondary)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            current_bal = get_balance(self.player_id)
            if current_bal < self.bet * 2:
                await interaction.response.send_message("❌ You don't have enough balance to Double Down!", ephemeral=True)
                return

            self.stop()
            self.bet *= 2
            self.player_hand.append(self.deck.pop())
            player_score = self.calculate_score(self.player_hand)

            if player_score > 21:
                update_balance(self.player_id, -self.bet)
                new_bal = get_balance(self.player_id)
                embed = discord.Embed(title="💥 Blackjack - You Busted on Double!", color=discord.Color.red())
                embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
                embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)}", inline=False)
                embed.add_field(name="Result", value=f"Doubled down and lost! You lost **${self.bet}**! New balance: **${new_bal}**.", inline=False)
                await interaction.response.edit_message(embed=embed, view=None)
                return

            dealer_score = self.calculate_score(self.dealer_hand)
            while dealer_score < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_score = self.calculate_score(self.dealer_hand)

            if dealer_score > 21 or player_score > dealer_score:
                update_balance(self.player_id, self.bet)
                title = "You Win! 🎉"
                color = discord.Color.green()
                res_msg = f"Amazing! You won **${self.bet}**!"
            elif player_score < dealer_score:
                update_balance(self.player_id, -self.bet)
                title = "Dealer Wins! ❌"
                color = discord.Color.red()
                res_msg = f"Ouch! You lost **${self.bet}**!"
            else:
                title = "It's a Tie! 🤝"
                color = discord.Color.gold()
                res_msg = "Your bet was returned to you."

            new_bal = get_balance(self.player_id)
            embed = discord.Embed(title=f"🃏 Blackjack (Double Down) - {title}", color=color)
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)} (Score: {dealer_score})", inline=False)
            embed.add_field(name="Result", value=f"{res_msg} Your new balance is **${new_bal}**.", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)
            print(f"[Double Down Error] {e}")

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
                title = "You Win! 🎉"
                color = discord.Color.green()
                res_msg = f"Congratulations! You won **${self.bet}**!"
            elif player_score < dealer_score:
                update_balance(self.player_id, -self.bet)
                title = "Dealer Wins! ❌"
                color = discord.Color.red()
                res_msg = f"Bad luck! You lost **${self.bet}**!"
            else:
                title = "It's a Tie! 🤝"
                color = discord.Color.gold()
                res_msg = "Your bet was returned."

            new_bal = get_balance(self.player_id)
            embed = discord.Embed(title=f"🃏 Blackjack - {title}", color=color)
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)} (Score: {dealer_score})", inline=False)
            embed.add_field(name="Result", value=f"{res_msg} Your new balance is **${new_bal}**.", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)
            print(f"[Stand Error] {e}")


class BlackjackBot(commands.Bot):
    def __init__(self):
        bot_intents = discord.Intents.default()
        bot_intents.message_content = True
        bot_intents.members = True
        super().__init__(command_prefix="!", intents=bot_intents)

    async def setup_hook(self):
        print("Setup hook executed. Use /sync to register commands.")

    async def on_error(self, event_method, *args, **kwargs):
        import traceback
        print(f"[Bot Error in {event_method}]")
        traceback.print_exc()


client = BlackjackBot()


@client.event
async def on_ready():
    print(f"Logged in as {client.user.name} and ready for action!")


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"⏳ Slow down! You can use this command again in **{error.retry_after:.1f}** seconds.", ephemeral=True)
        return
    msg = f"Something went wrong: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"[Error Handler Failed] {e}")
    print(f"[App Command Error] {error}")


@client.tree.command(name="sync", description="Secret command to sync application commands globally")
async def sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await client.tree.sync()
        await interaction.followup.send(
            f"Synced {len(synced)} command(s) globally. May take a few minutes to appear.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"Failed to sync: {e}", ephemeral=True)


@client.tree.command(name="help", description="Show guidelines and rules on how to use the bot and play blackjack")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Blackjack Casino - Help Menu", color=discord.Color.gold())
    embed.add_field(name="🎮 Game Commands", value="`/blackjack [bet]` - Start a game with virtual money.\n`/balance` - Check your current bank account.\n`/work` - Get extra cash every 5 minutes.", inline=False)
    embed.add_field(name="🃏 Blackjack Rules", value="1. Get a hand total closer to **21** than the dealer without going over.\n2. **Hit**: Take another card.\n3. **Stand**: Keep your hand and end your turn.\n4. **Double Down**: Double your bet, take exactly one more card, and stand.", inline=False)
    embed.set_footer(text="Developed with passion 💻")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="balance", description="Check your current virtual money wallet")
async def balance(interaction: discord.Interaction):
    user_bal = get_balance(interaction.user.id)
    embed = discord.Embed(title="💰 Bank Account Statement", color=discord.Color.green())
    embed.add_field(name="Account Holder", value=f"{interaction.user.mention}", inline=True)
    embed.add_field(name="Net Balance", value=f"**${user_bal}**", inline=True)
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="work", description="Do some freelance programming work to earn fast cash")
@app_commands.checks.cooldown(1, 300)
async def work(interaction: discord.Interaction):
    jobs = [
        "You fixed a nasty database bug in Sal's custom bot and earned **${amount}**! 💻",
        "You worked as an assistant dealer in the server's VIP casino and got **${amount}** in tips! 🃏",
        "You optimized some heavy backend code for a premium client and made **${amount}**! 🚀",
        "You built a highly responsive landing page using modern framework styles and earned **${amount}**! 🎨",
        "You successfully closed an open issue on GitHub and received a bounty of **${amount}**! 🛡️"
    ]
    earned = random.randint(50, 150)
    job_message = random.choice(jobs).format(amount=earned)
    
    update_balance(interaction.user.id, earned)
    new_bal = get_balance(interaction.user.id)
    
    embed = discord.Embed(title="💼 Freelance Work Completed!", description=job_message, color=discord.Color.teal())
    embed.set_footer(text=f"Updated Total Balance: ${new_bal}")
    await interaction.response.send_message(embed=embed)


@client.tree.command(name="blackjack", description="Start a high-stakes game of Blackjack")
@app_commands.describe(bet="The amount of virtual money you want to bet")
async def blackjack(interaction: discord.Interaction, bet: int):
    await interaction.response.defer(ephemeral=False)
    user_id = interaction.user.id
    current_bal = get_balance(user_id)

    if current_bal <= 0:
        update_balance(user_id, 100)
        current_bal = 100
        await interaction.channel.send(f"⚠️ {interaction.user.mention}, you were completely broke! The casino granted you a **$100 rescue fund** to get you back in action! 💸")

    if bet < 1:
        await interaction.followup.send("❌ Please enter a valid bet amount greater than 0.", ephemeral=True)
        return

    if bet > current_bal:
        await interaction.followup.send(f"❌ Rejected! You cannot bet **${bet}** because your current balance is only **${current_bal}**.", ephemeral=True)
        return

    try:
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [f"{rank}{suit}" for rank in ranks for suit in suits]
        random.shuffle(deck)

        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        view = BlackjackView(user_id, deck, player_hand, dealer_hand, bet)
        player_score = view.calculate_score(player_hand)

        embed = discord.Embed(title="🃏 Blackjack Table", color=discord.Color.blue())
        embed.add_field(name="Your Hand", value=f"{player_hand[0]}, {player_hand[1]} (Score: {player_score})", inline=False)
        embed.add_field(name="Dealer Hand", value=f"{dealer_hand[0]}, [Hidden]", inline=False)
        embed.set_footer(text=f"Active Bet: ${bet} | Wallet: ${current_bal}")

        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        await interaction.followup.send(f"Failed to start game: {e}", ephemeral=True)
        print(f"[Blackjack Start Error] {e}")


@client.tree.command(name="purge", description="Delete a specified number of messages from the channel")
@app_commands.describe(amount="The number of messages to delete")
async def purge(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    if amount < 1:
        await interaction.response.send_message("Please provide a number greater than 0.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Successfully deleted {len(deleted)} message(s).", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Failed to purge: {e}", ephemeral=True)
        print(f"[Purge Error] {e}")


class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running alive!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()


async def main():
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_TOKEN variable is missing.")
        return

    threading.Thread(target=run_health_server, daemon=True).start()
    print("Health check server started.")

    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
