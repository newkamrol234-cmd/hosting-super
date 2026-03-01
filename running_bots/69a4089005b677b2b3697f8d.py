import telebot
import time
from telebot import apihelper

# ==========================================================
# 🛑 NETWORK TIMEOUT FIX (For Bangladesh/Restricted Networks)
# If your bot shows "ConnectTimeoutError" or "timed out", 
# uncomment the line below and add a free proxy address:
# ==========================================================
# apihelper.proxy = {'https': 'http://161.35.197.114:8080'}

bot = telebot.TeleBot('8265829664:AAE1i7sWTn7Se1gCtx-nfm0GeHw1Gzy0oUY')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Hello! I am alive and hosted on BotHostBD!")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, message.text)

print("Bot is starting...")
bot.infinity_polling()