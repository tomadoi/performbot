# coding=utf-8
from slackbot.bot import listen_to, respond_to

import datetime
import json
import re
import sys, traceback
from itertools import chain

try:
    import bs4
except:
    import BeautifulSoup as bs4
import dateparser
import dateutil.parser
import requests

import db
from db import Deadline, ResponseDeadline

#session = db.Session()
_cfp_url_cache, _true_cfp_url_cache = dict(), dict()


def query_for_item(item, session, table=Deadline, field=Deadline.item):
    if '%' not in item:
        item += '%'  # prefix search
    results = list(session.query(table).filter(field.like(item)))
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


def get_cfp_from_wikicfp(conf_wikicfp_url):
    global _true_cfp_url_cache
    if conf_wikicfp_url in _true_cfp_url_cache:
        return _true_cfp_url_cache[conf_wikicfp_url]
    resp = requests.get(conf_wikicfp_url)
    soup = bs4.BeautifulSoup(resp.text)
    rows = soup.findAll(
        'div', {'class': 'contsec'})[0].findAll('td', {'align': 'center'})
    return [r for r in rows[:5] if "Link:" in r.text][0].a['href']


def get_conf_wikicfp_url(conference_name, try_get_true_cfp=False):
    global _cfp_url_cache
    if conference_name in _cfp_url_cache:
        return _cfp_url_cache[conference_name]

    WIKICFP_URL = "http://wikicfp.com"
    resp = requests.get(
        WIKICFP_URL + "/cfp/servlet/tool.search?q={conference_name}&year=a".format(
            conference_name=conference_name.replace(' ', '+')))
    soup = bs4.BeautifulSoup(resp.text)
    rows = soup.findAll(
        'div', {'class': 'contsec'})[0].findAll(
        'td', {'align': 'left'})[0].findAll('tr')
    headers = rows[0]
    # Make sure the page we got was valid
    assert map(unicode.strip, map(bs4.Tag.getText, headers.contents)) == ['Event', 'When', 'Where', 'Deadline']
    links = []
    for row_num in range(1, len(rows), 2):
        try:
            conf_info = list(chain(rows[row_num].findAll('td'),
                                   rows[row_num + 1].findAll('td')))
            if conference_name.lower() not in conf_info[0].text.lower():
                continue
            shortname, name, dates, location, deadlines = tuple(
                t.text for t in conf_info)
            conf_wikicfp_url = WIKICFP_URL + conf_info[0].a['href']
            links.append(conf_wikicfp_url)
        except:
            ##traceback.print_exc()
            ##sys.stderr.write("Row %d doesn't contain a conference entry.\n" % (row_num,))
            pass
    # There should only be one matching link; if there are multiple, the query
    # was not specific enough, and if there is none, the CFP isn't on WikiCFP
    assert len(links) == 1
    _cfp_url_cache[conference_name] = links[0]

    # Optionally, try to get the conference's CFP URL, not just the WikiCFP page
    if try_get_true_cfp:
        try:
            return get_cfp_from_wikicfp(links[0])
        except:
            pass
    return links[0]


@respond_to(r'^((?!abstract).*\S(?<!is))(\s+is)?\s+((on|in)\s+\S.*)', re.IGNORECASE)
def set_deadline(message, item, _, datestr, __):
    if 'response' in item or 'notification' in item:
        return
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
            message.reply("More than one matching deadline: {}".format(', '.join(x.item
                                                                                 for x in q)))
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


@respond_to(r'^(early\s+(reject\s+)?|first\s+round\s+|(final\s+)?(acceptance\s+)?)(response\s+|notification\s+)for\s+(.*\S(?<!is))(\s+is)?\s+((on|by)\s+\S.*)', re.IGNORECASE)
# Accepts commands of the form:
#     "(first round|early|early reject) (response|notification) for conference is (on|by) date"
# for early reject/first round notification dates, and of the form:
#     "(final)? (acceptance)? (response|notification) for conference is (on|by) date"
# for final notification dates.
def add_notification_date(message, notification_type, _, __, ___, ____, item, _____, datestr, ______):
    date_is_valid, date = parse_and_verify_date(datestr, strict=True)
    if not date_is_valid:
        error_msg = date
        message.reply(error_msg)
        return

    # Figure out the notification type
    if not notification_type or notification_type.isspace() or 'final' in notification_type or 'acceptance' in notification_type:
        notification_type = 'final acceptance notification'
        updated_field = 'notification_date'
        other_notification_type = 'early notification'
    else:
        notification_type = 'early notification'
        updated_field = 'early_response_date'
        other_notification_type = 'final acceptance notification'

    # Look up existing item
    session = db.Session()
    try:
        q = query_for_item(item, session)
        if not q:
            message.reply("No matching deadlines")
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(', '.join(x.item
                                                                                 for x in q)))
        else:
            if date <= q[0].date:
                datestr = q[0].date.strftime("%b %d, %Y")
                message.reply("{} date can't be before conference deadline: "
                              "{} is on {}".format(notification_type.capitalize(),
                                                   q[0].item, datestr))
                return

            resp = query_for_item(item, session, ResponseDeadline, ResponseDeadline.item)
            if not resp:
                r = ResponseDeadline(item=q[0].item, early_response_date=None, notification_date=None)
                session.add(r)
            else:
                r = resp[0]  # there should be only one because Deadline.item acts as a de facto foreign key constraint
                # Make sure the early response date is after the acceptance notification date, if both exist
                early_response_date = (date if updated_field == 'early_response_date' else
                                       r.early_response_date if r.early_response_date is not None else None)
                notification_date = (date if updated_field == 'notification_date' else
                                     r.notification_date if r.notification_date is not None else None)
                if early_response_date and notification_date and notification_date <= early_response_date:
                    datestrs = { 'early notification': early_response_date.strftime("%b %d, %Y"),
                                 'final acceptance notification': notification_date.strftime("%b %d, %Y") }
                    message.reply("Early notification date can't be on or after final acceptance "
                                  "notification date! {} date is {}, but {} date provided is "
                                  "{}".format(other_notification_type.capitalize(),
                                              datestrs[other_notification_type], notification_type,
                                              datestrs[notification_type]))
                    return

            datestr = date.strftime("%b %d, %Y")
            message.reply(("{} date updated: " if getattr(r, updated_field) != None
                           else "Set {} date: ").format(notification_type).capitalize() +
                          "{} for {} comes back by {}".format(notification_type,
                                                              r.item, datestr))
            setattr(r, updated_field, date)
            session.commit()
    except:
        session.rollback()
        message.reply("Encountered error when adding {} date".format(notification_type))
        raise
    finally:
        session.close()


@respond_to('^when\s+does\s+(.*\S(?<!come))\s+come\s+back\??$', re.IGNORECASE)
def get_notification_date(message, item):
    session = db.Session()
    try:
        q = query_for_item(item, session)
        if not q:
            message.reply("No matching deadlines")
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(', '.join(x.item
                                                                                 for x in q)))
        else:
            r = query_for_item(q[0].item, session, ResponseDeadline, ResponseDeadline.item)
            if not r or (not r[0].early_response_date and not r[0].notification_date):
                message.reply("I don't have any notification dates for {}! Maybe you can provide them... ( ͡° ͜ʖ ͡°)".format(q[0].item if not r else r[0].item))
                return
            response = ""
            if r[0].early_response_date:
                datestr = r[0].early_response_date.strftime("%b %d, %Y")
                response += "early notification for {} comes back by {}".format(r[0].item, datestr)
            if r[0].notification_date:
                datestr = r[0].notification_date.strftime("%b %d, %Y")
                response += "{}final acceptance notification{} comes by {}".format(
                    " and " if response else "", " for {}".format(r[0].item) if not response else "", datestr)
            message.reply(response[0].upper() + response[1:] + '.')
    except:
        session.rollback()
        raise
    finally:
        session.close()


@respond_to(r'^clear\s+(early\s+(reject\s+)?|first\s+round\s+)(response\s+|notification\s+)(date\s+)?for\s+(.*)', re.IGNORECASE)
def clear_early_notification_date(message, notification_type, _, __, ___, item):
    session = db.Session()
    try:
        q = query_for_item(item, session)
        if not q:
            message.reply("No matching deadlines")
            return
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(', '.join(x.item
                                                                                 for x in q)))
            return

        r = query_for_item(q[0].item, session, ResponseDeadline, ResponseDeadline.item)
        if not r or not r[0].early_response_date:
            message.reply("No early notification date is set for {}".format(r[0].item))
        else:
            message.reply("Cleared early notification date for {}".format(r[0].item))
            r[0].early_response_date = None
            session.commit()
    except:
        session.rollback()
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
            message.reply("More than one matching deadline: {}".format(', '.join(x.item
                                                                                 for x in q)))
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
            try:
                deadline_text = '<{cfp_url}|{conf_name}>'.format(
                    cfp_url=get_conf_wikicfp_url(deadline.item),
                    conf_name=deadline.item)
            except:
                deadline_text = deadline.item
            if days > 1:
                abstract_message = ""
                if deadline.abstract_date != None:
                    abstract_days = (deadline.abstract_date - datetime.date.today()).days
                    if abstract_days < 0:
                        abstract_message = ""
                    elif abstract_days == 0:
                        abstract_message = " (*abstract due TODAY!*)"
                    elif abstract_days == 1:
                        abstract_message = " (abstract due tomorrow)"
                    else:
                        abstract_message = " (abstract due in {} days)".format(
                            abstract_days)
                attach["text"] = "{} days until {}{}".format(days, deadline_text,
                                                             abstract_message)
            elif days == 1:
                attach["text"] = "*{} tomorrow!*".format(deadline_text)
            else:
                attach["text"] = "*{} TODAY!*".format(deadline_text)
                attach["color"] = "#ff0000"
            if days < 7 and days > 0:
                attach["color"] = "#ffff00"
            attachments.append(attach)
    except:
        session.rollback()
        message.reply("Exception on query!")
        error = True
        raise
    finally:
        if not error:
            if attachments:
                message.send_webapi('', json.dumps(attachments))
            else:
                message.reply("No deadlines!")
        session.close()


@listen_to(r'^notification\s+dates?', re.IGNORECASE)
@respond_to(r'notification\s+dates?', re.IGNORECASE)
def list_notification_dates(message):
    notifications = []
    session = db.Session()
    error = False
    try:
        for deadline in session.query(ResponseDeadline).order_by(ResponseDeadline.notification_date):
            days = (deadline.notification_date - datetime.date.today()).days
            if days < 0:
                continue
            try:
                deadline_text = '<{cfp_url}|{conf_name}>'.format(
                    cfp_url=get_conf_wikicfp_url(deadline.item),
                    conf_name=deadline.item)
            except:
                deadline_text = deadline.item

            # Early notifications
            if deadline.early_response_date != None:
                early_notification_days = (deadline.early_response_date - datetime.date.today()).days
                if early_notification_days >= 0:
                    early_notif = {"mrkdwn_in": ["text"]}
                    if early_notification_days == 0:
                        early_notif["text"] = "*Early notifications for {} come back TODAY!*".format(deadline_text)
                    elif early_notification_days == 1:
                        early_notif["text"] = "Early notifications for {} come back tomorrow".format(deadline_text)
                    else:
                        early_notif["text"] = "Early notifications for {} come back in {} days".format(deadline_text, early_notification_days)
                    notifications.append((early_notification_days, early_notif))

            # Final notifications
            notif = {"mrkdwn_in": ["text"]}
            if days > 1:
                notif["text"] = "Final notifications for {} come back in {} days".format(deadline_text, days)
            elif days == 1:
                notif["text"] = "*Final notifications for {} come back tomorrow!*".format(deadline_text)
            else:
                notif["text"] = "*Final notifications for {} come back TODAY!*".format(deadline_text)
            notifications.append((days, notif))
    except:
        session.rollback()
        message.reply("Exception on query!")
        error = True
        raise
    finally:
        if not error:
            if notifications:
                notifications.sort()
                response = []
                for days, notif in notifications:
                    if days == 0:
                        notif["color"] = "#ff0000"
                    elif days < 7 and days > 0:
                        notif["color"] = "#ffff00"
                    response.append(notif)
                message.send_webapi('', json.dumps(response))
            else:
                message.reply("No notification dates!")
        session.close()


@respond_to('^forget(\s+about)?\s+(.*)', re.IGNORECASE)
def forget_deadline(message, _, match):
    session = db.Session()
    try:
        q = query_for_item(match, session)
        if not q:
            message.reply("No matching deadlines")
        elif len(q) > 1:
            message.reply("More than one matching deadline: {}".format(', '.join(x.item
                                                                                 for x in q)))
        else:
            message.reply("Deleted deadline {}".format(q[0].item))
            r = query_for_item(match, session, ResponseDeadline, ResponseDeadline.item)
            if r:  # there should be only one because Deadline.item acts as a de facto foreign key constraint
                session.delete(r[0])
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
        - To record an early notification date: early notification for conference is on date \r\
        - To record a final notification date: (final)? notification for conference is on date \r\
        - To clear an early notification date: clear early notification date for conference\r\
        - To check notification dates for an individual conference: when does conference come back? \r\
        - To check current deadlines: deadlines? \r\
        - To check all notification dates: notification dates? \r\
        \r\
        *Note*: I am always listening for the word deadlines but you have to tag me for adding/removing. \r\
        \r\
        *Update*: I can tell you about notification dates now!"
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

