"""Read-only HTTP API for bot data."""
import asyncio
import configparser
import logging
from pathlib import Path
from typing import List

import discord

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import pydantic

from .models import ApiApplication, DiscordMember, Game


api_logger = logging.getLogger('polybot.api')

server = FastAPI()
security = HTTPBasic()
client: discord.Client = None

config = configparser.ConfigParser()
config.read(str(Path(__file__).parent.parent / 'config.ini'))


class NewGame(pydantic.BaseModel):
    """A new game created via a request to the API."""

    game_name: str
    guild_id: int
    is_ranked: bool = False
    is_mobile: bool = True
    notes: str = ''
    sides_discord_ids: List[List[int]]


async def get_discord_member(guild_id: int, user_id: int) -> discord.Member:
    """Get a member from the cache if possible, else fetch."""
    guild = client.get_guild(guild_id)
    if not guild:
        raise HTTPException(
            status_code=404,
            detail=f'Discord guild not found by ID {guild_id}.'
        )
    member = guild.get_member(user_id)
    if member:
        return member
    try:
        member = await guild.fetch_member(user_id)
    except discord.HTTPException:
        raise HTTPException(
            status_code=404,
            detail=f'Discord member not found by ID {user_id}.'
        )
    return member


async def get_scopes(
        credentials: HTTPBasicCredentials = Depends(security)) -> List[str]:
    """Get the scopes the requester has access to."""
    app = ApiApplication.authenticate(
        credentials.username, credentials.password
    )
    if app:
        api_logger.info(f'Successful app authentication for user {credentials.username}')
        return app.scopes.split()

    api_logger.warning(f'Failed app authentication attempted with user {credentials.username}')
    raise HTTPException(
        status_code=401,
        detail='Incorrect app ID or token.',
        headers={'WWW-Authenticate': 'Basic'}
    )


@server.on_event('startup')
async def startup():
    """Connect the Discord client."""
    global client
    loop = asyncio.get_running_loop()
    client = discord.Client(loop=loop)
    api_logger.debug(f'starting up')
    loop.create_task(client.start(config['DEFAULT']['discord_key']))


@server.get('/users/{discord_id}')
async def get_user(
        discord_id: int, scopes: List[str] = Depends(get_scopes)) -> dict:
    """Get a user by discord ID."""
    if 'users:read' not in scopes:
        api_logger.warning(f'FAILED users:read call attempted on discord_id {discord_id}')
        raise HTTPException(
            status_code=403, detail='Not authorised for scope users:read.'
        )
    user = DiscordMember.get_or_none(DiscordMember.discord_id == discord_id)
    if user:
        api_logger.info(f'users:read call returned on discord_id {discord_id}')
        return user.as_json(include_games='games:read' in scopes)

    api_logger.debug(f'Failed (not found) users:read call attempted on discord_id {discord_id}')
    raise HTTPException(status_code=404, detail='User not found.')


@server.get('/games/{game_id}')
async def get_game(
        game_id: int, scopes: List[str] = Depends(get_scopes)) -> dict:
    """Get a game by ID."""
    if 'games:read' not in scopes:
        api_logger.warning(f'FAILED games:read call attempted on game_id {game_id}')
        raise HTTPException(
            status_code=403, detail='Not authorised for scope games:read.'
        )
    game = Game.get_or_none(Game.id == game_id)
    if game:
        api_logger.info(f'games:read call returned on game_id {game_id}')
        return game.as_json()

    api_logger.debug(f'Failed (not found) games:read call attempted on game_id {game_id}')
    raise HTTPException(status_code=404, detail='Game not found.')


@server.post('/game/new')
async def new_game(
        game: NewGame, scopes: List[str] = Depends(get_scopes)) -> dict:
    """Create a new game, adding the users to it."""

    api_logger.info(f'games-write attempted with game info: {game.game_name} / {game.guild_id} / {game.sides_discord_ids}')

    if 'games:new' not in scopes:
        api_logger.warning('FAILED games:write call (unauthorized)')
        raise HTTPException(
            status_code=403, detail='Not authorised for scope games:new.'
        )
    discord_user_sides = []
    for side in game.sides_discord_ids:
        discord_user_side = []
        for discord_id in side:
            user = await get_discord_member(game.guild_id, discord_id)
            discord_user_side.append(user)
        discord_user_sides.append(discord_user_side)
    try:
        db_game, _warnings = Game.create_game(
            discord_groups=discord_user_sides,
            guild_id=game.guild_id,
            name=game.game_name,
            is_ranked=game.is_ranked,
            is_mobile=game.is_mobile
        )
    except ValueError as e:
        api_logger.error(f'FAILED games:write call (creation error): {e}')
        raise HTTPException(status_code=400, detail=str(e))
    if game.notes:
        db_game.notes = game.notes
        db_game.save()

    api_logger.info(f'Game ID {db_game.id} created successfully')
    return {'game_id': db_game.id}
