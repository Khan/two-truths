#!/usr/bin/env python3
import collections
import datetime
import functools
import logging
import random
import re
import os

import flask
import flask_sqlalchemy
import requests

import app_secrets


DB_INSTANCE = 'two-truths:us-central1:two-truths'
DB_USER = 'two_truths'
DB_NAME = 'two_truths'
USERNAME = 'Two Truths and a Lie Bot'
ICON_EMOJI = ':thinking_face:'


if os.environ.get('DEBUG', 'true').lower() == 'true':
    DATABASE_URI = 'sqlite:///%s/db.sqlite' % os.getcwd()
elif os.environ.get('GAE_VERSION'):
    path = '/cloudsql/%s' % DB_INSTANCE
    DATABASE_URI = 'mysql+pymysql://%s:%s@/%s?unix_socket=/cloudsql/%s' % (
        DB_USER, app_secrets.DB_PASSWORD, DB_NAME, DB_INSTANCE)
else:
    DATABASE_URI = 'mysql+pymysql://%s:%s@127.0.0.1/%s' % (
        DB_USER, app_secrets.DB_PASSWORD, DB_NAME)


app = flask.Flask(__name__)
app.config.update({
    'SQLALCHEMY_DATABASE_URI': DATABASE_URI,
    'SQLALCHEMY_TRACK_MODIFICATIONS': False,
})
db = flask_sqlalchemy.SQLAlchemy(app)


class SlackError(Exception):
    pass


class Statement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(32), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    veracity = db.Column(db.Boolean)


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(32), nullable=False)
    statement_id = db.Column(db.ForeignKey(Statement.id), nullable=False)

    statement = db.relationship("Statement")


class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(32), nullable=False)
    ts = db.Column(db.String(32), nullable=False)
    closed = db.Column(db.Boolean, nullable=False, default=False)
    timestamp = db.Column(db.DateTime, nullable=False)


def call_slack_api(call, data=None):
    data = data or {}
    logging.debug("Sending to slack: %s", data)
    data['token'] = app_secrets.TOKEN
    res = requests.post('https://slack.com/api/' + call, data).json()
    logging.debug("Got from slack: %s", res)
    if res.get('ok'):
        return res
    else:
        raise SlackError(res.get('error', str(res)))


def send_message(channel, message):
    return call_slack_api(
        'chat.postMessage',
        {'channel': channel, 'text': message,
         'username': USERNAME, 'icon_emoji': ICON_EMOJI})


MENTION_RE = re.compile(r'^<@([A-Z0-9]*)\|([^ >]*)>$')
EMOJIS = ('one', 'two', 'three')
ORDINALS = ('first', 'second', 'third')


def _in_channel(handler):
    @functools.wraps(handler)
    def wrapped(args, channel, user_id):
        # TODO(benkraft): Use the magic slack in channel syntax instead
        message = handler(args, channel, user_id)
        send_message(channel, message)
        return ':+1:'

    return wrapped


def handle_add(args, channel, user_id):
    usage = "usage: add @person <statement>"
    if ' ' not in args:
        return usage
    mention, statement = args.split(' ', 1)
    m = MENTION_RE.match(mention)
    if not m:
        return usage
    statement = Statement(user_id=m.group(1), text=statement,
                          timestamp=datetime.datetime.utcnow())
    db.session.add(statement)
    db.session.commit()
    return ':+1:'


def _get_user_real_name(user_id):
    resp = call_slack_api('users.info', {'user': user_id})
    return resp['user']['profile']['real_name'] or '@%s' % resp['user']['name']


def handle_open(args, channel, user_id):
    usage = "usage: open @person"
    m = MENTION_RE.match(args)
    if not m:
        return usage
    user_id, username = m.groups()
    if db.session.query(
            Poll.query.filter_by(user_id=user_id).exists()).scalar():
        return "There's already a vote on %s!" % username

    statements = (Statement.query.filter_by(user_id=user_id)
                  .order_by(Statement.timestamp).all())
    if len(statements) != 3:
        return "%s has %s statements, not 3." % (username, len(statements))

    message = ("Time to vote on %s's three statements!  "
               "React with the number of the lie.\n%s" %
               (_get_user_real_name(statements[0].user_id),
                '\n'.join(':%s: %s' % (emoji, statement.text)
                          for emoji, statement in zip(EMOJIS, statements))))
    resp = send_message(channel, message)

    for emoji in EMOJIS:
        # Add initial reactions.
        call_slack_api('reactions.add',
                       {'name': emoji, 'channel': channel,
                        'timestamp': resp['ts']})

    db.session.add(Poll(user_id=user_id, ts=resp['ts'],
                        timestamp=datetime.datetime.now()))
    db.session.commit()
    return ':+1:'


def handle_close(args, channel, user_id):
    usage = "usage: close @person :<lie>:"
    if ' ' not in args:
        return usage
    mention, lie = args.split(' ', 1)

    m = MENTION_RE.match(mention)
    if not m:
        return usage
    user_id, username = m.groups()

    lie = lie.strip().strip(':')
    if lie not in EMOJIS:
        return usage

    poll = Poll.query.filter_by(user_id=user_id).one_or_none()
    if not poll:
        return "There's not a vote on %s!" % username
    if poll.closed:
        return "The vote on %s is already closed!" % username

    statements = (Statement.query.filter_by(user_id=user_id)
                  .order_by(Statement.timestamp).all())

    for emoji, statement in zip(EMOJIS, statements):
        if emoji == lie:
            statement.veracity = False
        else:
            statement.veracity = True

    for emoji in EMOJIS:
        call_slack_api('reactions.remove',
                       {'name': emoji, 'channel': channel,
                        'timestamp': poll.ts})
    resp = call_slack_api('reactions.get',
                          {'timestamp': poll.ts, 'channel': channel,
                           'full': True})

    for reaction in resp['message']['reactions']:
        if reaction['name'] in EMOJIS:
            statement_id = statements[EMOJIS.index(reaction['name'])].id
            db.session.add_all([
                Vote(user_id=u, statement_id=statement_id)
                for u in reaction['users']])

    resp = send_message(
        channel, "The lie was :%s:!  Thanks for playing." % lie)

    db.session.commit()
    return ':+1:'


@_in_channel
def handle_leaderboard(args, channel, user_id):
    votes = (db.session.query(Vote.user_id, db.func.count(Vote.id),
                              Statement.veracity)
             .select_from(Vote).join(Statement)
             .filter(Statement.veracity.isnot(None)))
    heading = "Two Truths and a Lie Leaderboard"
    if args.isdigit():
        try:
            year = int(args)
            start = datetime.datetime(year, 1, 1)
            end = datetime.datetime(year + 1, 1, 1)
            votes = (votes.filter(Statement.timestamp >= start)
                     .filter(Statement.timestamp < end))
            heading = "%s %s" % (heading, args)
        except Exception:
            return "%s doesn't seem like a valid year to me!" % args

    votes = votes.group_by(Vote.user_id, Statement.veracity).all()

    users = collections.defaultdict(lambda: {'total': 0})
    for user_id, votes, veracity in votes:
        if not veracity:
            users[user_id]['correct'] = votes
        users[user_id]['total'] += votes

    for user, data in list(users.items()):   # list() so we can delete items
        # TODO(benkraft): reddit comment score instead of threshold
        if data['total'] < 5:
            del users[user]

    for data in users.values():
        data['%'] = 100 * float(data.get('correct', 0)) / float(data['total'])

    leaderboard = sorted(users.items(),
                         reverse=True, key=lambda item: item[1]['%'])

    return "%s:\n%s" % (heading, '\n'.join(
        '%s. %s with %.0f%% (%s/%s)' % (
            i + 1, _get_user_real_name(user_id),
            data['%'], data['correct'], data['total'])
        for i, (user_id, data) in enumerate(leaderboard[:5])))


def _get_positional_stat(stmts):
    stmts_by_user = collections.defaultdict(list)
    for stmt in stmts:
        stmts_by_user[stmt.user_id].append(stmt)

    by_position = collections.defaultdict(int)
    for stmts_for_user in stmts_by_user.values():
        for index, stmt in enumerate(stmts_for_user):
            if not stmt.veracity:
                by_position[index] += 1
    total = sum(by_position.values())

    sorted_positions = sorted(by_position.items(), key=lambda item: item[1])

    index, freq = sorted_positions[-1]
    pct = 100 * float(freq) / float(total)
    return (f'The {ORDINALS[index]} statement is the most '
            f'common lie at {pct:.0f}% of the time.')


def _make_fraction_lies_stat_getter(description, predicate):
    def getter(stmts):
        matching = [stmt for stmt in stmts if predicate(stmt)]
        num = len(matching)
        lies = [stmt for stmt in matching if not stmt.veracity]
        pct = 100 * float(len(lies)) / float(num)
        return f'Of {num} statements {description}, {pct:.0f}% are lies.'

    return getter


def _common_words(stmts):
    return collections.Counter(word.lower() for stmt in stmts
                               for word in stmt.text.split())


def _get_common_words_stat(stmts):
    true_words = _common_words(stmt for stmt in stmts if stmt.veracity)
    false_words = _common_words(stmt for stmt in stmts if not stmt.veracity)

    true_only = None
    for word, ct in true_words.most_common():
        if word not in false_words:
            true_only = (word, ct)
            break

    false_only = None
    for word, ct in false_words.most_common():
        if word not in true_words:
            false_only = (word, ct)
            break

    return [
        f"The word '{true_only[0]}' is the most common word in truths "
        f"({true_only[1]} times) which does not appear in any lie.",
        f"The word '{false_only[0]}' is the most common word in lies "
        f"({false_only[1]} times) which does not appear in any truth.",
    ]


_STAT_GETTERS = [
    _get_positional_stat,
    _make_fraction_lies_stat_getter(
        'mentioning a number',
        lambda stmt: any(char.isdigit() for char in stmt.text)),
    _make_fraction_lies_stat_getter(
        'mentioning a number of two or more digits',
        lambda stmt: any(word.isdigit() and len(word) > 1
                         for word in stmt.text.split())),
    _make_fraction_lies_stat_getter(
        'mentioning a child',
        lambda stmt: ('child' in stmt.text or 'son' in stmt.text
                      or 'daughter' in stmt.text)),
    _make_fraction_lies_stat_getter(
        'mentioning a parent',
        lambda stmt: ('parent' in stmt.text or 'mom' in stmt.text
                      or 'mother' in stmt.text or 'dad' in stmt.text
                      or 'father' in stmt.text)),
    _get_common_words_stat,
]


@_in_channel
def handle_stats(args, channel, user_id):
    heading = 'Two Truths and a Lie Stats'
    stmts = (Statement.query.filter(Statement.veracity.isnot(None))
             .order_by(Statement.timestamp).all())
    stats = []
    for getter in _STAT_GETTERS:
        stat = getter(stmts)
        if isinstance(stat, (list, tuple)):
            stats.extend(stat)
        else:
            stats.append(stat)
    return '{}:{}'.format(heading, ''.join(f'\n- {s}' for s in stats))


def handle_mystats(args, channel, user_id):
    votes = (db.session.query(Statement.timestamp, Statement.veracity)
             .select_from(Vote).join(Statement)
             .filter(Vote.user_id == user_id)
             .filter(Statement.veracity.isnot(None))
             .all())
    if not votes:
        return 'No votes recorded for you yet!'

    # TODO: stats by year, etc.
    correct = len([1 for ts, veracity in votes if not veracity])
    total = len(votes)
    percent = 100 * float(correct) / float(total)
    return f'Your all time stats: {correct}/{total} ({percent:.0f}%).'


def handle_help(args, channel, user_id):
    return ('To show the leaderboard, `/twotruths leaderboard [year]`.\n'
            'To see global stats, `/twotruths stats`.\n'
            'To see your stats, `/twotruths mystats`.\n'
            'To see this help, `/twotruths help`.')


def handle_adminhelp(args, channel, user_id):
    return ('To add a statement, `/twotruths add @person Statement text`.\n'
            'To open voting, `/twotruths open @person`.\n'
            'To close voting, `/twotruths close @person :<lie-emoji>:`.\n'
            'To see this admin help, `/twotruths adminhelp`.\n'
            'To see help for user commands, `/twotruths help`.')


def handle_debughelp(args, channel, user_id):
    return ('Commands include: '
            '__createtables, __droptables, __version, __whoami')


def handle_createtables(args, channel, user_id):
    logging.warning("DATABASE URI:", DATABASE_URI)
    db.create_all()
    return ':+1:'


def handle_droptables(args, channel, user_id):
    logging.warning("DATABASE URI:", DATABASE_URI)
    db.drop_all()
    return ':+1:'


def handle_version(args, channel, user_id):
    return os.environ.get('GAE_VERSION', '?!')


def handle_whoami(args, channel, user_id):
    return f'Hello, <@{user_id}>!'


HANDLERS = {
    'add': handle_add,
    'open': handle_open,
    'close': handle_close,
    'leaderboard': handle_leaderboard,
    'stats': handle_stats,
    'mystats': handle_mystats,
    'help': handle_help,  # also the default
    'adminhelp': handle_adminhelp,
    '__createtables': handle_createtables,
    '__droptables': handle_droptables,
    '__version': handle_version,
    '__whoami': handle_whoami,
}


@app.route('/command', methods=['POST'])
def handle_slash_command():
    text = flask.request.form.get('text')
    channel = flask.request.form.get('channel_id')
    if '__as' in text:
        text, user_mention = text.split('__as')
        user_id = user_mention.strip(' <@>').split('|')[0]
        text = text.rstrip()
    else:
        user_id = flask.request.form.get('user_id')
    if not text or ' ' not in text:
        command = text
        args = ''
    else:
        command, args = text.split(' ', 1)
    try:
        return HANDLERS.get(command, handle_help)(args, channel, user_id), 200
    except Exception as e:
        logging.exception(e)
        # We have to give 200 (a lie), or Slack won't even show the message.
        return f"Something went very wrong: {e}! Ping @benkraft for help.", 200


@app.route('/ping', methods=['GET'])
def handle_ping():
    return 'OK', 200


@app.errorhandler(500)
def server_error(e):
    logging.exception(e)
    return "Something went wrong.", 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=9000, debug=True)
