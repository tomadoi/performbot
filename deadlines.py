from slackbot.bot import listen_to, respond_to
import re
import dateutil.parser
import dateparser
import datetime
import json
from db import Deadline
import db

#session = db.Session()

@respond_to(r'(.*\S(?<!is))(\s+is)?\s+((on|in)\s+\S.*)', re.IGNORECASE)
def set_deadline(message, item, _, datestr, __):
    session = db.Session()
    parsed = dateparser.parse(datestr)
    if not parsed:
        message.reply("Can't parse date {}".format(datestr))
        session.close()
        return  # can't parse so ignore the date
    date = parsed.date()
    today = datetime.date.today()
    if date < today:
        if date.year == today.year:
            date = date.replace(year=date.year + 1)
        else:
            session.close()
            return  # too far in the past
    d = Deadline(date=date, item=item)
    try:
        session.add(d)
        session.commit() 
        datestr = date.strftime("%b %d, %Y")
        message.reply("Set deadline: {} is on {}".format(item, datestr))
    except:
        session.rollback()
        message.reply("Encountered error when adding deadline")
    finally:
        session.close()

@listen_to(r'^deadlines?', re.IGNORECASE)
@respond_to(r'deadlines?', re.IGNORECASE)
def list_deadlines(message):
    attachments = []
    session = db.Session()
    error = False
    try:
        for deadline in session.query(Deadline).order_by(Deadline.date):
            days = (deadline.date - datetime.date.today()).days
            if days < 0:
                continue
            attach = {"mrkdwn_in": ["text"]}
            if days > 1:
                attach["text"] = "{} days until {}".format(days, deadline.item)
            elif days == 1:
                attach["text"] = "*{} tomorrow!*".format(deadline.item)
            else:
                attach["text"] = "*{} TODAY!*".format(deadline.item)
                attach["color"] = "#ff0000"
            if days < 7 and days > 0:
                attach["color"] = "#ffff00"
            attachments.append(attach)
    except:
        session.rollback()
        message.reply("exception on query")
        error = True
        raise
    finally:
        if not error:
            if attachments:
                message.send_webapi('', json.dumps(attachments))
            else:
                message.reply("No deadlines!")
        session.close()


@respond_to('forget(\s+about)?\s+(.*)', re.IGNORECASE)
def forget_deadline(message, _, match):
    session = db.Session()
    if '%' not in match:
        match += '%'   # prefix search
    try:
        q = list(session.query(Deadline).filter(Deadline.item.like(match)))
        if not q:
            message.reply("No matching deadlines")
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(x.item
                                                                       for x in q))
        else:
            message.reply("Deleting deadline {}".format(q[0].item))
            session.delete(q[0])
            session.commit()
    except:
        session.rollback()
    finally:
        session.close()

@respond_to('help?', re.IGNORECASE)
def show_help(message):
    attachments = []
    attach = {"mrkdwn_in": ["text"]}
    attach["text"] = "I can only understand the following language:\r\
        \r\
        - To add conference to the databse: conference is on date \r\
        - To remove conference from databse: forget about conference \r\
        - To check current deadlines: deadlines? \r\
        \r\
        *Note*: I am always listening for the word deadlines but you have to tag me for adding/removing. \r\
        \r\
        *Another note*: I am dumb and cannot handle duplicates, so please don't add them. Happy deadlines fellow human!"
    attachments.append(attach)
    message.send_webapi('', json.dumps(attachments))    

@respond_to('rollback?', re.IGNORECASE)
def rollback_db(message):
    attachments = []
    session = db.Session()
    session.rollback()
    attach = {"mrkdwn_in": ["text"]}
    attach["text"] = "session rolledback!"
    attachments.append(attach)
    message.send_webapi('', json.dumps(attachments))
    session.close()

