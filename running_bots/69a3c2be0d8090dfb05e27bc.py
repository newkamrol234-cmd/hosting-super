import telebot

# Apnar deya bot token
TOKEN = '8334962578:AAF6NfC09EKBkfYLU2urGkjY-tf2lqCJoLc'

# Bot initialize kora hochhe
bot = telebot.TeleBot(TOKEN)

# /start command handle korar jonno handler
@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Apnar requested message-ti reply hishebe pathano hochhe
    bot.reply_to(message, "Ami ready, amar update cholse")

# Bot start korar command
if __name__ == "__main__":
    print("Bot cholche... /start diye check korun.")
    bot.infinity_polling()