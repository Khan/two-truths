PROJECT_ID=two-truths
INSTANCE_ID=two-truths

lint:
	flake8

proxy:
	@echo "Make sure DB_PASSWORD is set in app_secrets.py"
	which cloud_sql_proxy >/dev/null || gcloud components install cloud_sql_proxy
	cloud_sql_proxy -dir /tmp/cloudsql -instances=$(PROJECT_ID):us-central1:$(INSTANCE_ID)=tcp:3306

deploy: lint
	@[ -f app_secrets.py ] || ( echo "*** Please create app_secrets.py! ***" ; exit 1 )
	gcloud app deploy --project $(PROJECT_ID) app.yaml

