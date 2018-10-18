import discord
import argparse
import traceback
from discord.ext import commands
from modules import models
from modules import initialize_data
import settings
import logging
from logging.handlers import RotatingFileHandler


handler = RotatingFileHandler(filename='discord.log', encoding='utf-8', maxBytes=500 * 1024, backupCount=1)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))

my_logger = logging.getLogger('polybot')
my_logger.setLevel(logging.DEBUG)
my_logger.addHandler(handler)  # root handler for app. module-specific loggers will inherit this

discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.INFO)

if (discord_logger.hasHandlers()):
    discord_logger.handlers.clear()

discord_logger.addHandler(handler)

logger_peewee = logging.getLogger('peewee')
logger_peewee.setLevel(logging.DEBUG)

if (logger_peewee.hasHandlers()):
    logger_peewee.handlers.clear()

logger_peewee.addHandler(handler)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--add_default_data', action='store_true')
    args = parser.parse_args()
    if args.add_default_data:
        initialize_data.initialize_data()
        exit(0)


def get_prefix(bot, message):
    # Guild-specific command prefixes
    if message.guild and message.guild.id in settings.config:
        # Current guild is allowed
        return commands.when_mentioned_or(settings.guild_setting(message.guild.id, 'command_prefix'))(bot, message)
    else:
        logging.error(f'Message received not from allowed guild. ID {message.guild.id}')
        return commands.when_mentioned_or(settings.get_setting('command_prefix'))(bot, message)


if __name__ == '__main__':

    main()

    bot = commands.Bot(command_prefix=get_prefix)
    # bot.remove_command('help')

    @bot.check
    async def globally_block_dms(ctx):
        # Should prevent bot from being able to be controlled via DM
        return ctx.guild is not None

    @bot.check
    async def is_user(ctx):
        if ctx.guild.id == settings.server_ids['main']:
            minimum_role = discord.utils.get(ctx.guild.roles, name='Rider')
            if ctx.author.top_role < minimum_role:
                await ctx.send('You must attain "Rider" role to use this bot')
                return False

        return True

    @bot.event
    async def on_command_error(ctx, exc):

        # This prevents any commands with local handlers being handled here in on_command_error.
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (commands.CommandNotFound, commands.UserInputError, commands.CheckFailure)

        # Anything in ignored will return and prevent anything happening.
        if isinstance(exc, ignored):
            logging.warn(f'Exception on ignored list raised in {ctx.command}. {exc}')
            return

        exception_str = ''.join(traceback.format_exception(etype=type(exc), value=exc, tb=exc.__traceback__))
        logging.critical(f'Ignoring exception in command {ctx.command}: {exc} {exception_str}', exc_info=True)
        print(f'Exception raised. {exc}\n{exception_str}')
        await ctx.send(f'Unhandled error: {exc}')

    @bot.after_invoke
    async def post_invoke_cleanup(ctx):
        models.db.close()

    initial_extensions = ['modules.games', 'modules.help', 'modules.game_import_export', 'modules.matchmaking']
    for extension in initial_extensions:
        bot.load_extension(extension)
        try:
            bot.load_extension(extension)
        except Exception as e:
            print(f'Failed to load extension {extension}: {e}')
            pass

    @bot.event
    async def on_ready():
        """http://discordpy.readthedocs.io/en/rewrite/api.html#discord.on_ready"""

        print(f'\n\nv2 Logged in as: {bot.user.name} - {bot.user.id}\nVersion: {discord.__version__}\n')
        print(f'Successfully logged in and booted...!')

    bot.run(settings.discord_key, bot=True, reconnect=True)
