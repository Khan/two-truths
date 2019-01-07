Two Truths and a Lie Bot
------------------------

To use, `/twotruths help` in any slack channel.  To deploy, `make deploy`.  You'll need secrets.py, which should look like:
```py
TOKEN = '<value of K333>'  # @twotruths
DB_PASSWORD = '<value of K334>'  # two_truths
```

To test that it's working, `/twotruths leaderboard` (perhaps in #bot-testing).

To connect directly to the prod DB (e.g. to fix things up), .env/bin/activate, then `make proxy` in one terminal and `DEBUG=false ipython2` in another.
