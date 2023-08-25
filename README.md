Two Truths and a Lie Bot
------------------------

To use, `/twotruths help` in any slack channel.  To deploy, `make deploy`.  You'll need `app_secrets.py`, which should look like:
```py
BOT_TOKEN = '<latest secret from https://console.cloud.google.com/security/secret-manager/secret/Slack__API_token_for_two_truths_bot/versions?project=khan-academy>'
VERIFICATION_TOKEN = '<latest secret from https://console.cloud.google.com/security/secret-manager/secret/two_truths_bot_DB_password/versions?project=khan-academy>'
DB_PASSWORD = '<latest secret from https://console.cloud.google.com/security/secret-manager/secret/two_truths_bot_DB_password/versions?project=khan-academy>'
# username: two_truths

```
(The secrets all have the "two_truths_bot" label.)

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
