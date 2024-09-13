#################################################################################

# Brandmeister Monitor
# Develped by: Michael Clemens, DK1MI
# Refactored by: Jeff Lehman, N8ACL
# Current Version: 1.2
# Original Script: https://codeberg.org/mclemens/pyBMNotify
# Refactored Script: https://github.com/n8acl/bm_monitor

# Questions? Comments? Suggestions? Contact me one of the following ways:
# E-mail: n8acl@qsl.net
# Discord: Ravendos
# Mastodon: @n8acl@mastodon.radio
# Website: https://www.qsl.net/n8acl

###################   DO NOT CHANGE BELOW   #########################

#############################
##### Import Libraries and configs
import config as cfg
import json
import datetime as dt
import time
import socketio
import http.client, urllib
import threading
from time import sleep


# libary only needed if Discord is configured in config.py
if cfg.discord:
    from discord_webhook import DiscordWebhook, DiscordEmbed

# libraries only needed if Telegram is configured in config.py
# if cfg.telegram:
#     import telebot 
#     from telethon.sync import TelegramClient 
#     from telethon.tl.types import InputPeerUser, InputPeerChannel 
#     from telethon import TelegramClient, sync, events 

# libraries only needed if dapnet or telegram is configured in config.py
if cfg.dapnet or cfg.telegram:
    import requests
    from requests.auth import HTTPBasicAuth

#############################
##### Define Variables

sio = socketio.Client()

last_TG_activity = {}
last_OM_activity = {}

discord_hook={}

DMRCallSign = {}

def dmrids():
    with open("dmrid.dat") as f:
        if cfg.verbose:
            print('Loading dmrid.dat')
        for line in f:
            (key, val, junk) = line.split(';')
            DMRCallSign[int(key)] = val
    threading.Timer(21600, dmrids).start()

#############################
##### Define Functions

# Send push notification via Pushover. Disabled if not configured in config.py
def push_pushover(msg):
    conn = http.client.HTTPSConnection("api.pushover.net:443")
    conn.request("POST", "/1/messages.json",
        urllib.parse.urlencode({
        "token": cfg.pushover_token,
        "user": cfg.pushover_user,
        "message": msg,
        }), { "Content-type": "application/x-www-form-urlencoded" })
    conn.getresponse()

# Send push notification via Telegram. Disabled if not configured in config.py
# def push_telegram(msg):
#     client = TelegramClient('bm_bot', cfg.telegram_api_id, cfg.telegram_api_hash) 
#     client.connect() 
#     if not client.is_user_authorized(): 
#         client.send_code_request(cfg.phone) 
#         client.sign_in(cfg.phone, input('Please enter the code which has been sent to your phone: ')) 
#     try: 
#         receiver = InputPeerUser('user_id', 'user_hash') 
#         client.send_message(cfg.telegram_username, msg) 
#     except Exception as e: 
#         print(e); 
#     client.disconnect() 

def push_telegram(msg):
    telegram_url = "https://api.telegram.org/bot" + cfg.telegram_api_hash + "/sendmessage"

    response = requests.post(
        telegram_url, json = msg, # data=json.dumps(msg),
        headers={'Content-Type': 'application/json'}
    )


# send pager notification via DAPNET. Disabled if not configured in config.py
def push_dapnet(msg):
    dapnet_json = json.dumps({"text": msg, "callSignNames": cfg.dapnet_callsigns, "transmitterGroupNames": [cfg.dapnet_txgroup], "emergency": True})
    response = requests.post(cfg.dapnet_url, data=dapnet_json, auth=HTTPBasicAuth(cfg.dapnet_user,cfg.dapnet_pass)) 

# Send notification to Discord Channel via webhook
def push_discord(wh_url, embed, session):
    discord_hook[session] = DiscordWebhook(url=wh_url)
    discord_hook[session].add_embed(embed)
    response = discord_hook[session].execute()

def update_discord(wh_url, msg, session):
    return
    discord_hook[session].content=msg   
    response = discord_hook[session].edit()

def end_discord(wh_url, embed, session, duration):
    if duration > 0 and duration < 10:
        if cfg.verbose:
            print('waiting for ' + str(10 - duration) + ' seconds')
        sleep(10-duration)
    if session in discord_hook:
        discord_hook[session].remove_embeds()
        discord_hook[session].add_embed(embed)
        response = discord_hook[session].edit()
        del discord_hook[session]


def construct_message(c,inprogress):
    tg = c["DestinationID"]
    out = ""
    duration = c["Stop"] - c["Start"]
    # construct text message from various transmission properties
    out += '[' + c["SourceCall"] + '](<https://qrz.com/db/' +  c["SourceCall"] + '>) (' + c["SourceName"] + ')'
    if not inprogress:
        out += ' was'
    out += ' active on '
    out += str(tg) 
    if c["DestinationName"] != '':
        out += ' (' + c["DestinationName"] + ')'
    out += ' at '
    # convert unix time stamp to human readable format
    time = dt.datetime.utcfromtimestamp(c["Start"]).strftime("%Y/%m/%d %H:%M")
    out += time + ' UTC'
    if  not inprogress:
        if duration < 2:
            strduration='kerchunk!'
        else:
            strduration=str(duration) + ' seconds'
        out += ' (' + strduration + ')'
    # finally return the text message
    return out

def construct_embed(c,inprogress):
    duration = c["Stop"] - c["Start"]
    embed=DiscordEmbed(title=c["SourceCall"], url='https://qrz.com/db/' +  c["SourceCall"])
    embed.set_color(color='ff0000')    
    embed.add_embed_field(name="Destination", value=c["DestinationID"], inline=False)                     

    # construct text message from various transmission properties
    if not inprogress:
        embed.set_color(color='00a8fc')    
    if c["DestinationName"] != '':
        embed.add_embed_field(name="TG Name", value=c["DestinationName"], inline=False)                     
    # convert unix time stamp to human readable format
    time = dt.datetime.utcfromtimestamp(c["Start"]).strftime("%Y/%m/%d %H:%M")
    embed.add_embed_field(name="Time", value=time + ' UTC', inline=False)                     

    if  not inprogress:
        if duration < 2:
            strduration='kerchunk!'
        else:
            strduration=str(duration) + ' seconds'
        embed.add_embed_field(name="Duration", value=strduration, inline=False)
    else:
        embed.add_embed_field(name="Duration", value='Talking now', inline=False)                   
    return embed
#############################
##### Define SocketIO Callback Functions

@sio.event
def connect():
    print('connection established')

@sio.on("mqtt")
def on_mqtt(data):

    call = json.loads(data['payload'])

    # if call["DestinationID"] in cfg.talkgroups:
    #     print(call)
    session=call["SessionID"]
    tg = call["DestinationID"]
    callsign = call["SourceCall"]
    sourceid=call["SourceID"]
    start_time = call["Start"]
    stop_time = call["Stop"]
    event = call["Event"]
    notify = False
    now = int(time.time())

    if callsign == '' and sourceid in DMRCallSign:
        callsign=DMRCallSign[sourceid]
        call["SourceCall"]=callsign

    if cfg.verbose and callsign in cfg.noisy_calls:
        print("ignored noisy ham " + callsign)

    elif callsign != '':
        # check if callsign is monitored, the transmission has already been finished
        # and the person was inactive for n seconds
        if callsign in cfg.callsigns:
            if callsign not in last_OM_activity:
                last_OM_activity[callsign] = 9999999
            inactivity = now - last_OM_activity[callsign]
            if callsign not in last_OM_activity or inactivity >= cfg.min_silence:
                # If the activity has happened in a monitored TG, remember the transmission start time stamp
                if tg in cfg.talkgroups and stop_time > 0:
                    last_TG_activity[tg] = now
                # remember the transmission time stamp of this particular DMR user
                last_OM_activity[callsign] = now
                notify = True
        # Continue if the talkgroup is monitored, the transmission has been
        # finished and there was no activity during the last n seconds in this talkgroup
        elif tg in cfg.talkgroups:# and callsign not in cfg.noisy_calls:
            notify=True
            if event == 'Session-Stop' and not session in discord_hook:
                notify=False
                if cfg.verbose:
                    print("Got session-stop for unknown session, not notifying")
            if event == 'Session-Stop':
                inprogress=False
            else:
                inprogress=True

        if notify:
            print(event)
            print(session)
            if cfg.pushover:
                push_pushover(construct_message(call))
            if cfg.telegram:
                push_telegram({'text': construct_message(call), 'chat_id': cfg.telegram_api_id, "disable_notification": True})
            if cfg.dapnet:
                push_dapnet(construct_message(call))
            if cfg.discord:
                if session in discord_hook:
                    if inprogress:
                        update_discord(cfg.discord_wh_url, construct_embed(call, inprogress), session)
                    else:
                        end_discord(cfg.discord_wh_url, construct_embed(call, inprogress), session, call["Stop"] - call["Start"])

                else:
                    push_discord(cfg.discord_wh_url, construct_embed(call, inprogress), session )

            if cfg.verbose:
                print(construct_message(call,inprogress))

@sio.event
def disconnect():
    print('disconnected from server')

#############################
##### Main Program
dmrids()
sio.connect(url='https://api.brandmeister.network', socketio_path="/lh/socket.io", transports="websocket")
sio.wait()
