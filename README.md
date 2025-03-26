# MusicBot

MusicBot is a Telegram bot designed to stream music in group voice chats using YouTube. It supports playing songs from YouTube URLs or search queries, queuing multiple tracks, skipping, pausing, resuming, and ending playback with admin-only controls for certain commands. Built with Pyrogram for Telegram interactions and PyTgCalls for voice chat functionality, it offers a seamless music experience.

## Features

- Play music from YouTube URLs or search queries using `/play <query>`.
- Queue songs with a configurable maximum limit.
- Skip to the next song with `/skip`.
- Display the current queue with `/queue`.
- Pause playback with `/pause` (admin-only).
- Resume playback with `/resume` (admin-only).
- End playback and clear the queue with `/end` (admin-only).
- Toggle multi-chat restriction with `/togglemulti`.

## Prerequisites

- Python 3.8 or higher
- FFmpeg installed on your system
- Telegram API credentials (API_ID, API_HASH, STRING_SESSION)
- A cookies file for YouTube (optional, for restricted content)

## Variables
- config.py
- API_ID: Telegram API ID (string, required).
- API_HASH: Telegram API Hash (string, required).
- STRING_SESSION: Pyrogram session string (string, required).
- MAX_QUEUE_SIZE: Maximum number of songs in the queue (int, default: 10).
- RESTRICT_MULTIPLE_CHATS: Restrict users to one chat at a time (bool, default: True).

## Functions
- MusicQueue Class
- add(chat_id, songname, file_path, url, media_type, quality, requester, user_id): Adds a song to the queue with a size limit.
- pop(chat_id): Removes and returns the first song in the queue.
- get_next(chat_id): Peeks at the next song without removing it.
- get_queue(chat_id): Returns the full queue as a list.
- clear(chat_id): Clears the queue and updates file usage.
- cleanup_file(file_path): Deletes a file if no longer in use.
- background_cleanup(file_path): Runs file cleanup asynchronously.
- MusicPlayer Class
- is_valid_chat(chat_id): Validates a chat ID.
- play_song(chat_id, file_path, url, media_type): Plays a song in the voice chat.
- end_call(chat_id): Ends the call, clears queue, and cleans up.
- skip_current(chat_id): Skips the current song and plays the next.
- pause(chat_id): Pauses the current playback (admin-only).
- resume(chat_id): Resumes paused playback (admin-only).
- YouTubeAPI Class
- track(link, videoid=None): Retrieves track details (title, duration, thumbnail, etc.).
- download(link, mystic=None, video=None, videoid=None, songaudio=None, songvideo=None, format_id=None, title=None): Downloads YouTube audio/video with fallback support.
- exists(link, videoid=None): Checks if a URL is a valid YouTube link.
- details(link, videoid=None): Gets detailed info about a video.
- title(link, videoid=None): Extracts the video title.
- duration(link, videoid=None): Extracts the video duration.
- thumbnail(link, videoid=None): Extracts the video thumbnail URL.
- Helper Functions
- shorten_song_name(songname): Trims song names for display.
- is_admin(chat_id, user_id): Checks if a user is an admin in a chat.
- time_to_seconds(time): Converts time string to seconds.
- cookiefile(): Retrieves the path to the cookies file.
- shell_cmd(cmd): Executes a shell command asynchronously.


## Credits
- [Pyrogram](https://github.com/pyrogram): For Telegram API integration.
- [PyTgCalls](https://github.com/pytgcalls/pytgcalls.git): For voice chat streaming.
- [okkhex](https://github.com/okkhex) - Developer and maintainer of MusicBot.