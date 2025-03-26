import os
from pyrogram import Client, idle
from pytgcalls import PyTgCalls
from pytgcalls import idle as pyidle

from config import API_ID,API_HASH,STRING_SESSION

# pyrogram client configuration
bot = Client("musicbot",
             api_id=API_ID,
             api_hash=API_HASH,
             session_string=STRING_SESSION,
             plugins=dict(root="plugin"))

#PyTgCalls configuration
call_client = PyTgCalls(bot)

bot.start()
print("pyrogram client Started")
call_client.start()
print("pytgcalls Client Started")
pyidle()
idle()
