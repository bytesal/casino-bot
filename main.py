import discord
from discord import app_commands
from discord.ext import commands
import random
import os
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


class BlackjackView(discord.ui.View):
    def __init__(self, player_id, deck, player_hand, dealer_hand):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.deck = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand

    def calculate_score(self, hand):
        score = 0
        aces = 0
        card_values = {
            '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
            '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11
        }
        for card in hand:
            score += card_values[card[:-1]]
            if card[:-1] == 'A':
                aces += 1
        while score > 21 and aces:
            score -= 10
            aces -= 1
        return score

    def get_hand_string(self, hand):
        return ", ".join(hand)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This game is not for you!", ephemeral=True)
            return False
        return True

    # Called when the view times out so the buttons don't stay active forever
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.blurple)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.player_hand.append(self.deck.pop())
            player_score = self.calculate_score(self.player_hand)

            if player_score > 21:
                embed = discord.Embed(title="Blackjack - You Busted!", color=discord.Color.red())
                embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
                embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]}, [Hidden]", inline=False)
                self.stop()
                await interaction.response.edit_message(embed=embed, view=None)
            else:
                embed = discord.Embed(title="Blackjack Game", color=discord.Color.blue())
                embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
                embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]}, [Hidden]", inline=False)
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            # Prevent the interaction from freezing if something goes wrong
            if not interaction.response.is_done():
                await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)
            print(f"[Hit Error] {e}")

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.green)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.stop()
            player_score = self.calculate_score(self.player_hand)
            dealer_score = self.calculate_score(self.dealer_hand)

            while dealer_score < 17:
                self.dealer_hand.append(self.deck.pop())
                dealer_score = self.calculate_score(self.dealer_hand)

            if dealer_score > 21 or player_score > dealer_score:
                title = "You Win! 🎉"
                color = discord.Color.green()
            elif player_score < dealer_score:
                title = "Dealer Wins! ❌"
                color = discord.Color.red()
            else:
                title = "It's a Tie! 🤝"
                color = discord.Color.gold()

            embed = discord.Embed(title=f"Blackjack - {title}", color=color)
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})", inline=False)
            embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)} (Score: {dealer_score})", inline=False)
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
        # Do NOT call tree.sync() here — it causes the bot to hang on startup
        # Use the /sync slash command manually when you need to push new commands
        print("Setup hook executed. Use /sync to register commands.")

    async def on_error(self, event_method, *args, **kwargs):
        # Global error handler so uncaught exceptions don't silently kill interactions
        import traceback
        print(f"[Bot Error in {event_method}]")
        traceback.print_exc()


client = BlackjackBot()


@client.event
async def on_ready():
    print(f"Logged in as {client.user.name} and ready for action!")


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Catches slash command errors globally so interactions never freeze
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


@client.tree.command(name="blackjack", description="Start a game of Blackjack")
async def blackjack(interaction: discord.Interaction):
    # Defer FIRST — gives us 15 minutes to reply and prevents "thinking" freeze
    await interaction.response.defer(ephemeral=False)

    try:
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [f"{rank}{suit}" for rank in ranks for suit in suits]
        random.shuffle(deck)

        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        view = BlackjackView(interaction.user.id, deck, player_hand, dealer_hand)
        player_score = view.calculate_score(player_hand)

        embed = discord.Embed(title="Blackjack Game", color=discord.Color.blue())
        embed.add_field(name="Your Hand", value=f"{player_hand[0]}, {player_hand[1]} (Score: {player_score})", inline=False)
        embed.add_field(name="Dealer Hand", value=f"{dealer_hand[0]}, [Hidden]", inline=False)

        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        # followup works here because we already deferred above
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

    # Silence the default request logging to keep the console clean
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

    # Start health server BEFORE the bot so it's up when the host checks
    threading.Thread(target=run_health_server, daemon=True).start()
    print("Health check server started.")

    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
