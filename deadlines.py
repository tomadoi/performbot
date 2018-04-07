from slackbot.bot import listen_to, respond_to
import re
import dateutil.parser
import dateparser
import datetime
import json
from db import Deadline
import db

#session = db.Session()


def query_for_item(item, session):
    if '%' not in item:
        item += '%'  # prefix search
    results = list(session.query(Deadline).filter(Deadline.item.like(item)))
    return results


def parse_and_verify_date(datestr, strict=False):
    parsed = dateparser.parse(datestr)
    if not parsed:
        # can't parse so ignore the date
        return False, "Can't parse date {}".format(datestr)
    date = parsed.date()
    today = datetime.date.today()
    if date < today:
        if date.year == today.year and not strict:
            date = date.replace(year=date.year + 1)
        else:
            # too far in the past
            return False, "Deadline already passed"

    return True, date


@respond_to(r'^((?!abstract).*\S(?<!is))(\s+is)?\s+((on|in)\s+\S.*)', re.IGNORECASE)
def set_deadline(message, item, _, datestr, __):
    date_is_valid, date = parse_and_verify_date(datestr)
    if not date_is_valid:
        error_msg = date
        message.reply(error_msg)
        return
    session = db.Session()
    try:
        q = query_for_item(item, session)
        if q:
            datestr = q[0].date.strftime("%b %d, %Y")
            message.reply("Deadline already exists! {} is on {}".format(item,
                                                                        datestr))
        else:
            datestr = date.strftime("%b %d, %Y")
            d = Deadline(date=date, item=item, abstract_date=None, old_date=None)
            session.add(d)
            session.commit()
            message.reply("Set deadline: {} is on {}".format(item, datestr))
    except:
        session.rollback()
        message.reply("Encountered error when adding deadline")
        raise
    finally:
        session.close()


@respond_to(r'^abstract\s+for\s+(.*\S(?<!due))(\s+due)?\s+((on|by)\s+\S.*)', re.IGNORECASE)
def add_abstract_deadline(message, item, _, datestr, ___):
    date_is_valid, date = parse_and_verify_date(datestr, strict=True)
    if not date_is_valid:
        error_msg = date
        message.reply(error_msg)
        return
    # Look up existing item
    session = db.Session()
    try:
        q = query_for_item(item, session)
        if not q:
            message.reply("No matching deadlines")
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(x.item
                                                                       for x in q))
        else:
            if date > q[0].date:
                datestr = q[0].date.strftime("%b %d, %Y")
                message.reply("Abstract deadline can't be after conference "
                              "deadline: {} is on {}".format(q[0].item, datestr))
                return
            datestr = date.strftime("%b %d, %Y")
            message.reply(("Abstract deadline updated: "
                           if q[0].abstract_date != None
                           else "Set abstract deadline: ") +
                          "abstract for {} is due on {}".format(q[0].item, datestr))
            q[0].abstract_date = date
            session.commit()
    except:
        session.rollback()
        message.reply("Encountered error when adding abstract deadline")
        raise
    finally:
        session.close()


@respond_to(r'^(.*\S(?<!moved))(\s+moved)\s+to\s+(\S.*)', re.IGNORECASE)
def change_deadline(message, item, _, datestr):
    date_is_valid, date = parse_and_verify_date(datestr)
    if not date_is_valid:
        error_msg = date
        message.reply(error_msg)
        return
    session = db.Session()
    try:
        q = query_for_item(item, session)
        if not q:
            message.reply("No existing deadline for {}".format(item))
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(x.item
                                                                       for x in q))
        else:
            again = q[0].old_date != None
            q[0].old_date = q[0].date
            q[0].date = date
            session.commit()
            datestr = date.strftime("%b %d, %Y")
            message.reply("Deadline updated{}: {} is now on {}".format(
                " again" if again else "", item, datestr))
    except:
        session.rollback()
        message.reply("Encountered error when changing deadline")
        raise
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
                abstract_message = ""
                if deadline.abstract_date != None:
                    abstract_days = (deadline.abstract_date - datetime.date.today()).days
                    if abstract_days == 0:
                        abstract_message = " (*abstract due TODAY!*)"
                    elif abstract_days == 1:
                        abstract_message = " (abstract due tomorrow)"
                    else:
                        abstract_message = " (abstract due in {} days)".format(
                            abstract_days)
                attach["text"] = "{} days until {}{}".format(days, deadline.item,
                                                             abstract_message)
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


@respond_to('^forget(\s+about)?\s+(.*)', re.IGNORECASE)
def forget_deadline(message, _, match):
    session = db.Session()
    try:
        q = query_for_item(match, session)
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
        raise
    finally:
        session.close()


@respond_to('help?', re.IGNORECASE)
def show_help(message):
    attachments = []
    attach = {"mrkdwn_in": ["text"]}
    attach["text"] = "I can only understand the following language:\r\
        \r\
        - To add conference to the database: conference is on date \r\
        - To remove conference from database: forget about conference \r\
        - To add an abstract deadline: abstract for conference due by date \r\
        - To record a deadline change: conference moved to date \r\
        - To check current deadlines: deadlines? \r\
        \r\
        *Note*: I am always listening for the word deadlines but you have to tag me for adding/removing. \r\
        \r\
        *Update*: I can handle duplicates now!"
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

