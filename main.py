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
        card_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11}
        
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

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.blurple)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player_hand.append(self.deck.pop())
        player_score = self.calculate_score(self.player_hand)

        if player_score > 21:
            embed = discord.Embed(title="Blackjack - You Busted!", color=discord.Color.red())
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})")
            embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]}, [Hidden]")
            self.stop()
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            embed = discord.Embed(title="Blackjack Game", color=discord.Color.blue())
            embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})")
            embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]}, [Hidden]")
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.green)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        embed.add_field(name="Your Hand", value=f"{self.get_hand_string(self.player_hand)} (Score: {player_score})")
        embed.add_field(name="Dealer Hand", value=f"{self.get_hand_string(self.dealer_hand)} (Score: {dealer_score})")
        await interaction.response.edit_message(embed=embed, view=None)

class BlackjackBot(commands.Bot):
    def __init__(self):
        bot_intents = discord.Intents.default()
        bot_intents.message_content = True
        bot_intents.members = True
        super().__init__(command_prefix="!", intents=bot_intents)

    async def setup_hook(self):
        print("Setup hook executed.")

client = BlackjackBot()

@client.event
async def on_ready():
    print(f"Logged in as {client.user.name}")
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} command(s) successfully globally!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@client.tree.command(name="blackjack", description="Start a game of Blackjack")
async def blackjack(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    suits = ['♠️', '♥️', '♦️', '♣️']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = [f"{rank}{suit}" for rank in ranks for suit in suits]
    random.shuffle(deck)

    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    view = BlackjackView(interaction.user.id, deck, player_hand, dealer_hand)
    player_score = view.calculate_score(player_hand)

    embed = discord.Embed(title="Blackjack Game", color=discord.Color.blue())
    embed.add_field(name="Your Hand", value=f"{player_hand[0]}, {player_hand[1]} (Score: {player_score})")
    embed.add_field(name="Dealer Hand", value=f"{dealer_hand[0]}, [Hidden]")

    await interaction.followup.send(embed=embed, view=view)

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running alive!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    server.serve_forever()

async def main():
    TOKEN = os.getenv('DISCORD_TOKEN')
    if TOKEN:
        threading.Thread(target=run_health_server, daemon=True).start()
        await client.start(TOKEN)
    else:
        print("Error: DISCORD_TOKEN variable is missing.")

if __name__ == "__main__":
    asyncio.run(main())
