Two Truths and a Lie Bot
------------------------

To use, `/twotruths help` in any slack channel.  To deploy, `make deploy`.  You'll need `app_secrets.py`, which should look like:
```py
BOT_TOKEN = '<keeper ID YN6eUmbB8H7qnO8o_Wfc-A>'
VERIFICATION_TOKEN = '<keeper ID yQWnNvs5WEdVEUyQRB5Tgg>'
DB_PASSWORD = '<keeper ID BUA1A04VVqnMLyILDRPNJw>'  # username: two_truths
```
(The secrets are all in the "Two Truths bot" folder.)

To test that it's working, `/twotruths __version` or `/twotruths leaderboard` (perhaps in #bot-testing).

To connect directly to the prod DB (e.g. to fix things up), .env/bin/activate, then `make proxy` in one terminal and `DEBUG=false ipython3` in another.

## TODO

stats:
- am I statistically significantly better than random
- better leaderboard sorting based on some sort of confidence interval
- other leaderboard rankings
- look up a particular person's statements

admin:
- manage & edit past statements (useful both for fixing typos and if we accidentally get dupes or something)
