PROJECT_ID=two-truths
INSTANCE_ID=two-truths


proxy:
	@echo "Make sure DB_PASSWORD is set in secrets.py"
	cloud_sql_proxy -dir /tmp/cloudsql -instances=$(PROJECT_ID):us-central1:$(INSTANCE_ID)=tcp:3306 -credential_file .credentials.json

deploy:
	gcloud app deploy --project $(PROJECT_ID) app.yaml

