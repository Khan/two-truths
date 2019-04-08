import collections
import datetime
import logging
import re
import os

import flask
import flask_sqlalchemy
import requests

import secrets


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
        DB_USER, secrets.DB_PASSWORD, DB_NAME, DB_INSTANCE)
else:
    DATABASE_URI = 'mysql+pymysql://%s:%s@127.0.0.1/%s' % (
        DB_USER, secrets.DB_PASSWORD, DB_NAME)


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
    data['token'] = secrets.TOKEN
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


def handle_add(args, channel):
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


def handle_open(args, channel):
    usage = "usage: open @person"
    m = MENTION_RE.match(args)
    if not m:
        return usage
    user_id, username = m.groups()
    if db.session.query(Poll.query.filter_by(user_id=user_id).exists()).scalar():
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


def handle_close(args, channel):
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


def handle_leaderboard(args, channel):
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

    for user, data in users.items():
        # TODO(benkraft): reddit comment score instead of threshold
        if data['total'] < 5:
            del users[user]

    for data in users.values():
        data['%'] = 100 * float(data.get('correct', 0)) / float(data['total'])

    leaderboard = sorted(users.items(),
                         reverse=True, key=lambda item: item[1]['%'])

    message = "%s:\n%s" % (heading, '\n'.join(
        '%s. %s with %.0f%% (%s/%s)' % (
            i + 1, _get_user_real_name(user_id),
            data['%'], data['correct'], data['total'])
        for i, (user_id, data) in enumerate(leaderboard[:5])))
    send_message(channel, message)

    return ':+1:'


def handle_help(args, channel):
    return ('To show the leaderboard, /twotruths leaderboard [year].\n'
            'To see this help, /twotruths help.')


def handle_adminhelp(args, channel):
    return ('To add a statement, /twotruths add @person Statement text.\n'
            'To open voting, /twotruths open @person.\n'
            'To close voting, /twotruths close @person :<lie-emoji>:.\n'
            'To see this admin help, /twotruths adminhelp.\n'
            'To see help for user commands, /twotruths help.')


def handle_createtables(args, channel):
    logging.warning("DATABASE URI:", DATABASE_URI)
    db.create_all()
    return ':+1:'


def handle_droptables(args, channel):
    logging.warning("DATABASE URI:", DATABASE_URI)
    db.drop_all()
    return ':+1:'


def handle_version(args, channel):
    return os.environ.get('GAE_VERSION', '?!')


HANDLERS = {
    'add': handle_add,
    'open': handle_open,
    'close': handle_close,
    'leaderboard': handle_leaderboard,
    'help': handle_help,  # also the default
    'adminhelp': handle_adminhelp,
    '__createtables': handle_createtables,
    '__droptables': handle_droptables,
    'version': handle_version,
}


@app.route('/command', methods=['POST'])
def handle_slash_command():
    text = flask.request.form.get('text')
    channel = flask.request.form.get('channel_id')
    if not text or ' ' not in text:
        command = text
        args = ''
    else:
        command, args = text.split(' ', 1)
    return HANDLERS.get(command, handle_help)(args, channel), 200


@app.route('/ping', methods=['GET'])
def handle_ping():
    return 'OK', 200


@app.errorhandler(500)
def server_error(e):
    logging.exception(e)
    return "Something went wrong.", 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=9000, debug=True)
