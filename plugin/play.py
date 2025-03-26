import os
import asyncio
from collections import deque
from asyncio import Lock
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls.types import MediaStream
from pytgcalls.types import StreamAudioEnded
from pytgcalls import PyTgCalls, filters as calls_filters, idle
from config import MAX_QUEUE_SIZE, restrict_multiple_chats
from main import bot, call_client
from .yt import YouTubeAPI


# Helper function to shorten song name
def shorten_song_name(songname: str) -> str:
    """Remove hashtags, pipes, dashes, and extra keywords from song name"""
    short_name = songname.split('#')[0].split('|')[0].split('-')[0].split(',')[0].split('.')[0].strip()
    return short_name

class MusicQueue:
    """Efficient music queue management using deque and locks with limit"""

    def __init__(self):
        self.queues = {}  # {chat_id: deque()}
        self.locks = {}  # {chat_id: Lock()}
        self.file_usage = {}  # {file_path: usage_count}

    async def add(self, chat_id: int, songname: str, file_path: str, url: str, media_type: str, quality: int, requester: str, user_id: int):
        """Add song to queue with size limit, requester, and user_id"""
        if chat_id not in self.queues:
            self.queues[chat_id] = deque(maxlen=self.MAX_QUEUE_SIZE)  # Set limit with maxlen
            self.locks[chat_id] = Lock()
        async with self.locks[chat_id]:
            if len(self.queues[chat_id]) >= self.MAX_QUEUE_SIZE:
                return -1  # Queue full
            self.queues[chat_id].append((songname, file_path, url, media_type, quality, requester, user_id))
            self.file_usage[file_path] = self.file_usage.get(file_path, 0) + 1
            return len(self.queues[chat_id])

    async def pop(self, chat_id: int) -> tuple:
        """Pop first song from queue"""
        if chat_id in self.queues:
            async with self.locks[chat_id]:
                if self.queues[chat_id]:
                    song = self.queues[chat_id].popleft()
                    self.file_usage[song[1]] -= 1
                    return song
        return None

    async def get_next(self, chat_id: int) -> tuple:
        """Get next song without removing it"""
        if chat_id in self.queues:
            async with self.locks[chat_id]:
                return self.queues[chat_id][0] if self.queues[chat_id] else None
        return None

    async def get_queue(self, chat_id: int) -> list:
        """Get the entire queue for a specific chat"""
        if chat_id in self.queues:
            async with self.locks[chat_id]:
                return list(self.queues[chat_id])  # Convert deque to list for easy access
        return []

    async def clear(self, chat_id: int):
        """Clear queue and update file usage"""
        if chat_id in self.queues:
            async with self.locks[chat_id]:
                for _, file_path, _, _, _, _, _ in self.queues[chat_id]:
                    self.file_usage[file_path] -= 1
                self.queues[chat_id].clear()
                del self.queues[chat_id]
                del self.locks[chat_id]

    async def cleanup_file(self, file_path: str):
        """Delete file if not in use with async retry mechanism"""
        if file_path in self.file_usage and self.file_usage[file_path] <= 0:
            max_retries = 5
            retry_delay = 0.5  # Reduced to 0.5 seconds
            for attempt in range(max_retries):
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        del self.file_usage[file_path]
                        print(f"Deleted file: {file_path}")
                    break
                except PermissionError as e:
                    if "[WinError 32]" in str(e):
                        print(f"File {file_path} in use, retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)  # Async delay
                    else:
                        print(f"Error deleting file {file_path}: {e}")
                        break
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")
                    break
            else:
                print(f"Failed to delete file {file_path} after {max_retries} attempts, skipping.")

    async def background_cleanup(self, file_path: str):
        """Background task to cleanup file"""
        asyncio.create_task(self.cleanup_file(file_path))  # Run cleanup in background

# Music Player Class
class MusicPlayer:
    """Main music player class"""
    def __init__(self):
        self.queue_manager = MusicQueue()
        self.youtube = YouTubeAPI()
        self.active_players = set()
        self.user_active_chats = {}  # {user_id: set(chat_ids)} to track all chats where user has songs

    async def is_valid_chat(self, chat_id: int) -> bool:
        """Check if the chat ID is valid"""
        try:
            await bot.get_chat(chat_id)
            return True
        except ValueError as e:
            if "Peer id invalid" in str(e):
                print(f"Invalid peer ID detected: {chat_id}")
                return False
            raise e

    async def play_song(self, chat_id: int, file_path: str, url: str, media_type: str):
        """Play song with optimized stream handling"""
        if not await self.is_valid_chat(chat_id):
            print(f"Skipping playback for invalid chat: {chat_id}")
            return False
        try:
            if chat_id not in self.active_players:
                await call_client.play(chat_id, MediaStream(file_path))
                self.active_players.add(chat_id)
            else:
                await call_client.play(chat_id, MediaStream(file_path))
            return True
        except ValueError as e:
            if "Peer id invalid" in str(e):
                print(f"Invalid peer ID {chat_id}, skipping playback.")
                return False
            print(f"Error playing song: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error playing song: {e}")
            return False

    async def end_call(self, chat_id: int):
        """End call and cleanup"""
        if chat_id in self.active_players:
            try:
                await call_client.leave_call(chat_id)
                self.active_players.remove(chat_id)
                # Remove all users associated with this chat
                for user_id in list(self.user_active_chats.keys()):
                    if chat_id in self.user_active_chats[user_id]:
                        self.user_active_chats[user_id].discard(chat_id)
                        if not self.user_active_chats[user_id]:
                            del self.user_active_chats[user_id]
                await self.queue_manager.clear(chat_id)
                if await self.is_valid_chat(chat_id):
                    await bot.send_message(chat_id, "Voice Chat Ended...")
            except ValueError as e:
                if "Peer id invalid" in str(e):
                    print(f"Invalid peer ID {chat_id}, cleaning up locally.")
                    self.active_players.remove(chat_id)
                    await self.queue_manager.clear(chat_id)
                else:
                    print(f"Error ending call: {e}")
            except Exception as e:
                print(f"Unexpected error ending call: {e}")

    async def skip_current(self, chat_id: int):
        """Skip current song and play next"""
        if not await self.is_valid_chat(chat_id):
            print(f"Skipping skip operation for invalid chat: {chat_id}")
            return None

        current_song = await self.queue_manager.pop(chat_id)
        if not current_song:
            await self.end_call(chat_id)
            return None

        # Cleanup in background to avoid delay
        await self.queue_manager.background_cleanup(current_song[1])

        # Remove user from active chats if no more songs in queue
        user_id = current_song[6]  # User ID
        if user_id in self.user_active_chats:
            queue = await self.queue_manager.get_queue(chat_id)
            if not any(song[6] == user_id for song in queue):  # If no songs from this user remain in queue
                self.user_active_chats[user_id].discard(chat_id)
                if not self.user_active_chats[user_id]:
                    del self.user_active_chats[user_id]

        next_song = await self.queue_manager.get_next(chat_id)
        if not next_song:
            await self.end_call(chat_id)
            return 0

        success = await self.play_song(chat_id, next_song[1], next_song[2], next_song[3])
        if not success:
            await self.end_call(chat_id)
            return 2

        return [next_song[0], next_song[2], next_song[5]]  # songname, url, requester

    async def pause(self, chat_id: int) -> bool:
        """Pause the current stream in the chat"""
        if chat_id not in self.active_players:
            return False
        try:
            await call_client.pause(chat_id)
            return True
        except Exception as e:
            print(f"Error pausing stream in chat {chat_id}: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        """Resume the current stream in the chat"""
        if chat_id not in self.active_players:
            return False
        try:
            await call_client.resume(chat_id)
            return True
        except Exception as e:
            print(f"Error resuming stream in chat {chat_id}: {e}")
            return False

# Initialize Player
player = MusicPlayer()

# Helper function to check if user is admin
async def is_admin(chat_id: int, user_id: int) -> bool:
    """Check if the user is an admin in the chat"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        print(f"Error checking admin status: {e}")
        return False

# Stream End Handler (Auto Play)
@call_client.on_update(calls_filters.stream_end)
async def stream_end_handler(_: PyTgCalls, update: StreamAudioEnded):
    chat_id = update.chat_id
    result = await player.skip_current(chat_id)

    if result == 0:
        if await player.is_valid_chat(chat_id):
            await bot.send_message(chat_id, "Queue is empty, leaving voice chat...")
    elif result == 2:
        if await player.is_valid_chat(chat_id):
            await bot.send_message(chat_id, "An error occurred, leaving voice chat...")
    elif result:
        if await player.is_valid_chat(chat_id):
            songname, url, requester = result  # Changed to unpack 3 values
            if url:
                track_details, vidid = await player.youtube.track(url)
                thumbnail = f"https://i.ytimg.com/vi/{vidid}/hqdefault.jpg"
                duration = track_details["duration_min"]
            else:
                thumbnail = "https://i.ytimg.com/vi/default.jpg"
                duration = "??"
            short_songname = shorten_song_name(songname)
            caption = (
                f"⏰ Vibe Time: {duration}\n"
                f"🎶 Vibe: [{short_songname}]({url})\n"
                f"👤 Proposed by: {requester}\n"
                f"👤 Auto Played"
            )
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=thumbnail,
                    caption=caption,
                    disable_notification=True
                )
            except Exception as e:
                print(f"Error sending photo: {e}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    disable_web_page_preview=False,
                    disable_notification=True
                )

# Play Command Handler
@Client.on_message(filters.command(['play']))
async def play_command(_, m: Message):
    """Handle play command"""
    chat_id = m.chat.id
    replied = m.reply_to_message
    requester = m.from_user.first_name if m.from_user else "Unknown"
    user_id = m.from_user.id if m.from_user else None

    try:
        sender = await m.reply("`Processing...`")
    except ValueError as e:
        if "Peer id invalid" in str(e):
            print(f"Cannot send message to invalid peer {chat_id}")
            return
        await m.reply("Invalid chat, try again!")
        return

    # Check if user has any active songs (playing or queued) in any chat
    # Only apply restriction if restrict_multiple_chats is True
    if (restrict_multiple_chats and 
        user_id in player.user_active_chats and 
        player.user_active_chats[user_id]):
        active_chats = ", ".join(str(cid) for cid in player.user_active_chats[user_id])
        await sender.edit(f"You can only play in one chat at a time! Your songs are currently playing or queued in chats: {active_chats}")
        return

    # Check queue limit first
    queue = await player.queue_manager.get_queue(chat_id)
    if len(queue) >= MAX_QUEUE_SIZE:
        await sender.edit(f"Queue is full (max {MAX_QUEUE_SIZE} songs)! Skip older songs first.")
        return

    if replied and (replied.audio or replied.voice):
        try:
            dl = await replied.download()
            songname = replied.audio.title if replied.audio and replied.audio.title else "Audio"
            url = None

            pos = await player.queue_manager.add(chat_id, songname, dl, url, "Audio", 0, requester, user_id)
            if pos == 1:
                if await player.play_song(chat_id, dl, url, "Audio"):
                    short_songname = shorten_song_name(songname)
                    caption = (
                        f"Duration ??\n"
                        f"🎶 Vibe [{short_songname}]({url if url else 'No Link'}) | `Audio`\n"
                        f"👤 Proposed by: {requester}"
                    )
                    # Add user to active chats
                    if user_id:
                        if user_id not in player.user_active_chats:
                            player.user_active_chats[user_id] = set()
                        player.user_active_chats[user_id].add(chat_id)
                    await sender.edit(caption)
                else:
                    await sender.edit("**Error ⚠️**\n`Playback failed to start, try again!`")
            else:
                short_songname = shorten_song_name(songname)
                # Add user to active chats even for queued songs
                if user_id:
                    if user_id not in player.user_active_chats:
                        player.user_active_chats[user_id] = set()
                    player.user_active_chats[user_id].add(chat_id)
                await sender.edit(
                    f"**Queued at #{pos}**\n"
                    f"🎶 Vibe: [{short_songname}]({url})\n"
                    f"👤 Proposed by: {requester}\n"
                )
        except Exception as e:
            await sender.edit(f"**Error ⚠️**\n`Error processing audio: {str(e)}`")
            print(f"Error in replied audio: {e}")

    elif len(m.command) < 2:
        await sender.edit("Reply with an audio file or provide a search query!")
    else:
        query = m.text.split(None, 1)[1]
        try:
            search = await player.youtube.track(query)
            if not search:
                await sender.edit("No results found!")
                return

            track_details, vidid = search
            songname = track_details["title"]
            url = track_details["link"]
            thumbnail = f"https://i.ytimg.com/vi/{vidid}/hqdefault.jpg"
            duration = track_details.get("duration_min", "??")

            audio_file, _ = await player.youtube.download(url)
            if not audio_file:
                await sender.edit("**Download Error ⚠️**\n`Song download failed!`")
                return

            pos = await player.queue_manager.add(chat_id, songname, audio_file, url, "Audio", 0, requester, user_id)
            if pos == 1:
                if await player.play_song(chat_id, audio_file, url, "Audio"):
                    short_songname = shorten_song_name(songname)
                    caption = (
                        f"⏰ Vibe Time: {duration}\n"
                        f"🎶 Vibe: [{short_songname}]({url})\n"
                        f"👤 Proposed by: {requester}\n"
                    )
                    # Add user to active chats
                    if user_id:
                        if user_id not in player.user_active_chats:
                            player.user_active_chats[user_id] = set()
                        player.user_active_chats[user_id].add(chat_id)
                    await sender.delete()
                    try:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=thumbnail,
                            caption=caption,
                            disable_notification=True
                        )
                    except Exception as e:
                        print(f"Error sending photo: {e}")
                        await bot.send_message(
                            chat_id=chat_id,
                            text=caption,
                            disable_web_page_preview=False,
                            disable_notification=True
                        )
                else:
                    await sender.edit("**Error ⚠️**\n`Playback failed to start, try again!`")
            else:
                short_songname = shorten_song_name(songname)
                # Add user to active chats even for queued songs
                if user_id:
                    if user_id not in player.user_active_chats:
                        player.user_active_chats[user_id] = set()
                    player.user_active_chats[user_id].add(chat_id)
                await sender.edit(
                    f"**Queued at #{pos}**\n"
                    f"🎶 Vibe: [{short_songname}]({url})\n"
                    f"👤 Proposed by: {requester}\n"
                )
        except Exception as e:
            await sender.edit(f"**Error ⚠️**\n`Error processing query: {str(e)}`")
            print(f"Error in query: {e}")

# Skip Command Handler
@Client.on_message(filters.command(['skip']))
async def skip_command(_, m: Message):
    """Handle skip command"""
    chat_id = m.chat.id
    skipper = m.from_user.first_name if m.from_user else "Unknown"  # Name of the skipper
    result = await player.skip_current(chat_id)

    if result == 0:
        await m.reply("Queue is empty, voice chat ended...")
    elif result == 2:
        await m.reply("An error occurred, ending voice chat...")
    elif result:
        songname, url, requester = result  # Extract only songname, url, requester
        queue = await player.queue_manager.get_queue(chat_id)  # Get current queue
        total_songs = len(queue)  # Total songs remaining in queue
        if url:
            track_details, vidid = await player.youtube.track(url)
            thumbnail = f"https://i.ytimg.com/vi/{vidid}/hqdefault.jpg"
            duration = track_details["duration_min"]
        else:
            thumbnail = "https://i.ytimg.com/vi/default.jpg"
            duration = "----"
        short_songname = shorten_song_name(songname)
        caption = (
            f"⏰ Vibe Time: {duration}\n"
            f"🎶 Now Playing: `\"{short_songname}\" proposed by \"{requester}\"`\n"  # Song and requester in quotes
            f"👤 Skipped by: {skipper}\n"
            f"Total Songs in Queue: {total_songs}"  # Total songs outside quotes
        )
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=thumbnail,
                caption=caption,
                disable_notification=True
            )
        except Exception as e:
            print(f"Error sending photo: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                disable_web_page_preview=False,
                disable_notification=True
            )

# Queue Command Handler
@Client.on_message(filters.command(['queue']))
async def queue_command(_, m: Message):
    """Handle queue command to display current queue"""
    chat_id = m.chat.id
    if not await player.is_valid_chat(chat_id):
        await m.reply("Cannot access this chat!")
        return

    queue = await player.queue_manager.get_queue(chat_id)

    if not queue:
        await m.reply("Queue is empty!")
        return

    queue_text = "Current Queue:\n"
    for i, (songname, _, url, _, _, requester, _) in enumerate(queue, 1):
        short_songname = shorten_song_name(songname)
        queue_text += f"{i}. `\"{short_songname}\" proposed by \"{requester}\"` - [Link]({url})\n"

    await m.reply(queue_text, disable_web_page_preview=True)

# Pause Command Handler (Admin Only)
@Client.on_message(filters.command(['pause']))
async def pause_command(_, m: Message):
    """Handle pause command (admin only)"""
    chat_id = m.chat.id
    user_id = m.from_user.id if m.from_user else None

    if not await player.is_valid_chat(chat_id):
        await m.reply("Cannot access this chat!")
        return

    if not user_id:
        await m.reply("Cannot identify user!")
        return

    if not await is_admin(chat_id, user_id):
        await m.reply("❌ Only chat admins can use this command!")
        return

    if chat_id not in player.active_players:
        await m.reply("No active playback in this chat!")
        return

    if await player.pause(chat_id):
        await m.reply("⏸ Playback paused!")
    else:
        await m.reply("❌ Failed to pause playback!")

# Resume Command Handler (Admin Only)
@Client.on_message(filters.command(['resume']))
async def resume_command(_, m: Message):
    """Handle resume command (admin only)"""
    chat_id = m.chat.id
    user_id = m.from_user.id if m.from_user else None

    if not await player.is_valid_chat(chat_id):
        await m.reply("Cannot access this chat!")
        return

    if not user_id:
        await m.reply("Cannot identify user!")
        return

    if not await is_admin(chat_id, user_id):
        await m.reply("❌ Only chat admins can use this command!")
        return

    if chat_id not in player.active_players:
        await m.reply("No active playback in this chat!")
        return

    if await player.resume(chat_id):
        await m.reply("▶️ Playback resumed!")
    else:
        await m.reply("❌ Failed to resume playback!")

# End Command Handler (Admin Only)
@Client.on_message(filters.command(['end']))
async def end_command(_, m: Message):
    """Handle end command to stop playback and clear queue (admin only)"""
    chat_id = m.chat.id
    user_id = m.from_user.id if m.from_user else None

    if not await player.is_valid_chat(chat_id):
        await m.reply("Cannot access this chat!")
        return

    if not user_id:
        await m.reply("Cannot identify user!")
        return

    if not await is_admin(chat_id, user_id):
        await m.reply("❌ Only chat admins can use this command!")
        return

    if chat_id not in player.active_players:
        await m.reply("No active playback in this chat!")
        return

    await player.end_call(chat_id)
    await m.reply("⏹ Playback stopped and queue cleared!")

# Toggle Multiple Chat Restriction Command
@Client.on_message(filters.command(['togglemulti']))
async def toggle_multi_command(_, m: Message):
    """Toggle multiple chat restriction"""
    global restrict_multiple_chats  # Use global to modify the imported variable
    restrict_multiple_chats = not restrict_multiple_chats
    status = "enabled" if restrict_multiple_chats else "disabled"
    await m.reply(f"Multiple chat restriction is now {status}")